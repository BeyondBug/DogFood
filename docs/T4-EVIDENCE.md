# T4 stretch features: independent evidence

The supplied acceptance checker stops at T2. BeyondBug therefore keeps its
official `.dogfood.toml` claim at T1/T2 and documents T4 separately.

| T4 requirement | Implementation | Evidence |
| --- | --- | --- |
| REST API | Browser mutations and public/private reads use documented JSON APIs | Generated `openapi.json`; synchronization test |
| Webhooks | Canonical JSON with a per-endpoint HMAC-SHA256 signature and retained delivery status | Stretch integration test exercises configuration and failure history |
| Certificates and records | Separate participant and winner certificates with public lookup | Lifecycle tests |
| Signed judge participation records | Canonical JSON signed by an offline-generated Ed25519 installation key; payload, signature, and public key are public | Integration test verifies with OpenSSL |
| Embeddable gallery widget | Responsive, dependency-free `/embed/{event_id}` page showing submitted projects only | Stretch integration test |
| Bulk import and export | Admin CSV import for participant and judge accounts; ten organizer CSV exports; secret-free JSON event archive | Stretch and lifecycle tests |

Webhooks are optional. An installation with no configured endpoints makes no
external requests, preserving the offline one-command runtime.
