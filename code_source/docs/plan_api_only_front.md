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
| 0 | Done (approved) | Cold-start measurement still to do against production (needs a deploy). ETag responses use `Cache-Control: no-store`: the page keeps the last body and sends `If-None-Match` itself (`alj-sync.js`), so personal data never lands in the browser's HTTP cache. |
| 1 | Done (approved) | See « Phase 1 — as built » below. |
| 2 | Done, awaiting review | See « Phase 2 — as built » below. |
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
- **Layers: controller → service → repository** (added during review). `src/api/competitions.py` only handles HTTP: it parses the body, calls the service, and shapes the response (ETag, `{status: success}`). `src/services/competition_service.py` holds the rules: existence checks, partial update, pass-through fields, `already_paid`/`already_linked`/`motif_required`, and the 5 s list cache with its invalidation on write. It raises `services.errors` (`NotFound`, `InvalidRequest`, `Conflict`, `StorageUnavailable`) and turns Firestore errors into them. It knows nothing about HTTP. One exception handler, `api.responses.service_error_handler` registered in `server.py`, maps each error class to 404/400/409/503 with the same `{status, message, code}` body. Phase 2 (`/api/members`) follows the same layout.
- **Rebase on main (3ea9078): main's new bureau features ported to the API.**
  - 💶 manual payment → `POST …/participants/{aid}/manual-payment {montant > 0}` (`record_manual_payment`, written under the optimistic lock).
  - Withdrawal « report / perdu » → the cancel route; the bureau flow now asks for the required comment.
  - ↩️ restore → `POST …/participants {selectionne: true}`, which already reactivates a cancelled participant as paid.
  - `url_resultats` (now in the domain model) goes through the competition routes and the Firestore repository. A results fetch drops the competition cache, and the page reloads after it.
  - main's admin-only checks on the new controls are relaxed to coach (D5).
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

#### Phase 2 — as built (deviations and notes for review)

- **Layers, as in phase 1.**
  - Controllers: `api/seasons.py` and `api/members.py`.
  - Services: `services/season_service.py` and `services/member_service.py`.
  - Pure view: `domain/member_view.py`, ported from `buildMembersData`.
  - Repository: `SqliteRepository.list_seasons` and `list_member_rows`.
  - Both routes go through the SQLite cache middleware (`ensure_fresh`, 30 s) and are coach-only (default rule of `required_role`).
- **Response shapes.**
  - `GET /api/seasons` → `{seasons, active}`.
  - `GET /api/members?season=` → `{season, members, creneaux}`. Without `season`, the server uses the active one; an unknown season → 404 `not_found`.
  - Deviation: `creneaux` (slot groups and their tariffs) travels with the members. Both pages need it to group members, and this saves a third poll.
- **Rows come from a dedicated query, not `v_adherents_legacy`.** The view has no `purchase_id`, which `/api/members/update` needs. It also runs one subquery per insurance option for every row, which the pages don't use.
  - `test_member_rows.py` checks that the query returns the same people as the view.
- **Age at the start of the requested season.** The JS computed every age at the *active* season's start, even when a past season was displayed. Same result for the active season; past seasons now show the age during that season.
- **S11 applied everywhere.** A tariff listed under two planning groups belongs to the first row by id, both in `/api/members` and in the Firestore `adherents` projection (`_read_planning_groups` now uses `member_view.tarif_slots`). A13 is resolved.
- **Front end.**
  - New classic script `web/shared/alj-members-sync.js` (`ALJMembersSync.start`) polls both routes and switches season on demand. A remembered season that no longer exists falls back to the active one. It is used by `bureau/adherents.html` and `index.html`.
  - `bureau/outils.html` reads `/api/seasons`. Its default season is now the active one, instead of a hard-coded `2026-2027`.
  - `alj-members.js` keeps the display helpers only. Dropped: `buildMembersData`, `startMembersListener`, `calcAge`, `normalizeGender`.
  - The browser now downloads one season instead of every season of the five `crm_*` collections.
  - The directory is online only (D2), and the PWA got its own `apiFetch` (ID token).
  - After a member update, the bureau page refetches; the 🔄 buttons refetch too.
