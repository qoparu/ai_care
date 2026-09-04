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

Full surface, but read the access-code caveat before committing to it.

Enable developer mode: Samsung Health -> ⋮ -> Settings -> About Samsung Health
-> tap the version line 10+ times. A "Developer mode (Samsung Health Data SDK)"
entry appears.

Inside it there are two different things, and they are easy to confuse:

- **A read toggle** ("Developer mode for Data read"). This is the one this
  project needs. Reading your own data does **not** require an access code.
- **An "app package name + access code" form.** This is for *writing* data.
  The access code is **issued by Samsung** after a partnership request — it is
  not self-generated, and it is case-sensitive. Do not try to invent one.

If the package-name form is filled in, the package name must be exactly the
`applicationId` from `app/build.gradle.kts`: **`com.aicare.collector`**.

Reports on the Samsung developer forum indicate the partner application process
has been suspended at times. If reading turns out to require an access code on
your build, this route is closed and Route A is the answer — it depends on no
approval from anyone.

Verify against the current docs: <https://developer.samsung.com/health/data/guide/developer-mode.html>

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

## Current state (Route B, Samsung Health Data SDK)

Developer mode "Data read" is enabled — no access code needed for this route.

Written and structurally complete, **not yet compiled or run on a device**
(no Android SDK / AAR available in the environment that wrote this):

- `Contract.kt` — full wire format, mirrors `backend/app/schemas.py` exactly.
- `Uploader.kt` — POST to `/api/v1/ingest`, handles 200/422/network failure.
- `SamsungHealthReader.kt` — store creation, permission request, and the
  `readData()` call shape, built from Samsung's own guide and API-reference
  pages (confirmed: `HealthDataService.getStore`, `Permission.of(DataType,
  AccessType.READ)`, `DataTypes.X.readDataRequestBuilder`,
  `LocalTimeFilter.of(start, end)`, `store.readData(request)`).
- `MainActivity.kt` — Compose UI: grant permissions, sync last 7 days, show
  the JSON on screen, upload it.

**What is explicitly a TODO in `SamsungHealthReader.kt`, and why:** the exact
field layout of a returned `HealthDataPoint` (how to read a sleep stage
duration, how to get a stable per-record UID for `sourceUid`) could not be
verified — developer.samsung.com is unreachable from the environment that
wrote this code. Three methods throw `NotImplementedError` with a comment
pointing at exactly what to check once the AAR is added and Android Studio's
autocomplete can show the real API: `readAll()`, `toSleepDto()`,
`toWorkoutDto()`. `DataTypes.BODY_COMPOSITION` / `ACTIVE_CALORIES_BURNED` /
`HEART_RATE_VARIABILITY_RMSSD` constant names are also unverified — confirmed
constants are `SLEEP`, `HEART_RATE`, `STEPS`, `EXERCISE`.

## Build order from here

1. Get the project to open in Android Studio and sync Gradle (needs the AAR
   in `app/libs/` — see `app/libs/README.md`).
2. Fix the three `NotImplementedError` spots using autocomplete on the real
   SDK types. This is a compile-and-fix loop, not a research project — the
   plumbing around them is already right.
3. Run on a device with developer mode read enabled. Tap "Grant permissions",
   then "Sync last 7 days". Read the JSON on screen before trusting it.
4. POST to `/api/v1/ingest`, confirm `accepted: true` and `features_recomputed
   > 0`, then check `/api/v1/report` for a real (non-synthetic) score.
5. Only then add a background sync worker (WorkManager, daily).

Do not build more UI. The screen above is deliberately the whole app.
