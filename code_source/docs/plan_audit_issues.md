# ALJ-CRM — Audit: main issues and remediation plan

> Written 2026-10-12 against `main` @ `46c998b` (app 2.6.2, web v19). Findings come from reading the code and from
> a few runtime checks. Every finding below went through a "grilling" pass: the strongest objection, an answer, and a
> verdict with a confidence level. Findings that did not survive are listed in §4 so nobody re-raises them.

## 1. How this was done (and its limits)

**Read:** `ARCHITECTURE.md`, `GEMINI.md`, `server.py` (routes, middleware, OAuth), `api_auth.py`, `firestore.rules`,
`cloud_database.py` (full), `helloasso_webhook_service.py`, `email_dispatch_service.py`, `secret_store.py`,
`google_drive_client.py`, `launcher/updater_core.py` + `launcher.py`, packaging scripts, CI/deploy workflows, Dockerfile,
both requirements files. Surveyed (not read line by line): Qt pages (~12k lines), `sqlite_repository.py`, the web pages.

**Ran:**
- A probe (`scratchpad/probe_oauth.py`, outside the repo) that drives the real FastAPI app with
  `ALJ_API_AUTH=required` and **no token**. It proves F1 (see below).
- The non-Qt test suite on Linux / Python 3.12 / latest deps: **342 passed, 1 failed, 2 skipped**. The one failure is
  `test_gmail_contacts_virtual_groups`, which imports PySide6 (not installed in my venv). So the suite is healthy.
- `git log -G` scans of the full history for secret patterns, and a check that the repo is public.

**Not done:** no deployed-service testing, no Firestore data inspection, no Qt GUI run, no check of the Google Cloud
console (OAuth client redirect URIs, Firebase Auth providers, IAM). Items that depend on those are marked **needs
confirmation**. Jolli memory was not available in this session (MCP tools not registered), so no past decisions were
consulted; where the code looks deliberate I say so.

**Second pass (same day):** added F13-F15 and §7 after reading the service worker, the projection sync, the
spreadsheet guards, the iframe sandboxing and the web listeners. Items added later are tagged *second pass*.

## 2. Architecture in one paragraph (what the issues hang off)

One Python code base builds two products. A **Qt desktop app** (Windows, portable zip, self-updating from GitHub
releases) and a **FastAPI service on Cloud Run** (`server.py`) that serves static HTML/JS pages plus a small API.
Firestore is the source of truth. `server.py` keeps an **ephemeral SQLite cache** replicated to Firestore
(`cloud_database.py`: triggers → per-field push, `_modified_at` pull, 3-way merge). Browsers also read/write Firestore
**directly** through the Firebase SDK, protected only by `firestore.rules`. Roles are derived from **hard-coded e-mail
lists** duplicated in `api_auth.py`, `firestore.rules` and the JS. The stated direction is "migrate everything to the
web, then delete the Qt layer". The repository is **public**.

## 3. Issue register

| ID | Sev | Area | Issue |
|----|-----|------|-------|
| F1 | **P0** | Security | OAuth callback is public and unverified: reflected XSS + anonymous overwrite of the club's Google credentials |
| F2 | **P1** | Security | One shared, over-scoped, plaintext-at-rest Google refresh token (Gmail full access + Drive + Contacts + Firestore) |
| F3 | **P1** | Security | Auto-updater fails open on integrity and has no authenticity check, and it runs with the club's secrets |
| F4 | **P1** | Reliability | Web-initiated token renewal is not durable on Cloud Run (ephemeral, per-instance) |
| F5 | **P2** | Reliability/Audit | Cloud Run write path is best-effort and unattributed (flush failures swallowed; `_modified_by` = OS user) |
| F6 | **P2** | Reliability | Webhook and several routes return HTTP 200 on internal errors, so HelloAsso will not retry |
| F7 | **P2** | Delivery | CI does not test what production runs; no CD; unpinned production dependencies |
| F8 | **P2** | Privacy/Access | Coarse access model: coaches read all member data incl. emergency/health fields; roles hard-coded in a public repo; domain-based admin |
| F9 | **P2** | Architecture | Logic duplicated across Python/JS and across two web forks, with no behavioural parity tests |
| F10 | **P3** | Maintainability | `server.py` is a 1.9k-line monolith; Qt god files; thin static analysis |
| F11 | **P3** | Observability | `print()`-only logging, `/health` is static, no alerting, no rate limits |
| F12 | **P3** | Docs/Hygiene | Stale docs, diverged root duplicates, version drift, legacy packaging script that copies `.env` |
| F13 | **P2** | Cost/Latency | Every admin write rewrites the whole `adherents` projection, synchronously, and fans out to every open browser |
| F14 | **P3** | Security | Third-party scripts without SRI; the `/map` page (member names + addresses) can be exfiltrated by a CDN compromise |
| F15 | **P2** | Privacy | No retention/erasure policy or tooling; member addresses sent to a public geocoder; `adherents` projection leaks emergency data to the read-only tier |
| R1–R6 | — | Requirements | Non-functional requirements that are missing or unstated (see §7) |

Sequencing is in §6. §5 lists open questions that need the club's decision or a measurement.

---

## F1 — OAuth callback: public, unverified, reflected XSS  (P0)

