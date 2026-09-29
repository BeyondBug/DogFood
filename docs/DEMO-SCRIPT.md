# Five-minute demo recording guide

Record the running portal at a readable desktop resolution. Use separate
browser profiles for organizer, participant, and judge so switching roles does
not change another profile's session. The fixture event is historically
closed; create a second event with a future submission deadline for the live
lifecycle. Show real actions and responses from this build.

| Time | Browser or terminal action | Point to prove |
| --- | --- | --- |
| 0:00–0:30 | Run `docker compose up`; open `/` and `/projects` | One command, 41 seeded project records, no hosted login |
| 0:30–1:10 | Sign in as demo organizer, create a new event with one track and a prize | Event setup uses real dates, tracks, prizes; new event appears in dashboard |
| 1:10–2:00 | In participant profile, sign in as `priya1@example.org`, join the new event, create a team, create an invite link, save a draft, then submit | Team formation, draft/edit, submission state |
| 2:00–2:45 | Organizer closes submissions from Event details, configures weights and creates a judge invite for `tomas.varga@example.org`; judge accepts it in their profile | Server-controlled phase change, local invitation and role activation |
| 2:45–3:35 | Organizer sets the judge's track and runs batch assignment; judge opens queue and submits a scorecard | Track-aware assignment, weighted review, progress |
| 3:35–4:05 | Direct HTTP request as Judge B to Judge A's score URL returns 403; participant request also returns 403 | Backend isolation, not a hidden button |
| 4:05–4:35 | Organizer previews the new event's result and publishes; open the public results page | Results hidden until deliberate publication |
| 4:35–5:00 | Show fixture organizer ranking with raw/adjusted scores, CSV export, and `acceptance-report.txt` | Normalization proof, operations, seven passing checks |

Before recording, create the event and three profiles once as rehearsal on a
disposable Compose volume. For the final recording, use a fresh volume or a
new event so the actions are repeatable. The organizer of the new event must
assign the judge's track after the invitation is accepted. One completed
review is sufficient for the one-project demo; the default batch target is
three, so set the UI's “Reviews per project” field to 1. This does not affect
the fixture proof.

A five-minute silent, captioned browser recording is committed at
The published walkthrough is available on [YouTube](https://youtu.be/MwQeCSS8QFo),
with the submission copy at `media/beyondbug-demo.mp4`. It was captured from a fresh, disposable
Compose volume and shows the actions above, including the direct peer-score
denial. This guide lets another person repeat the lifecycle; its time ranges
are a suggested narration outline rather than exact cuts in the recording.
