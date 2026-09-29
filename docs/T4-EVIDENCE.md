# T4 stretch features: independent evidence

The supplied acceptance checker stops at T2. BeyondBug therefore keeps its
official `.dogfood.toml` claim at T1/T2 and documents T4 separately.

| T4 requirement | Implementation | Evidence |
| --- | --- | --- |
| REST API | Browser mutations and public/private reads use documented JSON APIs | Generated `openapi.json`; synchronization test |
| Webhooks | Every audited event-scoped write queues canonical JSON (type = audit action) in the same transaction; a background task delivers it with a per-endpoint HMAC-SHA256 signature and retains status | `tests/test_webhook_outbox.py` proves a committed update is queued once and a rejected one is not; stretch test exercises failure history |
| Certificates and records | Separate participant and winner certificates with public lookup | Lifecycle tests |
| Signed judge participation records | Canonical JSON signed by an offline-generated Ed25519 installation key; payload, signature, and public key are public | Integration test verifies with OpenSSL |
| Embeddable gallery widget | Responsive, dependency-free `/embed/{event_id}` page showing submitted projects only | Stretch integration test |
| Bulk import and export | Admin CSV import; ten CSV exports; editable setup bundle; complete event archive preserving judging, voting, certificates, pairwise records, audit, and integration history | Round-trip test restores 41 projects, 126 scorecards, a ballot, certificate, and every exported audit row |

Webhooks are optional. An installation with no configured endpoints makes no
external requests, preserving the offline one-command runtime.
