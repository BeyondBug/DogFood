# API contract

The complete generated OpenAPI specification is available at `/openapi.json`
and browsable at `/docs`. Browser forms use these same JSON actions. The
official acceptance routes are declared in `.dogfood.toml`.

| Area | Routes | Access |
| --- | --- | --- |
| Health and gallery | `GET /health`, `/`, `/events/{id}`, `/projects`, `/projects/{id}` | Public; draft projects hidden |
| Accounts | `POST /api/auth/register`, `/api/auth/login`, `/api/auth/logout`; `GET /api/auth/me` | Local account/session |
| Events | `GET /api/events`, `/api/events/{id}`; `POST /api/events`, `/api/events/{id}/registration` | Public reads; login for writes |
| Teams | `POST /api/events/{id}/teams`, `/api/teams/{id}/invites`, `/api/team-invites/{token}/join`; `GET /api/events/{id}/my-team` | Participant/member/captain checks |
| Projects | `POST /api/events/{id}/projects`, `PUT /api/projects/{id}` | Team member and submission window |
| Judge invitation | `POST /api/events/{id}/judges/invites`, `/api/judge-invites/{token}/accept`; `PUT /api/events/{id}/judges/{id}/tracks` | Organizer, then named judge |
| Rubric and assignment | `GET/PUT /api/events/{id}/rubric`; `POST /api/events/{id}/assignments/batch`; `PUT /api/events/{id}/judges/{id}/conflicts/{project}` | Public rubric read; organizer writes |
| Judge work | `GET /api/judge/assignments?event_id={id}`, `/api/judge/scores`; `PUT /api/judge/assignments/{id}/scorecard` | Own assignment and scorecards only |
| Organizer review | `GET /api/events/{id}/progress`, `/rankings`, `/audit`; `POST /api/events/{id}/results/publish` | Event organizer |
| Results | `GET /api/events/{id}/results`, `/results/{id}` | Public only after publication |
| CSV | `GET /api/events/{id}/exports/{projects,teams,assignments,scores,rankings}.csv` | Event organizer |
| Administration | `GET /api/admin/overview` | Bootstrapped global admin |

API errors use `401` for missing login, `403` for a known forbidden action,
`404` for missing or unpublished public resources, `409` for phase conflicts,
and `422` for invalid input. JSON actions use the session cookie or a bearer
token. Login cookies are HttpOnly and SameSite=Strict. A write with an
explicit foreign `Origin` is rejected. The demo checker uses bearer headers
printed at startup, so it does not need to log in.
