# Plan: route all web data access through the API (front → back → db)

## Context

The web front end (mobile PWA `web/competitions.html`, `web/index.html`, and the bureau portal `web/bureau/*`) reads **and writes** Firestore directly with the Firebase SDK, while other actions go through FastAPI. Problems this causes:

- **Business logic exists twice:** `v_adherents_legacy` is rebuilt in JS (`web/shared/alj-members.js`). Competition logic exists in JS in two divergent versions, plus in Python (`competition_firestore_repository.py`).
- **Writes bypass validation:** `firestore.rules` checks *who* writes, never *what*.
- **The bureau competitions page diverges:** different field names and a status that exists nowhere else. Its whole-array overwrites can silently lose concurrent edits.
- **Personal data spreads to phones:** every coach's phone downloads and caches every member record, including health and emergency data about minors.
- **Role lists live in three places:** rules, `api_auth.py` and JS.

**Target state:**
- The browser uses Firebase **only for sign-in** (ID token).
- Every read and write goes through `/api/*`.
- `firestore.rules` denies all client access.
- Server (service account) and desktop app (club OAuth token, IAM) keep direct access. Rules don't apply to them, so the desktop app needs no change.

## Process: stop after each phase

Phases run in order: **0 → 1 → 2 → 3 → 4**. At the end of each phase:
- **Stop.** Don't start the next phase.
- Report what was done, test results, deviations from this plan, and anything newly found (added to Appendix A/B).
- Wait for review and explicit approval before the next phase.

The plan file is updated with any decisions taken during a review. Nothing is committed or deployed without asking.

## Progress

| Phase | State | Notes |
|---|---|---|
| 0 | Done, awaiting review | Cold-start measurement still to do against production (needs a deploy). ETag responses use `Cache-Control: no-store`: the page keeps the last body and sends `If-None-Match` itself (`alj-sync.js`), so personal data never lands in the browser's HTTP cache. |
| 1 | Done, awaiting review | See « Phase 1 — as built » below. |
| 2 | Not started | |
| 3 | Not started | |
| 4 | Not started | Cleanup backlog, filled during reviews |

## Decisions taken (from review Q&A)

| # | Decision | Consequence |
|---|---|---|
| D1 | **Updates:** polling with refetch, no Firestore listeners | Each screen polls every 20 s while visible, refetches on tab focus and right after the user's own write. ETag + 304 makes unchanged polls cheap. Other coaches' changes show up within about 20 s instead of instantly. |
| D2 | **Offline:** read-only snapshot of **competitions + participants** only | Stored in `localStorage` per user, wiped on logout or loss of role. Write controls are disabled offline. The `/index` member directory becomes **online-only** (today it works offline). |
| D3 | **Cloud Run stays at min-instances 0** | A cold start rebuilds the SQLite cache before the first member-data answer. Competition routes are taken out of the SQLite middleware so they don't pay for it (see Side effects S3). |
| D4 | **Pass-through fields:** `lieu`, `type` (competition) and `present` (participant) are kept, stored as-is, migrated later | The API accepts and stores them without validation. Tracked in **Appendix B**. |
| D5 | **Competition writes need the coach role** | Bureau page checks that are admin-only today (create, edit, delete, "Participe", ✕) are relaxed to coach, matching the mobile page and the current rules. |
| D6 | **Readonly keeps its current access** | GET on competitions, coaches and the competition member list opens to `readonly`. Full member records and HelloAsso data stay coach-only. |
| D7 | **Known bugs fixed later**, documented in **Appendix A** | New endpoints don't do extra bug-fixing. Where the *existing* server repository already behaves differently from the JS, the endpoint uses the repository as-is (it is shared with the desktop app and webhook), and the difference is listed as an inherited behaviour change (Appendix A, column "After migration"). |

## Architecture choices (recommended, open to review)

