# Samsung Health Data SDK AAR goes here

The SDK is not distributed via Maven Central — download the `.aar` from
Samsung Developer (requires a free Samsung Developer account) and drop it in
this folder. It is picked up automatically by the `fileTree` dependency in
`app/build.gradle.kts`.

Source: <https://developer.samsung.com/health/data/overview.html> (download
link is on that page; exact URL changes per SDK release, so it is not hardcoded
here).

This directory is otherwise empty in git — `.aar` files are gitignored
(see the root `.gitignore`), since they are large binaries you re-download
rather than commit.