- **Parity check on the emulator data** (dev, script in the session scratchpad, not committed): it rebuilt the list the way `alj-members.js` did, from the `crm_*` collections.
  - Same people and purchases in both seasons (43 and 62).
  - Identical slot group, category, age, normalized status and payer for all 62 members of the active season.
- **Not verified:**
  - In a browser.
  - The cold start on Cloud Run (the first `/api/members` after scale-to-zero waits for the cache rebuild; S3, D3).
- **Still loaded (removed in phase 3):** the Firestore SDK and `enablePersistence` on `index.html`.

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
6. Web version bump to the next version (**v23**; main is at v22 since ffdf6f3) (`<meta alj-web-version>`, titles, badge, `CACHE_NAME`).
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

#### C2 — Competition coaches: an association instead of three fixed columns

**Problem.** A competition stores its coaches as three fixed slots, `coach1_id`, `coach2_id` and `coach3_id`. This is a repeating group: a list modelled as numbered columns.
- **Arbitrary limit of 3.** The API rejects a 4th coach only because there is no 4th column (`MAX_COACHES` in `src/api/schemas.py`; see S10). The PWA used to allow more.
- **Three copies of the same information in each Firestore document** (`_build_comp_doc`, `competition_firestore_repository.py:~170`):
  - `coach1_id..coach3_id`;
  - `coach_ids` (array);
  - `coaches` (names copied from the `coaches` collection).

  Every writer has to keep the three in step. Readers fall back from one to the other (`_comp_from_doc`, around line 146). A partly failed coach rename or delete leaves them out of step (A7, A10).
- **Slot logic everywhere:**
  - Every query on a coach has to check three columns (`WHERE coach1_id = ? OR coach2_id = ? OR coach3_id = ?`, `competition_repository.py:952`).
  - Deleting a coach means checking every slot of every competition.
  - Code packs and unpacks lists into slots: `_apply_coaches` in `src/api/competitions.py`, `firestore_sync.py:117`.
  - Order is meaningful by accident: removing coach 1 leaves a gap or shifts the others.
- **Spread across every layer:**
  - the domain model (`competition_models.py:85-87`, `to_dict`/`from_row`);
  - the SQLite schema (`competition_repository.py:170-175`, 390-401);
  - the Firestore repository and `firestore_sync.py`;
  - the desktop form (three `QComboBox`, `presentation/pages/competitions.py:883-905`);
  - both web pages.

**Note on cardinality.** The link is **many-to-many**, not 1-n. A competition has several coaches, and a coach is on several competitions. "1-n" holds only on each side of the link table: one competition → n links, one coach → n links.

**Change.**
1. **Domain.** `Competition.coach_ids: list[int]`, an ordered list with no length limit, replacing `coach1_id..coach3_id`.
2. **SQLite (desktop).** Add a join table with foreign keys:
   ```sql
   CREATE TABLE competition_coaches (
       competition_id INTEGER NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
       coach_id       INTEGER NOT NULL REFERENCES coaches(id)      ON DELETE CASCADE,
       position       INTEGER NOT NULL DEFAULT 0,   -- display order only
       PRIMARY KEY (competition_id, coach_id)
   );
   CREATE INDEX idx_competition_coaches_coach ON competition_coaches(coach_id);
   ```
   - Migration: copy the non-null `coach1..3_id` into the table, then drop the three columns.
   - Deleting a coach becomes a single `ON DELETE CASCADE`.
   - "Competitions of coach X" becomes one indexed join.
