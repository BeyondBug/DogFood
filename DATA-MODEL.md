# Data model

SQLite is the source of truth. `src/db.py` contains the exact versioned SQL
schema; `PRAGMA user_version` advances from 0 through 7 at startup. Every
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
| `projects` | Event, team, track, title, summary, description, repository/demo/live/video/thumbnail URLs, gallery URLs, technology tags, draft/submitted status, timestamps, `duplicate_of` | Team edits stop at the server deadline |
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
| `event_awards` | Configured prize, event, submitted winning project, assigning organizer and time | One selected project per prize; selection locks after winner certificates issue |
| `certificate_designs` | Event and participant/winner kind, layout, palette, issuer line, updater and time | Only a site administrator may change a design; one setting per event and kind |
| `certificates` | Opaque ID, event, recipient, project, participant/winner kind, optional prize, issuance time, design JSON snapshot | Unique participant record per event/recipient and unique winner record per event/recipient/prize; later design edits do not change issued artwork |
| `app_keys`, `login_attempts` | Local HMAC secret; account and IP digests, outcome, timestamp | Failed logins and lockouts persist across process restarts without storing raw IPs |

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

For newly created events, duplicate flags compare only **submitted** projects
with a nonempty, identical repository URL. The earliest submitted record is
the canonical one. Drafts never make another project a duplicate; editing a
repository URL before the deadline recalculates the event's flags.

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
| `/api/events/{id}/exports/participants.csv` | Registered accounts and team membership | Organizer |
| `/api/events/{id}/exports/judges.csv` | Judges, status, and eligible tracks | Organizer |
| `/api/events/{id}/exports/assignments.csv` | Judge/project assignment and status | Organizer |
| `/api/events/{id}/exports/scores.csv` | Criterion-level scorecard rows | Organizer |
| `/api/events/{id}/exports/rankings.csv` | Raw and adjusted scores, coverage, duplicates | Organizer |
| `/api/events/{id}/exports/audit.csv` | Consequential event changes | Organizer |
| `/api/events/{id}/exports/votes.csv` | Final ballot records | Organizer |
| `/api/events/{id}/exports/certificates.csv` | Issued participation and winner records | Organizer |
| `python -m src.backup DESTINATION` | Consistent SQLite database copy | Local operator |
| `/api/events/{id}/certificates` | Issued certificate metadata | Organizer |
| `/api/admin/events/{id}/certificate-designs/{kind}` | Participant or winner design settings | Site administrator |
| `/api/admin/events/{id}/judges` | Create a local judge account, accepted profile, and review tracks; returns a temporary password once | Site administrator |
| `/api/admin/events/{id}/organizers` | Assign an existing account or create a local organizer account with a temporary password | Site administrator |
| `/api/auth/password` | Change password and revoke all existing sessions | Signed-in account |
| `/events/{id}/certificates/preview/{kind}.svg` | Watermarked, non-verifiable SVG sample | Site administrator |
| `/api/certificates/{id}/verify` | Public database-backed verification JSON | Public |
| `/certificates/{id}.svg` | Vector certificate for print or download | Public |

CSV columns have stable headers, use Python's CSV quoting, and prefix text
that would otherwise open as a spreadsheet formula. No bulk import or full
archive format is claimed. A future importer should map external IDs and
reconcile duplicates before modifying live events.

## Migration and retention

Version 1 created the core tables. Version 2 added judge invitations and
conflicts. Version 3 added voting windows, invite eligibility, ballots,
attempt signals, and comments. Version 4 added prize assignments and
certificates. Version 5 added persistent login throttling. Version 6 added
per-event certificate designs and issuance-time design snapshots. Version 7
added project media links and technology tags. Migrations run before fixture
seeding.
`rubrics.version` and each
scorecard's `rubric_id` preserve scoring context, but changing a rubric is
currently blocked once assignments exist. Published results lock scorecard
changes; a correction workflow and historical result snapshots are future
work. Back up the SQLite file before upgrading or moving hosts.