1. **Routers, not `server.py`.** New routes go in `src/api/competitions.py` and `src/api/members.py` (FastAPI `APIRouter`), included from `src/server.py`, which is already about 1,900 lines. Auth stays in the path-based middleware (`api_auth.required_role`), so routers need no `Depends`.
2. **Pydantic request models** for new routes (`src/api/schemas.py`). Existing routes keep `Dict = Body(...)`; converting them is out of scope.
3. **Thin routes over existing repositories.** Competition logic stays in `CompetitionFirestoreRepository` (`src/infrastructure/competition_firestore_repository.py`). It already has optimistic locking (`_mutate_participants`, `updateTime` precondition, 5 retries) and is shared with the desktop app and webhook, so all three clients get the same semantics. Member data comes from SQLite through `SqliteRepository` + `CloudDatabase.ensure_fresh`.
4. **One JS polling helper.** New classic script `web/shared/alj-sync.js`, following the `alj-firebase.js` pattern and exposing `window.ALJSync`. It handles interval, visibility pause, focus refetch, ETag, offline detection and the snapshot store, and is usable from both the classic PWA pages and the bureau modules.
5. **Write responses return the updated resource** (e.g. the full competition), so the UI updates without waiting for the next poll.

## API to create

Roles: R = readonly+, C = coach+, A = admin. "Repo" means `CompetitionFirestoreRepository` unless stated. All list GETs support `ETag`/`If-None-Match`.

### Phase 1 — Competitions, coaches, HelloAsso links (Firestore-backed)

