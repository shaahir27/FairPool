# Navigation data performance (T09B04)

Measured and implemented on 5 November 2026. Scope: the buyer, merchant and admin
read screens, retaining their existing palette and workflows. No database seeding,
migration, payment execution or hosting-plan change is included.

## Measured problem

A live request to `/health` took 32.4 seconds on the first probe. Render identifies
the active service as free in Oregon; the configured Supabase pooler is in
us-east-1. The first-probe delay is consistent with a free-service cold start,
not proof of a slow SQL query. It is recorded as an infrastructure limit and is not
masked with fake progress; the separate keep-alive pings below remove the sleeping
instance while they are actually running.

Repeated authenticated demo reads measured:

| Read | First sample | Second sample |
|---|---:|---:|
| Buyer entries | 2329 ms | 850 ms |
| Buyer orders | 1412 ms | 798 ms |
| Merchant demand | 903 ms | 782 ms |
| Merchant bids | 1509 ms | 985 ms |
| Admin alerts | 1316 ms | 887 ms |

The public catalogue measured 2332 ms, then 589/530 ms. These are client-observed
HTTP times, not SQL timings. Demo sessions were logged out after measurement; no
password, token, address or response body is recorded here.

The old implementation discarded page state on unmount. Discover always read the
catalogue again; only buyer entries/orders had a separate three-second promise
cache. Most portal pages fetched in component effects after the role gate and code
loaded. Seeding is a developer operation, not what these navigation reads do.

## Decision

Use TanStack Query v5 with the existing typed OpenAPI client. It supplies retained
snapshots, request deduplication, cancellation, bounded garbage collection, focus /
reconnect revalidation and write invalidation, instead of extending a second custom
promise cache. No API contract or database change is needed.

- General read freshness: 15 seconds; open catalogues: 60 seconds.
- Inactive snapshots are collected after five minutes. Memory only: no localStorage,
  sessionStorage, service worker, persisted tokens or cached credential URLs.
- A fresh return renders its data synchronously without another HTTP request.
  A stale return retains the previous snapshot while revalidating in the background.
  The workspace shows Updating information while retained data is being refreshed.
- Different resource IDs use different keys. Previous pool/lot data is not used as
  placeholder data for another resource. API failures throw and retain retry controls;
  automatic retries are disabled to avoid introducing exponential waiting.
  offlineFirst attempts the read once even when connectivity is reported offline;
  with retries disabled, a failure reaches the existing retry UI instead of leaving
  an initial loader silently paused. Reconnect revalidation remains enabled.
- Mouse, keyboard focus and touch intent warm the destination's data. Buyer pool
  links also warm its lazy code. Do not preload every page or payment SDK eagerly.
- Public catalogue/detail reads can start beside the session check. Private reads
  start only after a matching role is verified. The guard still controls rendering.
- Every typed API write cancels pre-write reads and invalidates snapshots, including
  an uncertain network outcome. Active reads refresh; inactive records become stale.
- Logout, login/reset and 401 clear all cached records. A late old-session response
  cannot repopulate the new session's cache. A mounted guard leaves on session end.
- Profile prefill remains separate from an edited form draft. Background refresh
  must not overwrite user input or retain a one-time created key/token.

Applied to Discover, public pool details, My Pools, Orders, addresses, agent access,
merchant demand/bids/profile/developer key metadata, fulfillment's awarded-lot
metadata, admin alerts and dead-letter records. Existing manual refresh controls
bypass freshness; SSE refreshes merchant facts rather than mutating business state.

Membership checks, checkout/PayPal order facts, shipment rows, admin lot intervention,
provider verification, CSV/audit downloads and credential/approval URLs keep their
fresh reads. Shipping access and payment actions are not granted by cached metadata.
The server remains authoritative for every deadline, price, transition and permission.

## Evidence and practical limits

- discover.behavior.test.tsx: returning renders the loaded catalogue immediately
  and sends no additional request within the freshness window.
- read-cache.test.tsx: all three role caches, in-flight prefetch deduplication,
  background refresh without blanking, resource-key isolation, failed-read recovery,
  session clearing/late responses, and refresh after a typed API write.
- navigation-loading.test.tsx and role-access.test.tsx: public parallel preloading,
  private role boundary and no early protected render.
- merchant.console.test.tsx and ops-console.test.tsx: the actual merchant demand
  and admin overview return immediately with one GET, alongside the buyer test.
- addresses.behavior.test.tsx: a deferred address save from a departed account
  cannot populate the successor account’s cache; query identity must still match.
- merchant.console.test.tsx: profile initialization reuses the verified account
  name without a second /me read; revalidation keeps drafts and the form enabled.
- session.guard.test.tsx: session-end event removes an already-mounted workspace.
- Existing lobby, checkout, fulfillment, profile, agent, ops and address tests retain
  the domain checks and write flows.

The query library adds about 12 KB gzip to the initial app bundle in the measured
build (60.63 to 72.68 KB gzip); receipt/PDF libraries remain lazy. This trades a small
one-time download for removal of repeated 0.5-1 second navigation reads. Dependency
scan reports no advisory on either added TanStack package; existing package advisory
totals are unchanged. Verify a production build, full frontend suite, make verify and
Graphify update before publishing. Browser visual performance is not claimed measured.

A browser hard reload intentionally discards private in-memory snapshots. It still
needs authentication and first data reads. A client cache cannot remove a sleeping
Render instance's first request or cross-region network latency; the sleep itself is
handled by the keep-alive pings below rather than by the cache. An always-on service
and colocated backend/database are infrastructure follow-ups requiring a separate
hosting decision; this change does not alter billing, move data or fake readiness.