**Evidence** (`src/server.py`, `src/infrastructure/api_auth.py`)
- `PUBLIC_PATHS` includes `/api/auth/google/login`, `/callback`, `/status` (`api_auth.py:75-77`) because the browser
  redirect from Google cannot carry a Bearer token.
- `google_auth_callback` (`server.py:1568`) never validates `state`: it is plain base64 JSON, decoded in a bare
  `try/except` (`:1642-1649`), no nonce, no signature, not tied to a session or to an authenticated admin.
- Untrusted values are interpolated unescaped into HTML: `error` (`:1625`), `redirect_uri` and Google's response body
  (`:1693-1695`), `str(e)` (`:1682`), and `return_to` — taken from the unsigned `state` — lands in both an inline
  `<script>` (`:1582`) and an `href` (`:1756`).
- Anyone who reaches the callback with a `code` causes `SecretStore.set_secret` for `GMAIL_CLIENT_ID`,
  `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_USER_EMAIL` (`:1730-1734`).
- The only response header added is `frame-ancestors 'self'` (`:83`): no script CSP.

**Proof (ran it).** With `ALJ_API_AUTH=required` and no Authorization header: a protected route returns 401, while
`/api/auth/google/callback?error=<img src=x onerror=alert(document.domain)>` returns 200 with the payload reflected raw;
a crafted `state` injects `return_to` into the JS string; and with Google mocked, an anonymous call writes all four
secrets.

**Why it matters.** The page is on the same origin as the admin web app, where Firebase Auth state lives in
browser storage. A coach/admin who clicks a crafted link gives the attacker that session: send e-mails and attestations
from the club address, edit members, read the member database. Separately, an attacker can run the Google flow with
their own account against the club's OAuth client and have the server adopt their refresh token (login CSRF / token
swap): the club's outgoing mail would then go through the attacker's mailbox, and Drive/Contacts calls would hit it too.

**Grilling.**
- *"Needs a valid Google `code`, so it isn't exploitable."* — That blocks only the token swap, and only if the callback
  URI is unregistered in the OAuth client; the XSS needs no `code` at all, and the probe shows it. The swap is feasible
  for anyone with a Google account **if** `…/api/auth/google/callback` is a registered redirect URI (the feature shipped
  in 2.6.1, so it very likely is). **Needs confirmation** in the Cloud console.
- *"The Firebase token is short-lived."* — The Firebase refresh token sits next to it in IndexedDB, and the injected
  script can simply call the API as the user while the page is open.
- *"Admins won't click strange links."* — The payload sits on the club's own domain and can be delivered in an e-mail
  that looks like the club's own OAuth flow.
- **Verdict: confirmed, high confidence (XSS and unauthenticated secret write proven by probe).**

**Remediation**
1. Escape everything: `html.escape()` for `error`, `redirect_uri`, `err_detail`, exception text; stop echoing Google's
   response body. Better: render with a Jinja2 autoescape template instead of f-strings.
2. Make `login` **admin-only**: the front-end fetches a login URL via `apiFetch` (Bearer), the server issues a
   signed state `HMAC(secret, uid|nonce|ts)` bound to the admin's `uid`, stored server-side with a 10-minute TTL. The
   callback verifies signature, TTL, single use. Reject otherwise.
3. Validate `return_to` as a same-origin relative path (`^/[A-Za-z0-9/_-]*$`); ignore the `redirect_uri` query param
   (compute it from configuration, not from the request or from state).
4. Put `/api/auth/google/status` behind coach (it discloses the club Gmail address and error strings, and, once credentials are
   configured, it triggers an outbound Google token refresh on every anonymous hit — read from the code, not probed); move `/api/auth/google/test` to admin (currently falls to
   coach).
5. Add a script CSP to every HTML route (`default-src 'self'` + the CDN/Firebase allow-list; inline scripts need
   nonces, so this is a staged task — do 1–4 first).
6. Add tests: reflected payload is escaped; callback with a forged/absent/expired state is rejected; secrets are never
   written on rejection.

**Effort:** S for 1, 3, 4; M for 2; M for 5. **Do first.**

---

## F2 — One shared, over-scoped Google credential  (P1)

