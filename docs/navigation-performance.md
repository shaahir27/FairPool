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
its cadence and its limits are recorded here instead of being left implicit.

Render's free-tier rule ([docs page](https://render.com/docs/free)): a free web service
spins down after **15 minutes** without inbound traffic, waking takes **about a minute**,
and only inbound requests count as activity. The interval therefore has to be shorter
than 15 minutes; it is **10 minutes**, which leaves a 5-minute margin for a late or
failed run. A 20-minute cadence would sleep the service between pings.

Two runners, both requesting `/health` and then `/ready`:

- `.github/workflows/keep-warm.yml` — cron `*/10 * * * *`, plus a manual
  `workflow_dispatch` button used to wake the app just before a demo or a screen share.
- `tools/keep_warm.ps1` — the same two requests, run by a Windows scheduled task on the
  owner's machine while the repository is private.

`/ready` is included because it runs the database and migration checks, so the free
Supabase project also sees queries and does not reach the pause-after-about-7-days rule.

The workflow stays **disabled while the repository is private**. A scheduled job on a
private repository bills at least one minute per run, so a 10-minute cadence is about
4,320 minutes a month against the 2,000 free GitHub Actions minutes and would exhaust
the quota and block CI. The repository flips public at T10A02/T11X01 (before 12 November
2026); scheduled runs are free on a public repository, so it is enabled then:

```powershell
gh workflow enable keep-warm.yml      # after the repository becomes public
```

Register the local task once (it needs no elevation and no secrets):

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File D:\Desktop\project\FairPool\tools\keep_warm.ps1'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
Register-ScheduledTask -TaskName 'FairPool Keep Warm' -Action $action -Trigger $trigger -Settings $settings -Description 'Requests /health and /ready every 10 minutes so the free Render service does not spin down.'
```

Check and remove:

```powershell
Get-ScheduledTaskInfo -TaskName 'FairPool Keep Warm' | Select-Object LastRunTime, LastTaskResult, NextRunTime
Get-Content "$env:TEMP\fairpool-keep-warm.log" -Tail 4
Unregister-ScheduledTask -TaskName 'FairPool Keep Warm' -Confirm:$false
```

Success line: `LastTaskResult` is `0`, the next run time is about ten minutes ahead, and
the log shows `/health HTTP 200` and `/ready HTTP 200`.

Limits stated honestly: the local task runs only while the owner's machine is awake, so
a closed laptop or a paused machine brings the cold start back. A ping cannot make a
warm read faster than the 0.5-1 second measurements above, and it does not change the
Render plan, the region or the BD-05 decision that paid instances must return before
20 November 2026.

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
