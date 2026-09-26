# API and screen contract — planning only

This is the team interface plan, not an implemented OpenAPI specification.
Routes and payloads may change together during kickoff. The final OpenAPI
document must be generated from and checked against shipped routes.

## Global conventions

- All event data is scoped by event ID. The service checks membership and role
  from the authenticated session on every request.
- JSON APIs use `/api/...`; public and logged-in pages use server-rendered
  HTML. The UI calls the same service actions as the APIs.
- Use `401` for missing/expired login, `403` for known forbidden actions, `404`
  where revealing existence would leak data, `409` for phase/conflict errors,
  and `422` for malformed input. The official closed-event probe accepts 4xx.
- Cookies are HttpOnly and SameSite; write requests need CSRF protection. A
  query parameter may select a resource but never establish the actor's role.
- Mutations record UTC server time and relevant audit entries in one
  transaction. IDs are opaque and stable. Pagination is bounded.

## Public and authentication

| Path/action | Actor | Result |
| --- | --- | --- |
| `GET /health` | Any | App/database readiness |
| `GET /projects` | Any | Searchable/filterable HTML gallery; fixture title on first page |
| `GET /projects/{project_id}` | Any | Published project details, no private judging data |
| `POST /api/auth/register` | Visitor | Local account |
| `POST /api/auth/login` | Visitor | Revocable session cookie |
| `POST /api/auth/logout` | Logged in | Invalidates session |
| `GET /api/me` | Logged in | Identity and event roles |

## Organizer/event actions

| Path/action | Actor | Result |
| --- | --- | --- |
| `POST /api/events` | Organizer/admin | New event with timeline |
| `PATCH /api/events/{event_id}` | Event organizer/admin | Dates, tracks, prizes, public settings |
| `POST /api/events/{event_id}/rubrics` | Event organizer/admin | New validated rubric version |
| `POST /api/events/{event_id}/judge-invites` | Event organizer/admin | Local invitation token/record |
| `POST /api/events/{event_id}/assignments/generate` | Event organizer/admin | Auditable assignment batch and shortage report |
| `GET /api/events/{event_id}/progress` | Event organizer/admin | Judge/project completion counts |
| `GET /api/events/{event_id}/exports/{kind}.csv` | Event organizer/admin | Stable CSV for projects, teams, assignments, scores, results |
| `POST /api/events/{event_id}/results/publish` | Event organizer/admin | Versioned public result snapshot |

## Participant actions

| Path/action | Actor | Result |
| --- | --- | --- |
| `POST /api/events/{event_id}/teams` | Participant | Team, subject to event rules |
| `POST /api/teams/{team_id}/invites` | Team captain | Expiring invite link |
| `POST /api/team-invites/{token}/accept` | Participant | Atomic join, max four members |
| `POST /api/events/{event_id}/projects` | Team member | Draft project; closed event returns 4xx |
| `PATCH /api/projects/{project_id}` | Team member | Own project edit before close |
| `POST /api/projects/{project_id}/submit` | Team member | Submitted state and server timestamp |

The project form covers title, short and long descriptions, track, repository
and demo URLs, technology tags, and optional media/custom answers. Validate
URLs and content length. Uploads, if implemented, stay on a local volume.

## Judge actions and checker mapping

| Path/action | Actor | Result |
| --- | --- | --- |
| `GET /api/judge/assignments` | Judge | Only assigned projects in allowed tracks |
| `GET /api/judge/scores` | Judge | Own scorecards; participant gets 403 |
| `GET /api/judge/scores?judge={id}` | Judge | 403 when `{id}` is another judge |
| `PUT /api/judge/assignments/{id}/scorecard` | Assigned judge | Draft criterion scores/feedback |
| `POST /api/judge/assignments/{id}/scorecard/submit` | Assigned judge | Validated, versioned completed review |

The acceptance config will point `gallery` to `/projects`, `judge_scores` to
`/api/judge/scores`, `peer_scores` to Judge A's selected URL, `submit` to the
fixture event's project creation route, and `csv_export` to the fixture event's
organizer CSV route. Judge A and Judge B are distinct seeded local accounts.
The fixture event is closed; a separate organizer-created event supports the
live submission demo.

## Screens needed for one lifecycle

Public event/gallery; register/login; participant team and invite; project
draft/edit/submit; organizer event setup, rubric, assignment and progress;
judge queue and scorecard; organizer results preview/publication. A direct
HTTP call must obey every rule even when the corresponding button is hidden.