**Evidence.** `google_auth_login` requests `https://mail.google.com/` (full mailbox), `gmail.send`, full `drive`,
`contacts`, `datastore` and `userinfo.email` in one consent (`server.py:1547-1554`). The same refresh token feeds
Gmail sending, the Drive copy, Google Contacts, and Firestore access from the desktop (`firestore_client.py` falls
back to the club's OAuth outside GCP). `SecretStore.set_secret` writes the secret to `.env` **always**, even when the
keyring succeeded (`secret_store.py:55-92`); the installer also writes a `.env` per PC.

**Why it matters.** Any compromised bureau PC (or any leaked `.env`) is a full Firestore bypass of `firestore.rules`
(IAM, not rules), full mailbox access and full Drive access. The keyring is defeated by the plaintext copy.

**Grilling.**
- *"`mail.google.com` is needed for SMTP XOAUTH2."* — Not here: both senders call the REST
  `gmail.googleapis.com/.../messages/send` (`email_repository.py:166`, `email_sender.py:78`), which needs only
  `gmail.send`. The SMTP branch uses `SMTP_*` credentials. So the full scope is unnecessary. (Confidence: high.)
- *"Full `drive` is needed for the legacy shared `database.db`."* — Partly true: `drive.file` cannot open a file the app
  did not create. Since the main DB moved to Firestore (v2.4.0), the Drive path is a rollback option and an export.
  Decide whether to keep it (§5, Q3).
- *"It's a small club, simplicity wins."* — Fair as a trade-off, but the cost of a leak is the whole member database
  and mailbox; the fixes below are cheap.
- **Verdict: confirmed, high confidence on scopes; medium on exploitability** (depends on how many PCs hold the `.env`).

**Remediation**
1. Drop `https://mail.google.com/`; keep `gmail.send`. Re-consent once.
2. Firestore from desktop: replace the user refresh token with per-user sign-in (the desktop users already have
   Google accounts) or a service-account key stored only in the OS keyring/DPAPI. Remove `datastore` from the shared
   token.
3. `SecretStore.set_secret`: if keyring succeeded, **do not** write to `.env`; keep the file fallback only for
   environments without a keyring, and `chmod 600` / restrict ACL.
4. Decide on the Drive path (Q3): if retired, remove `drive` and `contacts` scopes from the default flow and request
   `contacts` only on demand.

**Effort:** S (1, 3), M–L (2).

---

## F3 — Auto-updater integrity and authenticity  (P1)

**Evidence.** `launcher.py:72-78`: the checksum is verified only `if sums_asset:`; `updater_core.verify_download`
returns **True** when the sums file is empty or has no line for the zip. Hash and zip are served from the same release,
so the hash only guards against corruption; there is no signature. The updater then compiles and swaps the new
`app/`, and `pip install -r requirements.txt` from the new package (`pip_sync`). The extracted code runs on PCs that
hold the club's `.env`. `extract_zip_flat` also joins archive member names without a traversal check in its
"single root" branch.

**Grilling.**
- *"The attacker would need to control the GitHub release."* — Yes: one maintainer account/PAT with unknown MFA
  state, on a public repo (anyone with write access can publish a release). Low likelihood, very high impact (code execution on every bureau PC with Gmail/Firestore
  access). The fail-open check, by contrast, is a free fix.
- *"The zip-slip is irrelevant: whoever controls the zip already delivers code."* — Agreed: hardening only, I keep it
  in the fix list because it is a one-liner, not as a separate risk.
- **Verdict: confirmed (code-read), high confidence; priority driven by impact, not likelihood.**

**Remediation**
1. Missing/unmatched `SHA256SUMS.txt` ⇒ **abort** the update (fail closed). Add a test for each branch.
2. Sign releases (minisign, or GitHub artifact attestations / Sigstore) and embed the public key in the launcher;
   verify before swap.
3. Pin the update channel: require the tag to match `VERSION`, reject downgrades (already `is_newer`) and
   reject `app/` packages whose `requirements.txt` adds unknown indexes/URLs.
4. Add a path-traversal guard to `extract_zip_flat` and use `pip --require-hashes` once requirements are pinned
   with hashes.
5. Enable branch protection + required MFA on the maintainer account (process item).

**Effort:** S (1, 4), M (2, 3).

---

## F4 — Web-initiated token renewal is not durable on Cloud Run  (P1)

**Evidence.** `SecretStore.set_secret` persists to the keyring (absent in the Docker image) and a `.env` under
`/app` plus `os.environ` of **that one process**. Cloud Run's filesystem is ephemeral and the service runs up to 2
instances (`deploy_cloud_run.sh`). `load_dotenv` does not override an existing environment, and the deployment guide
sources secrets from Secret Manager (`--update-secrets …`) with no documented path that writes a renewed token back.
Cloud Run's Firestore access uses the metadata server, so this affects Gmail/Drive/Contacts only.

**Grilling.**
- *"It works in my tests."* — The unit test mocks `set_secret` (`test_google_auth_web.py`), so it cannot show
  persistence. In real use it would appear to work until the instance recycles or the second instance serves the
  request; then e-mail sending silently reverts to the old (possibly revoked) token.
- *"Maybe a startup hook re-reads from somewhere."* — I found none (`_iter_credential_candidates` reads only
  SecretStore and `.env` files on disk). **Needs confirmation** on the deployed service: renew via the web, wait for a
  new revision/instance, call `/api/email-status` and `/api/auth/google/test`.
- **Verdict: confirmed by code reading, medium-high confidence; runtime check recommended.**

**Remediation:** on Cloud Run, write the refreshed token to **Secret Manager** (new version) and read it at start /
on `invalid_grant`; keep `.env` only for desktop. Alternatively drop the user-OAuth Gmail path on Cloud Run for a
service-account with domain-wide delegation, or a transactional mail provider. Add a "token source" field to
`/api/auth/google/status` so the UI says where the token lives.

**Effort:** M.

---

## F5 — Cloud Run write path: best-effort durability, no attribution  (P2)

**Evidence.** `cloud_db_middleware` (`server.py:53-66`) runs `after_write` *after* the route has produced its
response; `CloudDatabase.flush_only` catches every exception, stores `_last_error`, logs, and returns
(`cloud_database.py:923-941`). The client has already received success. Pending rows live only in the instance's SQLite
file. The background sync thread is started only by the desktop (`main_window.py:572`), so on Cloud Run there is no
retry besides the next request on the same instance. `_modified_by` is always `CloudDatabase.who()` = OS user@host
(`:861-866`); `request.state.user` is never used for it.

**Grilling.**
- *"The next request retries the flush."* — True while the instance lives and receives traffic; with
  `min-instances 0` an idle instance is reclaimed with its pending changes. Rare (needs a Firestore failure *and* a
  recycle), but it is silent data loss.
- *"Audit isn't a stated requirement."* — Not stated; but members' e-mail/phone can be edited from the web and the
  club handles minors' data, so "who changed this" is a reasonable accountability expectation. Firestore rules log
  nothing by default.
- **Verdict: confirmed (code-read); severity depends on how often Firestore calls fail — I did not measure it.**

**Remediation:** (1) route handlers that write must call `flush_only()` *before* returning and return 503 on failure
(the cache stays dirty, the user sees the error); (2) pass the Firebase `uid`/e-mail into `flush` for `_modified_by`;
(3) expose `CloudDatabase.status()` (pending count, last error) in an admin-only status route and in `/health` details.

**Effort:** S–M.

---

## F6 — HTTP 200 on internal errors (webhook and others)  (P2)

**Evidence.** The HelloAsso webhook returns `{"status": "error", …}` with **HTTP 200** on any unexpected exception
(`server.py:1097-1098`), while the deliberate rejection paths return 4xx/5xx, and `helloasso_webhook_service.py:153`
explicitly relies on a 503 so that "HelloAsso renverra la notification plus tard". `get_planning`/`update_planning`
(`:912-918`, `:1052-1059`) and several others also return 200 with an `error` key.

**Grilling.**
- *"There's a manual `/api/helloasso/sync` as a backstop."* — True, which caps the damage: a missed payment
  notification is only repaired when someone clicks sync. It stays a silent failure until then.
- *"Does HelloAsso really retry on non-200?"* — The code's own comment assumes so; I did not confirm in HelloAsso's
  docs. **Needs confirmation.**
- **Verdict: confirmed as a bug class (error status codes); impact medium.**

**Remediation:** return 500/503 for unexpected webhook failures (still without leaking details); make `/api/planning`
etc. return proper status codes and adapt the JS callers; add tests asserting status codes on failure.

**Effort:** S.

---

## F7 — CI/CD doesn't cover what production runs  (P2)

**Evidence.** CI (`tests.yml`) runs on **windows-latest, Python 3.13, `requirements.txt`** (pandas 3.0.3 pinned).
Production is **Linux, Python 3.11, `requirements-docker.txt`** with `pandas>=2.2.0`, `pillow>=10`, `lxml>=5`,
`weasyprint>=60` unpinned, so every Cloud Build can install different versions than any test saw. Deployment is a manual
script from Cloud Shell; there is no test gate, no staging (the `--test` revision uses **production** Firestore, as the
script itself warns), and `deploy-pages.yml` publishes `web/` on every push to `main`. No Dependabot config.

**Grilling.**
- *"The suite passes anyway."* — Yes: I ran the non-Qt tests on Linux/3.12 with latest dependencies and got 342
  passes. That is evidence the code is fine today, not that it is protected: nothing enforces it.
- *"WeasyPrint on Linux is covered."* — I did not verify that any test renders a real PDF with WeasyPrint (they
  may mock the renderer). **Needs confirmation.**
- *"A club project doesn't need CD."* — A manual deploy that skips tests is the path by which F1-class issues ship.
  The fix is small.
- **Verdict: confirmed, high confidence.**

**Remediation:** add an `ubuntu-latest` job (Python 3.11, `requirements-docker.txt` + dev) running the non-Qt tests;
pin production dependencies with hashes (`pip-compile`); add Dependabot (pip, actions); add a `workflow_dispatch`
deploy workflow (Workload Identity Federation) gated on the tests, with the existing `--test` → promote flow; consider
a separate Firebase project (or the emulator, already available) for pre-prod.

**Option for the dependency half: adopt [`uv`](https://docs.astral.sh/uv/) instead of `pip-compile`.** Today three
installs (`tests.yml`, `build-executable.yml`, the `Dockerfile`) each run plain `pip install -r` against hand-kept
requirements files, and `pyproject.toml` declares no dependencies. With `uv`:
- declare dependencies once in `pyproject.toml`, using groups or extras for the desktop, web and dev profiles;
- commit one cross-platform `uv.lock` with hashes. It resolves Windows/3.13 and Linux/3.11 together, so CI and
  production install the same versions;
- replace the three `pip install` steps with `uv sync --frozen` (CI uses `astral-sh/setup-uv`; the `Dockerfile` copies
  the `uv` binary from the official image). `--frozen` fails the build if the lock is out of date, which closes the
  "every Cloud Build installs something new" gap;
- Dependabot supports `uv`, so it can propose lock updates, and the faster installs shorten CI and Docker builds.

*Grilled.*
- *"It fixes the mismatch."* — Only the **dependency** part. A lockfile does not make CI run Linux or Python 3.11, so the
  Ubuntu/3.11 job above is still required, and ideally it runs inside the production image.
- *"New tool for a volunteer-run club."* — The cost is one file and a few commands; the lock replaces two requirements
  files that already drift. Keep `requirements*.txt` generated (`uv export`) for a transition period if the
  PyInstaller build is slow to migrate.
- *"Python range."* — `requires-python` was `>=3.10` while production is 3.11 and CI is 3.13. **Verified by a spike:**
  with `pandas==3.0.3` pinned, `uv lock` refuses `>=3.10`; the range has to be `>=3.11`. With that, one lock resolves
  for 3.11–3.13 and all existing pins are preserved.
- *"The desktop package can use it too."* — No. The portable build and the updater run `pip install -r requirements.txt`
  inside an embedded Python on club members' PCs. That path stays on pip, fed by a `requirements.txt` generated from
  `uv.lock` (`code_source/dev/export_requirements.py`).

**Status (migration in the working tree, not committed):** `pyproject.toml` groups + `uv.lock`, generated
`requirements*.txt` with a CI freshness check, `uv`-based `tests.yml` / `build-executable.yml`, `Dockerfile` using
`uv sync --frozen` (built and smoke-tested locally: `/health` 200, WeasyPrint PDF renders, no Qt/pywin32 in the image),
Dependabot config. Known follow-up: Dependabot's `uv` PRs update `pyproject.toml`/`uv.lock` only, so they fail the
export check until `python dev/export_requirements.py` is run on them.

**Effort:** M.

---

## F8 — Access model and personal data  (P2)

**Evidence.**
- `firestore.rules:105-112`: every `crm_*` document is readable by any **coach** — including emergency contacts and
  health-commitment fields (`schema_v2.py:66-69`, `:107`) of all members. Coaches and read-only users are individuals
  identified by personal e-mail addresses.
- Role lists are hard-coded in `api_auth.py:47-58`, `firestore.rules`, and the JS (a test keeps them aligned). The
  repository is **public**, so these addresses are world-readable. The admin rule also grants admin to anyone with a
  verified `@alj-escalade.fr` address.
- Rules authorise writes by role only; no field validation, so any coach can write arbitrary shapes to
  `competitions`, `coaches`, `helloasso_items` straight from the browser, bypassing the API.
- Logs: `print()` of full addresses in the geocoding task (`server.py:117`) lands in Cloud Logging.

**Grilling.**
- *"The firestore web `apiKey` is in the repo."* — Not an issue; Firebase web config is public by design (see §4).
- *"Coaches need the contact data."* — Probably some do, for their own groups; the issue is "all members, all fields".
  That is a policy question (Q1), not a defect I can settle.
- *"The domain rule is standard."* — It is, and it is safe while the club controls the domain and Google verifies the
  address. If the domain lapses or MX is hijacked, ownership of any address grants admin. Low likelihood.
- **Verdict: confirmed as design risk; severity depends on club policy. Public exposure of personal e-mails is a
  certain, cheap-to-fix privacy leak.**

**Remediation:** move roles to Firebase custom claims (set by an admin-only route) or a `roles` collection read by both
API and rules, so no addresses live in code; split sensitive columns (health, emergency) into a separate collection
readable by admins only; add minimal shape validation in rules for browser-written collections (or route those writes
through the API); drop address logging; review the `@alj-escalade.fr` wildcard once claims exist. Because the repo is
public, rewriting history to remove the e-mail addresses is optional and only worthwhile if the club asks (§5, Q2).

**Effort:** M (claims), M (collection split).

---

## F9 — Duplicated logic and no parity tests  (P2)

**Evidence.** `alj-members.js` re-implements the SQL view `v_adherents_legacy` in JavaScript, including `calcAge` and
season logic (`ARCHITECTURE.md` §3 states any schema change must be mirrored by hand). `web/competitions.html` (2.7k
lines) and `web/bureau/competitions.html` (1.8k) are two forks of the same feature. Template-variable handling exists
in `domain/utils.apply_template_variables` and in JS strings. `tests/web` checks versions, routes and role lists; I
found no test that feeds the same data to the Python and JS implementations.

**Grilling.**
- *"The migration will delete one side anyway."* — That cuts against investing in the Qt side, not against parity
  tests on the web: the JS rebuild of the member view is the *target* architecture and nothing checks it.
- *"It's tested manually."* — With a 2.6.x web version and many pages, that does not scale to one maintainer.
- **Verdict: confirmed, medium confidence on risk (no incident observed).**

**Remediation:** a golden-data test (a fixed Firestore-shaped fixture → expected members/ages/groups) run under both
`pytest` and a Node script, so changes to either side fail CI; collapse `competitions.html` into the bureau page plus a
mobile layout (or share a module); define the data contract (`docs/base_firestore.md`) as a JSON Schema validated in
both.

**Effort:** M–L.

---

## F10 — Size and structure  (P3)

- `server.py` is 1,916 lines: ~600 lines of inline HTML for `/map` and `/pivot` (`:391-909`), OAuth flow, e-mail,
  attestations, member update, sync. Split into `APIRouter` modules and templates; the F1 fix is a natural first
  extraction (`routers/google_auth.py`).
- Qt: `competitions.py` 2,414, `communications.py` 2,267, `groups.py` 1,347, `workers.py` 1,241 lines; one
  *infrastructure* test imports a Qt worker (`test_infrastructure_lot2.py:427`), so some logic lives in `workers.py`.
  **Recommendation: do not refactor Qt wholesale** — the plan is to remove it. Extract only logic that the web needs
  (that is already the §6 recipe in `ARCHITECTURE.md`).
- Static analysis is thin by design: ruff `E4,E7,E9,F,B`, mypy on two files. Widen mypy gradually to
  `api_auth.py`, `cloud_database.py`, `domain/`, and add `bandit`/`ruff S` to catch F1-class f-string HTML.

**Grilling.** *"Large files aren't bugs."* — Agreed; this is P3 and only worth doing along the way. The layering is
better than the docs suggest: I found no SQL in `presentation/` and no `infrastructure`/`domain` → Qt imports.

## F11 — Observability and abuse limits  (P3)

`print()` everywhere (no severity, so Cloud Logging shows everything as one level); `/health` returns a static
"healthy" even if Firestore sync is failing; no alerting; **no rate limiting anywhere** (the unauthenticated surface is
small after F1, but `/api/dashboard` and e-mail sending let a coach call HelloAsso/Gmail repeatedly; there is no cap on
recipients per send for coaches). Fix: `logging` with JSON severity, `/health` that includes last sync error and
pending count, a Cloud Monitoring alert on 5xx and on sync errors, a per-user cap on e-mail sends.

## F12 — Docs and hygiene  (P3)

`ARCHITECTURE.md` says branch `feat/nux_setup`, version 2.5.8, `server.py` ~1,400 lines (actual 2.6.2 and 1,916);
`GEMINI.md` still describes Tkinter/Word-COM; `pyproject.toml` says 2.0.5; the repo root holds **diverged copies**
of `install.bat`, `pytest.ini`, `deploy_cloud_run.bat`, `Lancer_ALJ.vbs`, `GEMINI.md` (diffs of 6-470 lines vs
`code_source/`); the legacy `build_package.py` still copies a local `.env` into its release folder, contradicting its
own header comment (CI does not use it; delete it). Fix: delete root duplicates (keep one-line forwarders if needed),
generate version from `VERSION`, refresh `ARCHITECTURE.md` as part of each release, remove dead packaging.

---

## F13 — Whole-projection rewrite on every write  (P2)

*Added in the second pass.*

**Evidence.** After any request that pushes rows to `users/orders/purchases/planning/seasons`, `after_write` calls
`refresh_projection()` (`cloud_database.py:1034-1040`), which runs `sync_adherents_from_main`
(`competition_firestore_repository.py:220-375`). That function reads every row of `v_adherents_legacy` and
`planning`, builds a document per member and writes them **all** through `batch_upsert` (450 per commit) — no diff,
and `updated_at: now` guarantees every document changes. The only throttle (`projection_every=180`) is in the
desktop's `background_tick`; the Cloud Run path (`after_write`) has none. It happens inside the request, before the
response is returned (`server.py:53-66`). The browsers hold live `onSnapshot` listeners on `adherents`
(`bureau/competitions.html:612`, `index.html:396`, `alj-members.js:263`).

**Effect.** One edit of one phone number, or one attestation sent, costs ≈ *N members* + *N planning rows* Firestore
writes, adds 1-3 sequential HTTP commits to the user's wait, and then every connected client re-reads the whole
collection (≈ *N* reads × clients). Sending 300 attestations one by one ≈ 300 × *N* writes.

**Grilling.**
- *"Firestore's free quota would stop the app."* — Probably not: deploying with `--source` requires a billing account,
  so overage is billed (cents), not blocked. The real costs are latency, quota-burn against the "0 €/month" goal in
  the Dockerfile header, and noisy fan-out. I did not see the real *N* or the bill. **Needs measurement** (§5, M4).
- *"It guarantees the projection is always correct."* — True, and that is why it was built this way; the fix keeps that
  property by diffing.
- **Verdict: confirmed mechanism (code-read), medium confidence on magnitude.**

**Remediation:** write only changed members (compare a content hash stored in the doc; drop `updated_at` from the
hashed payload); move the refresh out of the request path (enqueue + coalesce within e.g. 30 s, or Cloud Tasks);
ideally project per row from the pushed `report` instead of recomputing everything.
**Effort:** M.

---

## F14 — Third-party scripts without SRI  (P3)

*Added in the second pass.*

**Evidence.** Zero `integrity=` attributes in `web/` or `server.py`. Firebase SDK 10.12.2 comes from `gstatic.com`
(version-pinned, Google-hosted) and Leaflet / MarkerCluster from `unpkg.com` in the `/map` page (`server.py:405-411`).

**Grilling.**
- *"A compromised CDN script owns the admin session."* — Not for Leaflet: `/map` and `/pivot` are loaded into
  `<iframe sandbox="allow-scripts allow-popups">` **without** `allow-same-origin` (`outils.html:56,70`), so the frame has
  an opaque origin and cannot read the parent's Firebase session. That is a good design. What remains is that the
  frame holds member names and addresses and has no `connect-src` restriction, so a poisoned script could send them
  out.
- *"unpkg is reputable."* — It is, and the version is pinned, which is why this stays P3.
- **Verdict: confirmed but low; the sandbox already contains the worst case.**

**Remediation:** self-host Leaflet in `web/shared/` (removes the third-party dependency and works offline), or add
`integrity` + `crossorigin` attributes; add `connect-src 'none'` through the CSP (F1 step 5) to the sandboxed documents.
The Firebase SDK scripts are the same-origin-critical ones: add SRI there too (Google publishes the hashes) and keep
the version bump a deliberate change.
**Effort:** S.

---

## F15 — Privacy posture beyond access control  (P2)

*Added in the second pass.*

1. **No retention or erasure.** Searching the code and docs for purge/retention/anonymisation/erasure finds nothing
   relevant. Members of all past seasons, including minors, with birth date, emergency contacts and health-commitment
   fields, accumulate indefinitely in `crm_*`, the SQLite cache, the `adherents` projection, desktop backups
   (`data/backups/`), Drive exports and Firestore daily exports (14 days). There is no tool to erase or export one
   person's data on request.
2. **Third-party processors.** `geocode_missing_addresses` sends each member's full postal address to the public
   OpenStreetMap Nominatim service (`server.py:103-131`; `reports.py:37` on the desktop) and caches the result in
   Firestore (`crm_geocache`). It is not documented anywhere that members' addresses leave the club's systems for this.
3. **The projection weakens the tiering.** `firestore.rules` says `crm_*` is readable by **coaches** only (health and
   emergency data included), but `/adherents` is readable by `isAuthorizedUser()` = coaches **and read-only** users
   (`firestore.rules:70-73`), and the projection copies personal e-mails, phone, birth date, gender, emergency
   contact name and phone, and the red-badge/autonomy flags into it (`competition_firestore_repository.py:316-337`).
   So the "read-only" tier can read the contact and emergency data that the rules appear to reserve for coaches.

**Grilling.**
- *"Legal retention periods require keeping them."* — Some data must be kept (accounting, insurance, federation
  licensing); that is exactly why a written policy with per-field durations is needed. The finding is the absence of a
  policy and of any deletion mechanism, not that data is kept.
- *"3 read-only users are trusted people."* — Probably; the point is that the rules advertise one thing and the
  projection does another. Either document the tier as "may see contacts", or strip the projection (Q1).
- *"Nominatim is just OSM."* — It is a public third-party endpoint with a usage policy; sending minors' home addresses
  there may need a note in the club's privacy information. Not a defect I can judge legally.
- **Verdict: item 3 confirmed from code; items 1-2 are confirmed gaps against a standard the club must confirm
  applies (assume French association data-protection rules).**

**Remediation:** (1) write a one-page retention policy (e.g. purge or anonymise members inactive for N seasons) and an
admin script/route "anonymise user X" that tombstones across `crm_*`, `adherents`, `helloasso_items`, competition
participants; (2) either self-host geocoding for the club's few hundred addresses, geocode at city level only, or record
the processor in the club's data-protection notice; (3) remove emergency and phone fields from the projection (the
PWA only needs a name and a group; fetch contact data from `crm_*` for coaches), or restrict `/adherents` to coaches.
**Effort:** S (3), M (1, 2).

---

## 4. Findings that did **not** survive grilling (do not re-raise)

| Suspicion | Why dropped |
|---|---|
| "Firebase `apiKey` committed" | Public web config by design; protection is rules + API auth. |
| "Secrets in git history" | `git log -G` hits are `votre_…` placeholders and `--update-secrets` doc lines; `dev.env` has only emulator values. |
| "Webhook is spoofable" | Fail-closed in production; items are re-read from the HelloAsso API; optional secret token; constant-time compare. The remaining nit (token in the URL appears in request logs) is minor. |
| "Mass-assignment in `/api/members/update`" | `update_member_fields` allow-lists columns. The broader `UPDATE … WHERE user_id` tarif fallback is only reachable without `purchase_id`/`order_ref`; the web always sends them. Hardening only. |
| "Middleware order wrong (auth after DB sync)" | Order is correct: security headers → local guard → auth → DB (documented in `server.py`). |
| "Local desktop server open to DNS rebinding / CSRF" | `local_guard_middleware` checks Host, Origin and `Sec-Fetch-Site`, with tests. |
| "Raw SQL / Qt leakage across layers" | Not found (see F10). |
| "Tests are weak" | 414 tests; 342 pass on Linux without Qt. Gaps are specific (F7, F9), not general. |
| "Spreadsheet/CSV formula injection from HelloAsso data" | Handled: `spreadsheet_safety.py` neutralises formulas and `csv_safe` prefixes triggers; used by all generators found (`create_excel`, presence sheets, planning export, MyCompet, FFME report). |
| "Stored XSS from member data in the web pages" | Spot-checked `adherents.html` (detail panel, table), `outils.html`, `communications.html`: member-derived values go through `esc()`; `/map` escapes names and uses `json_for_script`. Not an exhaustive audit of the 2.7k-line `competitions.html`, which uses `esc` ~60 times. |
| "`/map` and `/pivot` iframes can hijack the session" | Sandboxed without `allow-same-origin` (see F14); residual risk is data exfiltration only. |
| "No backups" | Firestore PITR (7 d) and a daily export (14 d) are documented in `docs/base_firestore.md`. The gap is restore rehearsal and infrastructure-as-code (R2), not their existence. |
| "Single-maintainer repo" | Git history shows several authors; not a finding. |
| "Coach can mail arbitrary external addresses" | `unauthorized_send_reason` restricts coaches to known member addresses. (The check looks only at `recipients`, but `recipient_ids` resolve to DB addresses, so the restriction still holds; the remaining issue is volume, F11.) |

## 5. Open questions (these need a decision or a measurement)

- **Q1 (policy):** which coach needs which fields? Basis for the F8 split of health/emergency data.
- **Q2 (policy):** is the club comfortable with its coaches' personal e-mails being public in the repo and history?
  Removing them from `main` is trivial; rewriting history is not.
- **Q3 (scope):** is the Google-Drive `database.db` rollback path still needed? It is the only reason to keep the
  full `drive` scope and part of F2.
- **M1 (measure):** is the OAuth callback URI registered on the Google OAuth client? Does web renewal persist across
  a new Cloud Run instance? (F1 impact, F4.)
- **M2 (measure):** cold-start cost. The first API call after a cold start runs `build_cache` (full read of nine
  collections) under a global lock, and every API request may trigger a 30-second-stale `sync`. Count documents and
  billed reads before the base grows.
- **M3 (measure):** does HelloAsso retry on non-2xx, and how often does a Firestore flush fail in the logs? (F5, F6.)
- **M4 (measure):** number of members/planning rows (*N*), daily Firestore reads/writes, and the current monthly
  bill. Decides how urgent F13 is.
- **Q4 (policy):** retention period per data category and who answers a data-subject request (F15, R3).
- **X1 (risk to inspect):** `renumber_row` rewrites integer primary keys when two writers collide. Competition
  participants and HelloAsso links reference adherent ids stored in other collections; I did not verify whether a
  renumber would orphan them. Low frequency, high confusion if it happens.

## 6. Suggested sequencing

1. **This week (P0/P1 quick wins, ~1-2 days):** F1 steps 1, 3, 4 + tests; F3 step 1 (fail-closed checksum); F2 step 1
   (drop `mail.google.com`) and step 3 (no plaintext `.env` when the keyring works); F6.
2. **Next (~1 week):** F1 steps 2 and 5 (signed state, CSP); F7 (Linux CI job, pinned dependencies via a `uv.lock`, Dependabot); F5
   steps 1-3; M1/M3 verifications.
3. **Then:** F4 (Secret Manager for renewed tokens); F8 (claims + data split) after Q1/Q2; F3 signing.
4. **Along the way:** F9 parity tests as each page migrates; F10/F11/F12 opportunistically.
5. **Second-pass items:** F13 diffed/deferred projection right after the M4 measurement (it also removes latency from
   every admin save); F15 item 3 (strip the projection) together with F8; F14 when the CSP lands; F15 items 1-2 and
   the §7 requirements once Q1-Q4 are answered.

Each item is independently shippable; none requires the Qt-to-web migration to finish first.

## 7. Requirements to make explicit (not defects, but currently unstated or unmet)

The code encodes many good decisions (fail-closed auth, per-field merge, escaped output, formula neutralisation,
tests for security rules). These are the expectations I could not find written down, and each one would turn an
implicit assumption into something the team can verify.

| ID | Requirement | Why it is needed here | Suggested acceptance check |
|----|-------------|-----------------------|----------------------------|
| R1 | **Security acceptance tests for every public route.** A route listed in `PUBLIC_PATHS` must have a test proving it returns no member data, escapes all reflected input and cannot change server state without proof of identity. | F1 existed because three routes were made public for a technical reason (no Bearer on a redirect) and nothing re-examined them. | A parametrised test over `PUBLIC_PATHS` + prefixes with hostile inputs; fails CI if a public route writes. |
| R2 | **Infrastructure as code and a restore drill.** Cloud Run settings, IAM, Secret Manager entries, OAuth clients, Firebase Auth providers, Firestore backups and rules deploys described in a repository (Terraform or a documented `gcloud` script), plus a yearly rehearsed restore from the daily export. | Today these live in the Cloud console and in `deploy_cloud_run.sh` flags; backups are documented but not shown to restore; M1/M3 cannot be answered from the repo. | A fresh project can be rebuilt from the repo; restore drill logged with date and result. |
| R3 | **Data-protection register and subject-request procedure.** Categories of data, purposes, processors (Google, HelloAsso, OpenStreetMap, GitHub Pages hosting), retention per category, and a runbook for access/erasure requests. | F15; the repo is public and the data concerns minors' health and emergency contacts. | A reviewed document in `docs/` and a tested "anonymise user" operation. |
| R4 | **Service objectives and alerting.** Stated targets (e.g. webhook processed within 5 minutes, admin save under 2 s, sync lag under 1 minute) and alerts on 5xx, failed sync/flush, expired Google token. | F4, F5, F6, F11: failures today are silent (HTTP 200, `print`, static `/health`). The Google token expiry in particular is a scheduled, predictable outage. | Alert fires in a drill; `/health` reports sync state and token validity. |
| R5 | **Least-privilege and rotation policy.** One credential per purpose (mail send, Firestore, Drive), documented owners, rotation schedule, and a break-glass procedure when the maintainer is unavailable. | F2, F3: today one refresh token does everything and lives on several PCs. | Inventory of credentials with scope, owner, last rotation; revocation tested. |
| R6 | **Release safety.** Releases are signed, reproducible from a tag, and tested on the production runtime profile before deploy; web and desktop versions are derived from one source. | F3, F7, F12. | CI builds both profiles from the tag; signature verified by the updater; dependencies come from one committed lockfile (`uv sync --frozen`, F7). |

Not recommended: a large rewrite of the Qt UI, a framework migration for the web pages, or a move off Firestore.
The issues above are all addressable inside the current architecture, and the stated plan (retire Qt) makes Qt
refactoring poor value.
