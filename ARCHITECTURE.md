# Architecture — design draft

This is a pre-kickoff design sketch. It describes intended behavior, not an
implemented system. Update it to match the shipped code.

## Deployment

A single FastAPI application will serve HTML and JSON from localhost:8080. Use
the official Python 3.12 slim image and pin application dependencies to tested
versions. Python's standard-library `sqlite3` module will access a SQLite
database on a named Docker volume. Use one application worker, parameterized
SQL, short transactions, and versioned SQL migrations. This keeps the offline
runtime small and makes event-scoped permission queries explicit.
Startup will apply migrations and import `fixtures.json` idempotently. The application
will need no cloud account, external API, hosted database, or external identity
provider. Built images and dependencies must be locally available for an
offline start; we will test that explicitly. Templates, fonts, and scripts
will be bundled locally rather than loaded from a CDN.

## Request flow

1. The browser or API client sends an HTTP request.
2. Session middleware resolves an opaque cookie to a hashed, revocable session
   record. Local passwords use Argon2id hashes. Production cookie security and
   a bootstrap organizer account are configured locally.
3. The route asks a service to perform the action. The service enforces event
   role, object ownership, assignment, track, and event phase.
4. The service writes in a database transaction and appends an audit entry for
   consequential changes.
5. The route renders a server template or returns a JSON/CSV response.

Permission checks belong in the service/query path and apply equally to HTML
and API routes. The intended matrix is:

| Actor | Gallery | Own team/project | Assigned scorecards | Peer scores | Event administration |
| --- | --- | --- | --- | --- | --- |
| Visitor | Read | No | No | No | No |
| Participant | Read | Read/write before deadline | No | No | No |
| Judge | Read eligible projects | No write | Read/write own only | No | No |
| Organizer | Read | Administer | Read | Read | Yes, own event |
| Admin | Read | Administer | Read | Read | Yes, permitted events |

Judge reads also require assignment to the project and permission for its
track. A judge's session identity, not a query string, determines whose scores
are returned. A route for a named peer judge must return 403 to another judge.

## Lifecycle and invariants

Events have configured registration, submission, judging, voting, and result
publication times. The server evaluates deadlines in UTC in the same
transaction as the write. Drafts can be edited before the deadline; published
submissions cannot be changed after it except through a recorded organizer
action. Team invite tokens expire, are single purpose, and respect the 1–4
member limit. A scorecard refers to one rubric version and one assignment.
Results remain private until an organizer publishes them.

## Reliability and operations

- SQLite foreign keys enabled on **every** connection, WAL mode, a busy
  timeout, and short write transactions keep a laptop deployment
  straightforward. Migrations are versioned and repeatable.
- Fixture import keys by external ID and never overwrites later user edits.
  Duplicate submissions are preserved and flagged for review.
- CSV exports use stable headers and proper quoting. Exports, backups, and an
  archive path will be documented after implementation.
- Audit entries record actor, event, action, target, timestamp, and summary of
  changed fields. Application audit records aid review; they are not a claim of
  tamper-proof storage against a database administrator.
- Health checks, useful startup errors, and clear seed credentials will make
  the one-command deployment reviewable.

The Docker choice follows the [FastAPI container guidance](https://fastapi.tiangolo.com/deployment/docker/)
and [Docker Compose startup behavior](https://docs.docker.com/reference/cli/docker/compose/up/).

## Acceptance and independent verification

The official checker tests three T1 and four T2 HTTP behaviors. The team will
also test registration, team invites, draft/edit transitions, cross-track
denials, scorecard ownership, rubric validation, restart persistence, and a
fresh offline run. See [PLAN.md](PLAN.md) for the delivery gates.
