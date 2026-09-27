# Data model

SQLite is the source of truth. `src/db.py` contains the exact versioned SQL
schema; `PRAGMA user_version` advances from 0 to 1 to 2 to 3 at startup. Every
connection enables foreign keys and a busy timeout. Event-scoped APIs check
the event ID as well as the acting user's role.

## Tables

| Table | Main columns and relationships | Invariant |
| --- | --- | --- |
| `users` | ID, case-insensitive unique email, name, password hash, global admin flag | Passwords are salted PBKDF2 hashes |
| `sessions` | SHA-256 token digest, user ID, expiry | Raw token appears only in cookie or bearer header |
| `events` | Name, description, registration/submission/judging/voting dates, voting mode, ballot seed, publication time, creator | All stored timestamps include UTC offset |
| `event_roles` | Event ID, user ID, participant/judge/organizer role | Composite primary key permits distinct roles per event |
| `tracks`, `prizes` | Event ID and name | Track names are unique within an event |
| `teams`, `team_members` | Event, captain/creator, member role | Membership and team-size checks are transactional |
| `team_invites` | Hashed token, team, creator, expiry, use count, revocation time | Default one use; at most four members enforced in service |
| `projects` | Event, team, track, title, summary, description, URLs, draft/submitted status, timestamps, `duplicate_of` | Team edits stop at the server deadline |
| `judge_profiles`, `judge_tracks` | Judge user, event, accepted status, eligible tracks | One judge profile per user and event |
| `judge_invites` | Hashed token, event, invited email, creator, expiry, acceptance time | Acceptance requires matching account email |
| `judge_conflicts` | Judge, project, reason, creation time | Assignment excludes declared conflicts |
| `rubrics`, `rubric_criteria` | Event, version, active flag; criterion slug, weight, maximum score, order | Weights are positive; shipped API uses a 0–5 criterion range |
| `judge_assignments` | Event, project, judge, timestamp, reason | Unique judge/project pair |
| `scorecards`, `criterion_scores` | Assignment, rubric version, draft/submitted state, comment, per-criterion value | A submitted card requires every criterion |
| `audit_entries` | Event, actor, action, entity, JSON details, UTC time | Organizer-readable history of consequential writes |
| `voter_invites` | Hashed token, event, invited email, creator, expiry, acceptance and voter account | One accepted invitation per event and email |
| `ballots` | Event, voter account, project, cast time | Unique event and voter pair; one final vote per account |
| `vote_attempts` | Event, voter account, keyed IP digest, outcome, time | Countable signals for throttling and organizer review |
| `comments` | Event, project, author, body, creation and moderation fields | Hidden comments stay in the database for audit |

Generated IDs are opaque strings with prefixes such as `evt_`, `tm_`, and
`prj_`. Published fixture IDs are preserved verbatim to make acceptance and
data reconciliation easy. Foreign keys connect assignments to project and
judge, and scorecards to assignments. The API adds phase, ownership, and
cross-row checks that SQLite alone cannot express cleanly.

## Fixture import

`src/seed.py` loads the published `fixtures.json` when its event is absent.
It preserves the fixture's original `submissions_close` date. Tracks, judge
track preferences, teams, project submissions, and 126 historical scorecards
become relational rows. One default rubric is made from the fixture criterion
names with equal weights. Each imported historical score creates a matching
assignment. Unfinished reviews remain absent rather than being filled with
zeroes.

The file has 41 project records for 40 teams. `prj_41` repeats `prj_07`'s
team and repository URL; both records remain visible, while `prj_41` is
flagged with `duplicate_of=prj_07` and excluded from ranking. Its four
historical scorecards remain in the database for traceability. The initial
ranking therefore uses 122 completed reviews over 40 unique projects.

Fixture import is a first-boot operation. It does not overwrite edits when
the container restarts. Demo mode adds four known local sessions and passwords
for acceptance and walkthroughs; disabling demo mode removes those known
credentials. An operator can bootstrap a global admin account from local
environment variables.

## Import, export, backup

| Path | Format | Access |
| --- | --- | --- |
| `fixtures.json` → `src/seed.py` | Published JSON | Startup only |
| `/api/events/{id}/exports/projects.csv` | Project and team rows | Organizer |
| `/api/events/{id}/exports/teams.csv` | One row per team member | Organizer |
| `/api/events/{id}/exports/assignments.csv` | Judge/project assignment and status | Organizer |
| `/api/events/{id}/exports/scores.csv` | Criterion-level scorecard rows | Organizer |
| `/api/events/{id}/exports/rankings.csv` | Raw and adjusted scores, coverage, duplicates | Organizer |
| `python -m src.backup DESTINATION` | Consistent SQLite database copy | Local operator |

CSV columns have stable headers, use Python's CSV quoting, and prefix text
that would otherwise open as a spreadsheet formula. No bulk import or full
archive format is claimed. A future importer should map external IDs and
reconcile duplicates before modifying live events.

## Migration and retention

Version 1 created the core tables. Version 2 added judge invitations and
conflicts. Version 3 added voting windows, invite eligibility, ballots,
attempt signals, and comments. Migrations run before fixture seeding.
`rubrics.version` and each
scorecard's `rubric_id` preserve scoring context, but changing a rubric is
currently blocked once assignments exist. Published results lock scorecard
changes; a correction workflow and historical result snapshots are future
work. Back up the SQLite file before upgrading or moving hosts.