3. **Firestore.** It has no joins or foreign keys, so a separate link collection would mean extra reads on every competition list and multi-document writes with no cascade.
   - The idiomatic Firestore equivalent of a many-to-many link is **one array of ids on the owning document**: keep `coach_ids` as the **only** source of truth.
   - "Competitions of coach X" is the `array-contains` query.
   - Remove `coach1_id..coach3_id` and the copied `coaches` names. The API adds the names when it reads (it already loads the `coaches` collection), so renaming a coach no longer rewrites every competition (`_refresh_coach_names`, A10).
   - Data migration: strip the obsolete fields from existing documents. Readers keep accepting them during the transition.
4. **API.** `coach_ids` without `max_length`; delete `MAX_COACHES` and `_apply_coaches`. Responses keep `coach_ids` and gain resolved `coaches: [{id, nom}]`.
5. **Clients:**
   - Desktop: a multi-select list replaces the three combo boxes.
   - Both web pages: read `coaches` from the API response.
   - `presence_sheet_generator.py` already works on a list (`encadrants`).

**Side effects to handle.**
- **Old desktop builds** keep writing `coach1..3_id`, and they write Firestore directly.
  - Ship the desktop change first, with readers that accept both shapes.
  - Remove the old fields only once every club PC runs the new version.
- **Order.** Today "Coach 1" may implicitly mean the lead coach. Check with the club. If it matters, keep `position` / array order and show it. If not, drop `position`.

**Out of scope until decided.** A lead-coach role, or other per-link attributes (e.g. driver, judge). These would justify Firestore link documents instead of an id array.

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
  - Lockdown is a separate, later deploy: rules go out ≥1 week after that version.
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
  - At most 3 coaches per competition (the repo stores `coach1..3_id`; the PWA allowed more). The API returns 400 above 3; check existing data first. The limit itself goes away with cleanup C2.
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
| A13 | `alj-members.js` vs repo `_read_planning_groups` (342) | Tariff → group tie-break: JS takes the first row, Python the last. | **Resolved in phase 2**: first row by id everywhere (`domain.member_view.tarif_slots`). |
| A14 | `src/server.py:1803` | `/api/auth/google/test` calls `ensure_fresh(max_age_seconds=10)`, but the parameter is `max_age`: TypeError (caught), so `database.ok` is always false. The test mocks it away. | **Fixed on main** (89c9394: `ensure_fresh` accepts `max_age_seconds`, the call uses `max_age`). |
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
| A27 | `server.py` `POST /api/competitions/{id}/fetch-results` (main, 3ea9078 series) | Reads the competition, adds the MyCompet results to its participants, then rewrites the whole `participants` array with no precondition. A participant change made in between (coach, webhook payment) is lost. It also bypasses the service layer. | **Still present.** Fix: move it to `ParticipantService` and write per participant through `_update_participant` (optimistic lock). |
| A28 | `api_auth.LOCAL_HOSTS` (main) | `"testserver"` (the FastAPI TestClient's host) was added to the hosts accepted by the local server without authentication. Production code is relaxed to suit tests: a local server then also accepts requests sent with `Host: testserver`. Tests should set `base_url="http://127.0.0.1"` instead. | **Still present.** Low risk (local server only), review with the author. |

## Appendix B — Fields to migrate later (D4)

Today only `web/bureau/competitions.html` writes these. They are not in `src/domain/competition_models.py`, the PWA or the desktop app. The API stores them as unvalidated pass-through values and preserves them on every write.

| Field | Level | Written at | Notes |
|---|---|---|---|
| `lieu` | competition | `bureau/competitions.html:906-917` | Free text (place). |
| `type` | competition | same | Free text; no list of values defined. |
| `present` | participant | `bureau/competitions.html:637-640`, 717-743 | Attendance flag (bool). |
| `categorie`, `tarif`, `groupe`, `created_at` | participant | bureau "+ Inscrire" 717-743 | Copied from the member at enrolment; the PWA doesn't write them. Decide whether to keep or derive. |

Migration later means: add them to the `Competition`/`Participant` dataclasses, validate them in the API, show them in the PWA and the desktop app, and backfill or clean existing documents.
