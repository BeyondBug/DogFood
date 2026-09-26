# Data model — design draft

This is a pre-kickoff schema plan. Table names and constraints will be revised
against the implemented migrations.

## Entities and relationships

| Entity | Purpose | Key constraints |
| --- | --- | --- |
| `users` | Local identities | Unique normalized email; password hash, never plaintext |
| `sessions` | Revocable login sessions | Opaque token hash, user, expiry |
| `events` | Timelines and publication state | UTC timestamps; explicit phase settings |
| `event_roles` | Participant, judge, organizer, admin grants | Unique user/event/role |
| `tracks`, `prizes` | Organizer configuration | Belong to one event |
| `teams`, `team_members`, `team_invites` | Team membership and joining | Membership unique per event; invite expiry and use limit; max four members |
| `projects`, `project_revisions` | Draft and submitted work | Event, team, track, status, server timestamps; revision history |
| `rubrics`, `rubric_criteria` | Versioned scoring definitions | Positive weights; bounded criterion scores |
| `judge_tracks`, `judge_assignments` | Eligibility and work allocation | Unique judge/project assignment; conflict exclusion |
| `scorecards`, `criterion_scores` | Reviews and feedback | Unique judge/project/rubric version; one value per criterion |
| `audit_entries` | Organizer-readable action history | Actor, action, entity, time, change summary |

All records that can cross event boundaries carry an event ID or an enforced
foreign-key path to one. Database constraints should back the invariants that
are easy to express, while service transactions enforce phase-dependent rules.
IDs, rather than names, identify teams and projects because fixture names
repeat.

## Published fixture import

The [official fixture](https://dogfoodhack.com/spec/fixtures.json) has one
closed event, 8 tracks, 30 judges, 40 teams, 41 project records, and 126
scorecards. We will map external IDs into import keys and preserve the source
JSON for traceability. `prj_41` repeats `prj_07`'s team and repository URL; the
import will retain both and flag the pair instead of silently dropping data.
All 30 judges connect through shared project reviews, but two judges have only
one scorecard. A proposed normalization method must account for that sparse
coverage.

Seed import must be idempotent: a restart adds nothing twice and does not
overwrite changes made after seeding. It will provision local demo identities
for an organizer, two judges, and a participant, then print usable credentials
or headers for `.dogfood.toml`. The exact mechanism belongs in the shipped
README and acceptance config.

## Import/export plan

Start with the official JSON fixture as an import format and CSV exports for
teams, projects, assignments, scorecards, and results. Use stable column names,
UTF-8, and safe CSV quoting. Export original and normalized scores separately
with rubric version and review counts so results are reproducible. Bulk import
and full archive export are T4 work and will be claimed only if implemented.

## Migration and retention plan

Version the schema from the first code commit. Preserve historical rubric
versions and scorecards when criteria change. Prefer soft closure and explicit
archive state to accidental deletion of judged events. Document backup and
restore commands once the implementation exists.