| Method & path | Role | Body | Implementation | Replaces (front end) |
|---|---|---|---|---|
| GET `/api/competitions` | R | — | `list_competitions()` + participants and counters, as today's docs (normalized ids, `docId` dropped). Pass-through fields included. Per-instance 5 s memory cache, invalidated on write. | `competitions` listener: `competitions.html:833`, `bureau/competitions.html:324` |
| POST `/api/competitions` | C | `{nom, id_ffme, date_competition, date_fin, prix, statut, coach_ids[≤3], helloasso_ref?, lieu?, type?}` | `save_competition` (id = ms timestamp) | `competitions.html:1261` set, `bureau/competitions.html:912` add |
| ~~PUT~~ **PATCH** `/api/competitions/{id}` | C | same fields, all optional | `save_competition` (partial update, participants untouched) | `competitions.html:1305` tx, `bureau/competitions.html:906` |
| DELETE `/api/competitions/{id}` | C | — | `delete_competition` (+ legacy doc id) | `competitions.html:1340-1342`, `bureau/competitions.html:931` |
| ~~PUT `/api/competitions/{id}/status`~~ (dropped: PATCH `{statut}`) | C | `{statut}` | `save_competition` | archive/unarchive `competitions.html:1050` |
| POST `/api/competitions/archive-past` | C | — | loop `set_competition_status("close")` over past competitions | `competitions.html:1063` |
| POST `/api/competitions/{id}/participants` | C | `{adherent_id, selectionne}` | `add_participant`, or `set_selection` if already present | `addAdherent` 1606, bureau "+ Inscrire" 717-743 |
| PATCH `/api/competitions/{id}/participants/{adherent_id}` | C | `{selectionne?, present?}` | `set_selection` (status via `statut_paiement_apres_bascule`). **409 `already_paid`** when unselecting a paid participant; the client then opens the cancel modal (today's logic at 1469/1479). `present` is stored as pass-through. | `toggleSelection` 1476, bureau Participe/Présent 630-640 |
| POST `/api/competitions/{id}/participants/{adherent_id}/cancel` | C | `{mode: "perdu"\|"reporte", note}` (note required) | `mark_cancelled` | `applyCancelModal` 1527 |
| DELETE `/api/competitions/{id}/participants/{adherent_id}` | C | — | `remove_participant` | bureau ✕ 643-648 (mobile has no UI) |
| POST `/api/competitions/{id}/load-group` | C | — | `load_competition_group_into` | `loadCompetitionGroup` 1560 |
| GET `/api/coaches` | R | — | `list_coaches` | `coaches` listener 836 |
| POST `/api/coaches` | C | `{nom}` | `save_coach` | 1692 |
| PUT `/api/coaches/{id}` | C | `{nom}` | `save_coach` (cascades names into competitions) | 1710 + cascade 1718 |
| DELETE `/api/coaches/{id}` | C | — | `delete_coach` (cascade clears `coach_ids` and `coach1..3_id`) | 1735 + cascade 1739 |
| GET `/api/competition-members` | R | — | `list_adherents()` (the `adherents` projection), with only the fields the competition pages use | `adherents` listener 839, bureau 334 |
| GET `/api/helloasso/items` | C | — | `list_mirror_items` | `helloasso_items` listener 843, bureau 338 |
| PUT `/api/helloasso/items/{id_item}/link` | C | `{competition_id\|null, adherent_id\|null, commentaire}` | `save_item_comment` + `set_item_link(source="manuel")`, or `clear_item_link` when null. Then, if both ids are set, `apply_helloasso_payment` (`add_participant` first if missing). | `saveAttachment` 2175-2215 |
| PUT `/api/helloasso/items/{id_item}/ignore` | C | `{ignore: bool, motif, commentaire}` (motif required to ignore) | **New repo method `set_item_ignored`**: `update_fields` with `expected_update_time`. **409** if the item became linked meanwhile (today's check at 2135). | `toggleIgnoreItem` 2121 |

Existing routes reused unchanged: `/api/helloasso/sync`, `/api/send-email`, `/api/email-templates`, `/api/email-status`, `/api/preview-email`. The Balance/Bilan views stay computed client-side from GET `/api/competitions`; `get_bilan` exists if we later want it on the server.

#### Phase 1 — as built (deviations and notes for review)

- **PATCH instead of PUT for competitions.** A full replace would have wiped fields the page doesn't send (`helloasso_ref`, set from the desktop app). The status route is dropped: archive/unarchive is `PATCH {statut}`.
- **Manual HelloAsso link also selects the member.** `PUT …/link` calls `add_participant(selectionne=True)` before `apply_helloasso_payment`, which doesn't select. This keeps today's « paid ⇒ participates » behaviour of the manual link.
- **Shared write helper.** `ALJSync.request()` in `alj-sync.js` is used by both pages. It sends JSON and throws an `Error` with the server's message, `status` and `code`.
- **Offline (mobile page).** Write controls are not disabled; writes are refused with a toast and the header shows « 📴 Hors ligne — données du … (lecture seule) ». The snapshot also holds the coaches list (names only, no personal data).
- **Bureau page, paid participant.** Unticking « Participe » for someone who paid now asks for a comment and « report / perdu » (`prompt` + `confirm`, minimal UI), then calls the cancel route. Before, the bureau page silently overwrote the status.
- **Bureau page field names fixed (A6).** It now reads the real fields (`nom/prenom/tarif/email`, mirror `montant/order_id/payer_*`, athlete from `raw_json`) and knows the statuses `annule_perdu/annule_reporte`. Admin-only controls are relaxed to coach (D5). It keeps no offline snapshot (desktop).
- **Repository additions** (`competition_firestore_repository.py`):
  - `ParticipantAlreadyPaid`, `ItemAlreadyLinked`;
  - `set_selection(refuse_unselect_paid=)`, `set_present`;
  - `save_manual_link`, `set_item_ignored` (precondition + retry);
  - `archive_past_competitions`, `list_competition_docs`, `get_competition_doc`, `list_item_docs`;
  - `save_competition(extra=)` for pass-through fields.
- **Tests.** The Firestore fake moved to `tests/support/fake_firestore.py` (`conftest.py` puts `tests/` on `sys.path`, as importlib mode doesn't). New route tests are in `tests/api/test_api_competitions.py`. Static checks assert that both competition pages no longer call Firestore.
- **Still loaded on these pages (removed in phase 3):** the Firestore SDK script and `enablePersistence`.

### Phase 2 — Member data (SQLite-backed)

| Method & path | Role | Implementation | Replaces |
|---|---|---|---|
| GET `/api/seasons` | C | `crm` seasons without tombstones (SqliteRepository) | `bureau/outils.html:364`; season pickers |
| GET `/api/members?season=` | C | New pure module `src/domain/member_view.py`: rows from `v_adherents_legacy` (`schema_v2.py:641`) plus the fields that only JS computes today (`age` at `YYYY-09-01`, `creneau_groupe`, `categorie`, `creneau_details`, `status_norm`, `payer`), ported from `alj-members.js:97-207`. Returns one season only (today the browser downloads every season). | `startMembersListener` (`alj-members.js:219`) used by `bureau/adherents.html:1315`; `index.html:391-404` |

Existing member writes (`/api/members/update`, `/api/attestations/*`) are unchanged. After a write, the page refetches.

### Phase 0 — Foundations (before phase 1)

- `api_auth.required_role`: add a readonly GET set (`/api/competitions`, `/api/coaches`, `/api/competition-members`) so readonly users get 200 there and 403 on everything else, as today.
- `server.cloud_db_middleware`: **skip `ensure_fresh`/`after_write` for the Firestore-only routes** (`/api/competitions*`, `/api/coaches*`, `/api/competition-members`, `/api/helloasso/items*`). See S3.
- ETag helper (`json_with_etag(request, payload)`: sha1 of the JSON body, returns 304).
- `web/shared/alj-sync.js` (polling + snapshot store) and its precache entry in `sw.js`.
- Measure cold start (time for the first `/api/members` after scale-to-zero) to confirm D3.
- Enable Cloud Run **session affinity** in `deploy_cloud_run.sh` (S4).

### Phase 3 — Lockdown (only after phases 1–2 are deployed and verified)

1. Front end: remove `firebase-firestore-compat.js` from every page and from the `sw.js` precache. `alj-firebase.js` keeps auth only (keeps the Auth emulator in dev, drops the Firestore emulator). Remove `enablePersistence` (`competitions.html:2681`, `index.html:841`).
2. **Wipe the existing Firestore offline cache on phones:** on boot, delete IndexedDB databases whose name starts with `firestore/` (`indexedDB.databases()`, falling back to the known name `firestore/[DEFAULT]/smart-amplifier-510811-n6/main`).
3. `firestore.rules`: `match /{document=**} { allow read, write: if false; }`. Role functions and e-mail lists are removed from the rules.
4. Tests: update `test_api_security.py:108` (role lists now in `api_auth.py` + display JS only), `test_firestore_rules_emulator.py` (assert deny for every role), `test_firestore_sync.py:160`.
5. Docs: `ARCHITECTURE.md` §2/§4/§5, `docs/base_firestore.md`, `README.md` (rules deploy step).
6. Web version bump to **v21** (`<meta alj-web-version>`, titles, badge, `CACHE_NAME`).
7. Deploy order (see S1): app first, rules last, after a waiting period.

### Phase 4 — Cleanup (after phase 3)

Code-quality improvements noticed during reviews. None changes behaviour; they are kept out of phases 0–3 so the migration diffs stay focused. Add new items here as they come up in reviews.

#### C1 — Roles as an enum instead of strings (`src/infrastructure/api_auth.py`)

**Problem.** Roles are plain strings (`"readonly"`, `"coach"`, `"admin"`):
- `required_role()` returns `Optional[str]`.
- `roles_for_claims()` returns a `set` of strings.
- `has_role(claims, role: str)` looks the string up in `ROLE_LEVELS = {"readonly": 1, "coach": 2, "admin": 3}`.

Consequences:
- The same literals are repeated in about ten `return "admin"` lines, in `src/server.py:1256` (`has_role(claims, "admin")`) and in about 15 test assertions.
- A typo (`"coache"`) isn't caught by mypy or the IDE. It only fails at runtime with a `KeyError` in `ROLE_LEVELS`, and only on the code path that uses it.
- The hierarchy lives in a separate dict instead of on the type.

**Change.**
1. Add an ordered enum. The order *is* the hierarchy, so `ROLE_LEVELS` is deleted:
   ```python
   from enum import IntEnum

   class Role(IntEnum):
       """Access levels, lowest to highest: a higher level includes the lower ones."""
       READONLY = 1
       COACH = 2
       ADMIN = 3
   ```
2. `required_role(method, path) -> Optional[Role]`. `None` still means "public route" (no requirement); no fake `Role.PUBLIC`.
3. Replace `roles_for_claims() -> set` with `role_for_claims(claims) -> Optional[Role]`, returning the highest level. Since admin includes coach, the set never carried more information than its maximum.
4. `has_role(claims, needed: Role) -> bool`: `role is not None and role >= needed`.
5. Error messages use `role.name.lower()` (same text as today).
6. Update callers: `src/server.py:1256` and the tests in `tests/test_api_security.py` (`test_required_role`, `test_readonly_reads`, `test_roles_for_claims`) and `tests/test_bureau_web.py` (174-176, 259-260, 475-479, 576+, 615).

**Why `IntEnum`.**
- Ranked values give ordering for free, like comparing ordinals in Java.
- Known trade-off: an `IntEnum` also equals plain ints (`Role.ADMIN == 3`). That is acceptable here.

**Alternatives considered:**
- `Enum` + `functools.total_ordering`: strict, but the comparisons have to be written by hand.
- `StrEnum`: no ordering, and it needs Python 3.11 while `pyproject.toml` declares `>=3.10`.
- `typing.Literal[...]`: type-checked, but no runtime object and no ordering.

**Out of scope.** The JS role helpers (`web/shared/alj-core.js` `roleFor`, and the PWA pages) and `firestore.rules`. The rules lose their role logic in phase 3; the JS checks only control what the UI shows.

## Front-end changes per page

- **`web/competitions.html` (PWA):**
  - Replace `startListeners`, `txCompetitionDoc`, `mutateParticipants` and the direct writes with API calls via the existing local `apiFetch` (610).
  - Keep the client-side matching suggestions (2059-2099) and the balance computation.
  - Show the snapshot with an "offline — data from HH:MM" banner and disable write controls offline.
- **`web/bureau/competitions.html`:**
  - Same API.
  - Map its divergent field names to the API shape: adherents `last_name/first_name/tarif_name/email_primary` become `nom/prenom/tarif/email`; HelloAsso items `linked_competition_id/order.*/amount/100` become `competition_id/order_id/montant`; the status `annule` becomes `annule_perdu|annule_reporte`.
  - Relax admin-only controls to coach (D5).
- **`web/bureau/adherents.html`:** replace `startMembersListener` with polling of `/api/members?season=`. Remove the members part of `alj-members.js` and keep constants and helpers (`STATUS_COLORS`, `normKey`, `telHref`, `calcAge` if still used).
- **`web/index.html`:** the same GET `/api/members`; no offline cache (D2).
- **`web/bureau/outils.html`:** use `/api/seasons`.

## Side effects and how they are handled

- **S1 — Old clients after the rules lockdown.** Installed PWAs and open tabs still running old code would get `permission-denied`.
  - Handling: since the network-first `sw.js` change, clients load new pages on their next online visit.
  - Lockdown is a separate, later deploy: rules go out ≥1 week after v21.
  - Before deploying rules, check in the GCP console that Firestore requests evaluated by rules have dropped to about 0.
  - Rollback: `git checkout <prev> -- firestore.rules && firebase deploy --only firestore:rules`. This is manual; `deploy_cloud_run.sh` doesn't deploy rules.
- **S2 — Desktop app.** Not affected: it uses the club OAuth token (IAM), not Firebase Auth, so rules don't apply. Verify the club account keeps its IAM role on the project. `firestore_sync.py` (legacy import tool) is also IAM-based and unaffected.
- **S3 — Cold start and SQLite middleware.** `cloud_db_middleware` runs `ensure_fresh` before **every** `/api/*` request. At min-instances 0, a polled competition GET would wait for a full `crm_*` cache rebuild after each cold start. Routes that only touch Firestore are therefore exempted (phase 0). Member routes still pay the rebuild once per cold start; this is accepted with D3 and measured in phase 0.
- **S4 — Read-your-writes across instances.** Up to 2 instances each have their own SQLite cache, up to 30 s stale, so a member edit made through instance A can briefly disappear on a poll served by instance B.
  - Mitigation: Cloud Run session affinity (best effort), plus the write response updates the local row.
  - Competition data reads Firestore directly, so it has no such issue beyond the 5 s per-instance cache, which is invalidated on that instance's own writes.
- **S5 — Concurrency semantics.**
  - Participant writes: per-participant operations with a Firestore `updateTime` precondition and retries. This replaces the browser transactions and the bureau whole-array overwrites.
  - Competition metadata: field-level last-writer-wins (same as today; no precondition in `save_competition`).
- **S6 — Firestore read costs from polling.** Each competition poll reads every competition doc. Mitigation: 5 s per-instance cache + ETag. Old competitions accumulate over seasons; if costs grow, add `?include_archived=false` (follow-up).
- **S7 — Cloud Run cost.** Polling keeps an instance warm only while someone has a page visible (pause when hidden). Expected impact is small; watch billing for the first month.
- **S8 — Readonly role.** Without D6's readonly GET set, readonly users would lose access entirely, because the API refuses them on every route today. Covered in phase 0.
- **S9 — Personal data.** Phones stop caching all members (all seasons). The remaining offline snapshot holds participant contacts for competitions only (D2), wiped on logout. The old Firestore IndexedDB cache is deleted (phase 3 step 2).
- **S10 — Behaviour inherited from the server repository (D7).** These replace JS behaviour:
  - HelloAsso link: the amount is **set**, not added (no more double counting, but multi-order payments keep only the last order).
  - Deleting a coach clears `coach1..3_id`.
  - Competitions created from the bureau page get a numeric id.
  - Counters are always recomputed.
  - At most 3 coaches per competition (the repo stores `coach1..3_id`; the PWA allowed more). The API returns 400 above 3; check existing data first.
- **S11 — Planning-group tie-break.** JS picks the **first** planning row matching a tariff; Python (`_read_planning_groups`, repo:342) picks the **last**. Moving `/api/members` to Python must pick one. Recommendation: use the JS rule (first by id) everywhere, so member pages don't change. The `adherents` projection may then change for members whose tariff is in two groups.
- **S12 — Dev environment.** `dev/dev.env` sets `ALJ_API_AUTH=off`, and emulator ID tokens can't pass `verify_firebase_token`, so roles can't be exercised end to end in dev. Role coverage relies on the `make_token` unit tests.
- **S13 — CI.** ~~Only runs on release tags.~~ Since #18, `tests.yml` runs pytest on push/PR (the presentation tests in separate processes).
- **S14 — Email recipient checks** (`EmailDispatchService`) already read the Firestore `adherents` projection server-side. Unchanged.

## Verification

- **Unit and route tests** (pytest, `TestClient`, `make_token` from `tests/test_api_security.py:36-72`, `FakeFirestore` from `tests/test_competition_firestore_repository.py:31-138`):
  - **Role matrix** for every new route: anonymous 401; readonly 200 on R-GETs and 403 elsewhere; coach 200 on writes.
  - Participant flows: select, unselect a paid participant (409), cancel, load group, remove, link/unlink, ignore with a concurrent link (409).
  - ETag 304.
  - Middleware exemption: the competition route doesn't call `ensure_fresh`.
  - `member_view` parity: port representative `buildMembersData` cases to Python, and compare against the seeded emulator data.
- **Static guard test:** no `firestore-compat`, `.collection(` or `enablePersistence` left under `web/` (after phase 3).
- **Rules:** `test_firestore_rules_emulator.py` asserts deny for admin, coach and readonly (`docker compose -f dev/docker-compose.yml up`).
- **Manual end to end in dev** (`dev/run_server.sh` + seed):
  - Each page loads.
  - Two browsers see each other's participant changes within about 20 s.
  - Offline mode shows the snapshot banner with writes disabled.
  - Logout wipes the snapshot.
  - Desktop app still syncs competitions.
- **Production rollout:** deploy with `--test` (0 % traffic), smoke-test, promote, wait ≥1 week, check rules-evaluation metrics, then deploy the rules.

## Critical files

`src/server.py` (router include, middleware exemption) · `src/api/{competitions,members,schemas}.py` (new) · `src/infrastructure/api_auth.py` · `src/infrastructure/competition_firestore_repository.py` (`set_item_ignored`, pass-through fields) · `src/infrastructure/sqlite_repository.py` + `src/domain/member_view.py` (new) · `web/competitions.html` · `web/index.html` · `web/bureau/{competitions,adherents,outils}.html` · `web/shared/{alj-firebase,alj-members,alj-sync(new)}.js` · `web/sw.js` · `firestore.rules` · `deploy_cloud_run.sh` · tests listed above · `ARCHITECTURE.md`, `docs/base_firestore.md`.

---

## Appendix A — Known bugs (fix later; D7)

"After migration" means fixed as a by-product (the endpoint uses existing server code), still present, or moot.

| # | Where | Bug | After migration |
|---|---|---|---|
| A1 | `web/competitions.html:2191-2215` `saveAttachment` | Re-saving an already linked HelloAsso item adds `montant_paye` again (only the order id is de-duplicated). | By-product: the repo's `apply_helloasso_payment` **sets** the amount. See A11. |
| A2 | same | Moving a link to another competition or adherent, or clearing it, doesn't undo the previous participant's payment (`paye`, `montant_paye`, `commande_helloasso` stay). | **Still present** (server has no "unapply"). |
| A3 | same, 2175 vs 2191 | The `helloasso_items` update and the participant update are two separate writes; a failure in between leaves them inconsistent. | **Still present** (two server-side writes, now with fewer failure modes). |
| A4 | `web/bureau/competitions.html:652-660` `saveCompParticipants` | Writes the whole `participants` array from the local copy with no transaction (concurrent changes lost) and doesn't recompute the counters. | By-product: per-participant endpoints with a precondition. |
| A5 | `web/bureau/competitions.html:912` | Create uses `.add()`: random doc id and no numeric `id` field, which other code treats as a legacy doc. | By-product (repo assigns the id). Existing random-id docs are still normalized on read by `_list_comp_docs`. |
| A6 | `web/bureau/competitions.html` (various) | Field names differ from the data (`last_name/first_name/tarif_name/email_primary`, `linked_competition_id`, `order.*`, `amount/100`, status `annule`), so data is likely displayed wrong or empty. | By-product: the page is rewritten against the API shape. |
| A7 | `web/competitions.html:1739` `deleteCoach` | `coach1_id`/`coach2_id`/`coach3_id` aren't cleared when a coach is deleted. | By-product (`delete_coach` clears them). |
| A8 | `web/competitions.html:1692-1735` | Coach create/update/delete have no role check in code (only the hidden tab). | Moot (API role check). |
| A9 | `web/competitions.html:1340-1342`; repo `_list_comp_docs` | Deleting a competition is two separate deletes; legacy-id normalization is a non-atomic copy then delete. | Delete: by-product. **Normalization still present.** |
| A10 | coach cascades (PWA 1718/1739; repo `_refresh_coach_names`, `delete_coach`) | Several sequential competition updates with no rollback; a failure leaves names or ids partly updated (repo just logs). | **Still present.** |
| A11 | repo `apply_helloasso_payment` (repo:668) | Overwrites `montant_paye` and `commande_helloasso`: a participant paying with several orders keeps only the last one. | **Still present** (now also on manual links). |
| A12 | repo `sync_adherents_from_main` (repo:220-339) | Projections `adherents`/`planning` are upsert-only: deleted or out-of-season members and slots are never removed. | **Still present.** |
| A13 | `alj-members.js` vs repo `_read_planning_groups` (342) | Tariff → group tie-break: JS takes the first row, Python the last. | Resolved by choosing one rule (S11). |
| A14 | `src/server.py:1803` | `/api/auth/google/test` calls `ensure_fresh(max_age_seconds=10)`, but the parameter is `max_age`: TypeError (caught), so `database.ok` is always false. The test mocks it away. | **Still present.** |
| A15 | `/api/auth/google/callback`, `update-token`; `secret_store.py:42-92` | On Cloud Run the refresh token is saved to the instance's `.env`/environment only: lost on restart, not shared between instances. | **Still present.** |
| A16 | `src/server.py:1582,1625` | `return_to` and `error` are put into HTML/JS unescaped (open redirect / reflected injection); OAuth `state` is unsigned and not checked. **Security, prioritize.** | **Still present.** |
| A17 | `/api/auth/google/status` (public) | Exposes the connected account's e-mail without authentication. | **Still present.** |
| A18 | `web/bureau/competitions.html:797-828` Bilan | Assumes every payment equals `prix`. | **Still present** (client-side computation unchanged). |
| A19 | GET `/api/planning` (server.py:912) | Appends to `planning_sync_debug.log` on every call. | **Still present.** |
| A20 | `/api/members/update` | Unknown keys in `fields` are silently ignored but echoed back as if applied. | **Still present.** |
| A21 | `cloud_database._after_sync` (944) | The projection is only marked dirty by local flushes, not by pulled changes, so desktop edits don't trigger a server rebuild. | **Still present.** |
| A22 | `CloudDatabase.ensure_fresh` (1024) | Freshness is checked outside the lock, so concurrent requests run redundant syncs; while Firestore is down, every request retries. | **Still present.** |
| A23 | `web/bureau/competitions.html:334-340` | `adherents`/`helloasso_items` listeners have no error handler. | Moot (listeners removed). |
| A24 | `web/competitions.html` | `snap.metadata.fromCache` is ignored: the status bar says "temps réel" even when showing cached data. | Moot (snapshot banner instead). |
| A25 | repo `_new_id` (ms timestamp), PWA `Date.now()` | Two competitions or coaches created in the same millisecond get the same id; the second silently overwrites the first. Found while testing phase 1. | **Still present** (unlikely in practice). |
| A26 | `FirestoreClient.update_fields` | Creates the document when it doesn't exist. A write racing a delete from another device (status change, link, comment) recreates a stub document with only the written fields. The routes check existence first, which narrows the window but doesn't close it. | **Still present.** |

## Appendix B — Fields to migrate later (D4)

Today only `web/bureau/competitions.html` writes these. They are not in `src/domain/competition_models.py`, the PWA or the desktop app. The API stores them as unvalidated pass-through values and preserves them on every write.

| Field | Level | Written at | Notes |
|---|---|---|---|
| `lieu` | competition | `bureau/competitions.html:906-917` | Free text (place). |
| `type` | competition | same | Free text; no list of values defined. |
| `present` | participant | `bureau/competitions.html:637-640`, 717-743 | Attendance flag (bool). |
| `categorie`, `tarif`, `groupe`, `created_at` | participant | bureau "+ Inscrire" 717-743 | Copied from the member at enrolment; the PWA doesn't write them. Decide whether to keep or derive. |

Migration later means: add them to the `Competition`/`Participant` dataclasses, validate them in the API, show them in the PWA and the desktop app, and backfill or clean existing documents.
