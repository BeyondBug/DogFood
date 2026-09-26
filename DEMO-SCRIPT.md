# Five-minute demo plan — planning only

Use a clean local deployment with the published fixture and a second event
created through the portal. The fixture event is closed; it demonstrates
historical data and deadline enforcement. The second event demonstrates a
complete active lifecycle. Record actual behavior only.

| Time | Scene | Evidence to show |
| --- | --- | --- |
| 0:00–0:35 | `docker compose up` and landing page | One-command boot, seeded gallery, no cloud login |
| 0:35–1:15 | Organizer creates an event | Dates, track, prize, weighted rubric |
| 1:15–2:10 | Participant joins team and submits | Invite link, draft/edit, submit, server deadline check |
| 2:10–3:15 | Organizer assigns judges; judge scores | Track-aware assignment, progress, weighted criterion form |
| 3:15–3:55 | Permission proof | Peer judge score request denied by backend; participant denied |
| 3:55–4:35 | Organizer previews results | Raw vs normalized rank, review coverage, duplicate warning |
| 4:35–5:00 | Publish and export | Public results, CSV, acceptance report and tier claim |

Use local, fake fixture accounts and visible role labels. Keep the terminal
and browser readable at recording resolution. If a planned feature is cut,
remove its demo scene rather than simulating it.

