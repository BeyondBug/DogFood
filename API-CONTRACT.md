# API contract

The complete generated OpenAPI specification is available at `/openapi.json`
and browsable at `/docs`. Browser forms use these same JSON actions. The
official acceptance routes are declared in `.dogfood.toml`.

| Area | Routes | Access |
| --- | --- | --- |
| Health and gallery | `GET /health`, `/`, `/events/{id}`, `/projects`, `/projects/{id}` | Public; draft projects hidden |
| Accounts | `POST /api/auth/register`, `/api/auth/login`, `/api/auth/logout`, `/api/auth/password`; `GET /api/auth/me` | Local account/session; password change revokes existing sessions |
| Events | `GET /api/events`, `/api/events/{id}`; `POST /api/events`, `/api/events/{id}/registration`; `PATCH /api/events/{id}` | Public reads; administrator creates; participant registers; event organizer edits |
| Teams | `POST /api/events/{id}/teams`, `/api/teams/{id}/invites`, `/api/team-invites/{token}/join`; `GET /api/events/{id}/my-team` | Participant/member/captain checks |
| Projects | `POST /api/events/{id}/projects`, `PUT /api/projects/{id}` | Team member and submission window |
| Judge invitation | `POST /api/events/{id}/judges/invites`, `/api/judge-invites/{token}/accept`; `PUT /api/events/{id}/judges/{id}/tracks` | Organizer, then named judge |
| Rubric and assignment | `GET/PUT /api/events/{id}/rubric`; `POST /api/events/{id}/assignments/batch`; `PUT /api/events/{id}/judges/{id}/conflicts/{project}` | Public rubric read; organizer setup; judge can report only their own assigned conflict |
| Judge work | `GET /api/judge/assignments?event_id={id}`, `/api/judge/scores`; `PUT /api/judge/assignments/{id}/scorecard` | Own assignment and scorecards only |
| Organizer review | `GET /api/events/{id}/progress`, `/rankings`, `/judging-insight`, `/ml-review-signals`, `/scorecards/{scorecard}`, `/audit`; `POST /api/events/{id}/results/publish` | Event organizer; ML and peer evidence never exposed to judges |
| Results | `GET /api/events/{id}/results`, `/results/{id}` | Public only after publication |
| Participant feedback | `GET /api/events/{id}/my-feedback` | Participant's own team, after publication; reviewer identities omitted |
| Voting setup | `GET/PUT /api/events/{id}/voting`; `POST /api/events/{id}/voter-invites`, `/api/voter-invites/{token}/accept` | Public schedule; organizer setup; named voter accepts |
| Ballots | `GET /api/events/{id}/ballot`; `POST /api/events/{id}/votes`; `GET /api/events/{id}/votes/summary`, `/api/events/{id}/votes/results` | Eligible voter; organizer-only interim summary; public tally after publication |
| Comments | `GET/POST /api/projects/{id}/comments`; `DELETE /api/comments/{id}` | Public read, logged-in write during voting, organizer hide |
| CSV | `GET /api/events/{id}/exports/{projects,participants,teams,judges,assignments,scores,rankings,audit,votes,certificates}.csv` | Event organizer |
| Awards and certificates | `PUT /api/events/{id}/prizes/{prize}/winner`; `POST/GET /api/events/{id}/certificates`; `GET /api/me/certificates`, `/api/certificates/{id}/verify` | Organizer awards/issues; recipient reads own list; verification is public |
| Administration | `GET /api/admin/overview`; `POST /api/admin/events/{id}/organizers`, `/judges`, `/api/admin/backups`; `GET /api/admin/backups/{file}`; `PUT /api/admin/events/{id}/certificate-designs/{kind}` | Bootstrapped global admin |
| Pairwise mode | `POST /api/events/{id}/pairwise/assignments/batch`; `GET /api/events/{id}/pairwise/my-assignments`, `/pairwise/rankings`; `PUT /api/pairwise/assignments/{id}` | Organizer assigns and reads ranking; judge reads and submits own pairs |
| T4 integrations | `GET /embed/{id}`, `/api/events/{id}/export.json`; `POST/GET /api/events/{id}/webhooks`; `POST /api/events/{id}/judge-records/issue`; `GET /api/judge-records/{id}`; `POST /api/admin/events/{id}/bulk/{participants,judges}` | Public embed and record verification; privileged setup and archive APIs |

API errors use `401` for missing login, `403` for a known forbidden action,
`404` for missing or unpublished public resources, `409` for phase conflicts,
and `422` for invalid input. JSON actions use the session cookie or a bearer
token. Login cookies are HttpOnly and SameSite=Strict. A write with an
explicit foreign `Origin` is rejected. The demo checker uses bearer headers
printed at startup, so it does not need to log in.