## Keep-alive pings

Added 5 November 2026, after this document first told the owner not to hide the cold
start behind a keep-alive job. The owner decided to run one anyway, so the mechanism,
its cadence and its limits are recorded here instead of being left implicit. The scope
settled with the owner is deliberately narrow: the app only has to be warm from the
submission flip onward, because the judges see the link once the repository is public.

Render's free-tier rules ([docs page](https://render.com/docs/free)):

- a free web service spins down after **15 minutes** without inbound traffic and needs
  **about a minute** to wake; only inbound requests count as activity;
- hours are consumed **while the service runs** and the workspace pool is **750 hours a
  month**; at exhaustion Render suspends every free service until the next month;
- a free web service is **not** deleted for inactivity, so the URL itself keeps working
  indefinitely — the difference between awake and asleep is one slow first request.

The cadence therefore has to be under 15 minutes: **every 10 minutes**, which leaves a
5-minute margin for a late or failed run. The window is **20 hours a day, not 24**, and
that is the arithmetic, not a preference: 24/7 is 720-744 hours of a 750-hour pool, which
leaves as little as 6 hours of margin before a suspension that would black out the demo
for days. `*/10 3-22 * * *` UTC is about 600 hours a month and keeps 150 hours in reserve.
During the four unwarmed hours a visitor waits about a minute on the first request.

One runner requests `/health` and then `/ready`:

- `.github/workflows/keep-warm.yml` — the windowed cron above, plus a manual
  `workflow_dispatch` button that pre-warms the app before a screen share at any hour.

`/ready` is included because it runs the database and migration checks, so the free
Supabase project also sees queries. Supabase pauses a free project after **7 days**
without database activity, keeps a paused project restorable for a year, and resumes it
on activity ([pausing docs](https://supabase.com/docs/guides/platform/free-project-pausing)),
so the daily pings remove the only data-side way this demo could go quiet in January or
February.

The workflow was kept **disabled while the repository was private**. A scheduled job on
a private repository bills at least one minute per run: an unwindowed 10-minute cadence
is about 4,320 minutes per 30-day month against 2,000 free GitHub Actions minutes. Even
the 20-hour window is about 3,600 minutes, so either would exhaust the quota and block
CI. The repository was made public and the workflow enabled on **2026-11-12**, recorded
in [progress.md](progress.md). This is the command used, also available for re-enabling:

```powershell
gh workflow enable keep-warm.yml
```

After enabling, the success line is a scheduled run whose log shows `/health -> HTTP 200`
and `/ready -> HTTP 200`, and a `/health` request that returns in well under a second.

**Enablement verified 2026-11-12:** the repository is public and Keep warm is active.
Manual run [43274377129](https://github.com/shaahir27/FairPool/actions/runs/43274377129)
passed with `/health -> HTTP 200 after 0s` and `/ready -> HTTP 200 after 1s`.
The logged-out app probe returned HTTP 200 in 0.29s; the open-pools endpoint returned
HTTP 200 with 20 pools. A manual run is separate from automatic-schedule evidence;
the first successful `event: schedule` run is still being checked in this follow-up.

- **60-day activity check:** GitHub disables public-repository schedules after 60 days without repository activity; a push resets the inactivity clock. If the repository stays quiet after 2026-11-12, check in early January, before **2027-01-11**, and re-enable with the command above if disabled ([GitHub schedule rules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)).
- **Render hours meter:** read the workspace's shared meter during submission QA. The 20-hour window uses about 600 of 750 hours per 30-day month (620 in a 31-day month), with other traffic able to consume more; near 750, narrow the `3-22` UTC hour field in `*/10 3-22 * * *`, retain the 10-minute interval, and never switch to 24/7 on the free plan or add a second free service.

Limits stated honestly: GitHub's scheduler can delay or skip a scheduled run under load,
which only costs warmth, not availability. A ping cannot make a warm read faster than the
0.5-1 second measurements above, and it does not change the Render plan, the region or the
BD-05 decision that paid instances must return before 20 November 2026. If the owner later
wants zero cold starts around the clock through February, that is the paid web service at
about $7 a month, not a better cron.

## Primary references

- React on effect fetching, caching and waterfalls: https://react.dev/reference/react/useEffect
- TanStack Query defaults and freshness: https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults
- TanStack invalidation: https://tanstack.com/query/latest/docs/framework/react/guides/query-invalidation
- Existing OpenAPI client middleware: https://openapi-ts.dev/openapi-fetch/middleware-auth
- Render free-service limits: https://render.com/docs/free
- Supabase connection reuse: https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits

## Verification record

`make verify` exited 0: 1,207 backend tests, 269 frontend tests and 94.59% domain
coverage. Two further real-portal return tests and an offline failure test were added afterward and the final full
frontend suite passes 272 tests; lint/type checking and the production build also
pass for that state. Independent read-only review found no remaining blocker after the late-save
and profile-initialization fixes. No browser timing or pixel-level approval is claimed.

Network-mode reference: https://tanstack.com/query/latest/docs/framework/react/guides/network-mode

**Keep-warm follow-up, 2026-11-12:** `make verify` exited 0 on an isolated loopback
test database: 1,452 backend tests passed (one existing live-Elastic check skipped),
376 frontend tests passed, and domain coverage was 94.62%. Documentation validation
exited 0 with one existing endpoint warning. This follow-up changes only this document
and the two keep-warm request records in `progress.md`; it does not complete the
remaining submission QA or change the workflow, hosting configuration or application.
