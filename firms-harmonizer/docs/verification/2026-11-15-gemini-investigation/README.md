# Gemini incident investigation verification

The original Orlando holdout was rerun against the current real cube, with the
same polygon (-81.03 to -80.88 longitude, 28.68 to 28.82 latitude) and selected
day, 2011-02-28. No incident name or curated incident record was added to the
request or knowledge corpus. Requests, actual answers, source URLs and tool names
are in [orlando-live.json](orlando-live.json).

All three live answers used `gemini-agent/gemini-3.8-flash`: activity assessment,
incident/cause research, and energy. Research retrieved NASA's regional report,
retained Iron Horse, Keller and Ferry-7 as documented regional candidates, and
stated that ignition was absent from that article. It did not equate selected
hexagons with a verified incident perimeter. The selected day survived follow-ups.

After restarting the API, the same unprepared incident question was sent through
the running Vite proxy at `/api/explain-spike`. It returned HTTP 200 in 35.46
seconds, used Gemini, cited NASA's Iron Horse report, retained the selected day,
and distinguished a regional candidate from a verified perimeter match. The actual
request and response are in [running-web.json](running-web.json).

Independent direct staging SQL, using R7 cells and their unique R4 parents,
returned 22 detections and 19,593.5 MW summed instantaneous FRP. Separately reading
the current cube and averaging finite available sensors inside each cell, then
integrating exact H3 areas, returned 52,499.43275733092 GJ. This matched the energy
tool. The earlier holdout's 52,510.466 GJ was measured in another checkout and was
not used as an expected value for this cube.

The selected Copilot suite passed 192 tests, including provider failures, explicit
Groq selection, no cross-provider credential use, offline behavior, SQL/geometry
ownership, unsupported numeric repair, source retrieval, county/date mismatch,
bounded article packing, refined searches, Gemini evidence review and period
preservation. Public contracts and frozen-test hashes were not modified.

This finite test establishes this case's behavior, not universal incident matching
or independently verified ignition causes. Gemini's final evidence review is still
model-based; provider outages and unrecoverable invalid output retain local fallback.
