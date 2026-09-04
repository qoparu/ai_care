# Android collector — SKELETON

**This does not work yet.** It is a structural starting point, not a functional
app. Nothing here has been run on a device.

What is real and finished is the target it has to hit:
[`docs/INGESTION_CONTRACT.md`](../../docs/INGESTION_CONTRACT.md). Hit that shape
and the entire backend, analytics and bot work immediately.

## Phase 0 — answer these before writing app code

Do not assume any of it. The brief is right that advertised metrics and
available metrics are different sets.

- [ ] Which data types does the Galaxy Watch 7 actually expose to your phone?
- [ ] How much history is readable — 7 days, 30, more?
- [ ] Is HRV exposed at all? Under which definition (RMSSD or SDNN)?
- [ ] Is Energy Score readable?
- [ ] What are the timestamp and timezone semantics per type?
- [ ] Are there rate limits or read-window constraints?

Write every answer into `docs/INGESTION_CONTRACT.md`.

## Two routes

### A. Health Connect — recommended first

No Samsung approval of any kind. Samsung Health writes into Health Connect on
Android 14+. You request runtime permissions and read.

- Smaller surface: sleep stages, heart rate, steps, exercise sessions, body
  composition. Samsung's proprietary metrics (Energy Score) probably absent.
- Fastest path to seven real days, which is what actually unblocks the project.

### B. Samsung Health Data SDK + developer mode

Full surface. Developer mode exists precisely so an unpublished, personally
signed app can read your own data on your own device; partner approval is a
Play Store distribution concern, not a personal-use one.

- Verify current requirements: <https://developer.samsung.com/health/data/guide/developer-mode.html>
- Developer mode is device-local and can need re-enabling after updates.

The backend does not care which route you take. Switching later costs nothing
downstream.

## Contract rules the collector must not break

1. Timestamps carry an explicit UTC offset. Naive timestamps are rejected (422).
2. `sourceUid` is stable across reads of the same underlying record — this is
   the entire basis of idempotency.
3. Missing is `null`, never `0`. A zero step count means zero steps.
4. Unknown JSON fields are rejected. Add a field to the backend schema first.
5. Re-sending an overlapping window is the expected pattern, not a problem.
6. `hrvRmssdMs` is RMSSD in milliseconds, or it does not go in that field.

## Suggested build order

1. Permissions + read one sleep session. Log it. Nothing else.
2. Map it to `SleepSessionDto`, serialize, print the JSON.
3. POST to `/api/v1/ingest` with the bearer token. Confirm `accepted: true`.
4. Add the remaining types one at a time, re-POSTing after each.
5. Only then add a background sync worker.

Do not build the UI first.
