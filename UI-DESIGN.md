# BeyondBug UI plan — pre-kickoff draft

This is a design plan, not a built interface. The portal must be attractive,
fast to understand, and usable for an organizer running a real event. A
polished landing page alone will not satisfy the judging or lifecycle brief.

## Visual direction

The installed [frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design)
guides the design pass. Its first question is what is distinctive about this
product. BeyondBug's identity should come from the visible event lifecycle and
the trust placed in judging, not from generic hacker imagery or a set of
identical marketing cards.

**Concept:** an *event desk*. The public event page is spacious and inviting;
participant, judge, and organizer workspaces become progressively more
information dense. A single milestone rail shows where the event is in the
registration → submission → judging → results sequence. It becomes the
recognizable visual element, while forms and tables remain quiet and precise.

**Draft token palette:** canvas `#F4F7F5`, ink `#102B38`, rule `#C7D5D4`,
signal teal `#167D78`, action blue `#304DB8`, deadline coral `#D56B4F`.
Use color to signal phase and action; include text and icons for meaning too.
These tokens are a design proposal to verify in browser screenshots for
contrast, not project CSS written before kickoff.

**Type:** self-host IBM Plex Sans after kickoff, with a system sans fallback.
Use one family with a deliberate scale and tabular figures for dates, counts,
and scores. The font's [SIL Open Font License](https://github.com/IBM/plex/blob/master/LICENSE.txt)
permits bundling; keep its license with the assets. Avoid all-caps labels and
decorative monospace metadata. Use concise, specific interface words such as
“Save draft”, “Submit project”, and “Publish results”.

**Implementation direction after kickoff:** local CSS and assets only,
reusable spacing/type/color tokens, responsive layout, accessible focus states
and contrast. No CDN or hosted font is needed at runtime. Use small motion for
state changes, never as the only way to convey meaning.

### Event page layout sketch

```text
Product nav: Events  Gallery                            Account
──────────────────────────────────────────────────────────────
Event name and one-sentence purpose       Next milestone + date
Status and timing                         Main action
──────────────────────────────────────────────────────────────
Registration ━━ Submission ━━ Judging ━━ Results  (event rail)
──────────────────────────────────────────────────────────────
Tracks and prizes                  How the event works
──────────────────────────────────────────────────────────────
Featured projects                 Browse all projects
```

Keep the main content left aligned. On narrow screens, place the next
milestone below the event name and let the timeline scroll or wrap with labels
fully visible. Do not make a countdown the only indicator of event state.

### Design critique before implementation

The earlier “navy, white, blue, accent cards” proposal could describe almost
any SaaS dashboard. The revised concept uses the event's actual phases as its
organizing structure. The milestone rail is the one memorable visual move;
the gallery, forms, and judging tables should be deliberately restrained.
During implementation, review desktop and mobile screenshots and remove
decoration that does not help people understand the event or complete a task.

## One coherent product, five key surfaces

| Surface | What the user must immediately understand | Primary action |
| --- | --- | --- |
| Event landing page | Name, status, dates, tracks, prizes, how to join and submit | Register or open dashboard |
| Public gallery | What was built, by whom, in which track | Search/filter and open project |
| Participant workspace | Team, invite, draft completeness, deadline, submission state | Invite teammate, save draft, submit |
| Judge console | Assigned queue, track, progress, rubric, feedback | Score next assigned project |
| Organizer console | Event setup, submissions, assignment coverage, review progress, ranking state | Resolve gaps, export, publish |

The event page should feel like a real hackathon homepage: a strong event hero,
status/deadline block, clear registration call to action, track cards, prize
summary, schedule, project preview, and an explanation of judging. It must be
generated from event data, not hardcoded to Dogfood, because the winning portal
is meant to run future events too.

## Page and interaction inventory

### Event landing page

- Header with product identity, event switcher, gallery, and login/account.
- Hero with event name, short description, status badge, dates, and one clear
  primary action. A countdown may help, but the server remains the source of
  truth for deadline enforcement.
- Tracks and prizes as scan-friendly cards. Timeline distinguishes upcoming,
  active, and finished phases.
- Public projects preview and a link to the complete gallery.
- Plain explanation of submission and judging so visitors know what happens.

### Participant workspace

- Team identity and member count, with invite action and the four-member limit.
- Submission stepper: project details, links/media, track, review and submit.
- Visible `Draft`, `Submitted`, and `Closed` states; save/submit confirmation.
- Deadline displayed with timezone, plus clear server rejection after close.
- Errors next to fields and a persistent summary rather than a generic toast.

### Judge console

- Queue grouped by `To review`, `Draft`, and `Submitted`; progress fraction.
- Project context and rubric visible together so judges need fewer clicks.
- Weighted criteria with score range and help text, comment field, save draft,
  and final submit. Show what is still missing before final submission.
- No peer scores, aggregate ranking, or other-track projects in UI **or API**.

### Organizer console

- Setup overview for dates, tracks, prizes, judge invitations, and rubric.
- Coverage table: each project, assigned judge count, submitted reviews,
  conflicts, and under-reviewed warnings.
- Judge progress table and filters that answer "who has not started?".
- Results workspace with raw/adjusted rank comparison, duplicate flags,
  review count, explanation of normalization, and deliberate publish action.
- CSV export actions close to the data they export; audit trail readable here.

### Public gallery and results

- Search across title/summary and filter by track; project cards show title,
  team, track, short summary, and relevant links.
- Responsive list/grid that remains usable with 40+ fixture projects.
- Public results are absent until the organizer publishes them. If T3 voting
  ships, ballot ordering is randomized, with status and vote rules clearly
  explained. Do not expose a hidden ranking in page source or JSON.

## Accessibility and quality bar

- Keyboard navigation and visible focus on every action; semantic headings,
  labels, status text, and error messages.
- Color is never the sole indicator of score, progress, or deadline state.
- Mobile widths support registration and judging, not just the landing page.
- Avoid decorative charts that obscure the underlying numbers. Tables need
  readable labels, sorting where useful, and export where specified.
- Every screen has a clear loading, empty, error, and success state.

## Build order

At kickoff, establish reusable layout, typography, buttons, forms, status
badges, and tables along with the first T1 path. Then complete event landing,
gallery, participant flows, judge console, and organizer console alongside
their backend behavior. Spend the final polish pass on visual consistency,
mobile layout, content clarity, and the five-minute demo path. Never use a
hardcoded UI to stand in for missing data or permissions.
