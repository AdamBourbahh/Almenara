# Differential review of the offline thermal predictor

Baseline: main at 93a7b1f. Scope: the new risk route, its database/core call chain,
the additive response contract and the Impact card. Medium risk because the route is
public, fits models synchronously, and produces figures that users could apply beyond
their validated scope.

| Severity | Open findings |
| --- | ---: |
| Critical | 0 |
| High | 0 |
| Medium | 2 |
| Low | 0 |

**Conditional approval for local thermal-signal exploration.** The label and latency
requirements below remain open.

1. **Medium. Physical incident probability is unverifiable with the supplied data.**
   Independent event labels and complete observation coverage are absent. The model
   validates two FIRMS proxies against held-out local data. The endpoint identifies the
   proxy target and the UI describes the observed events, shows the UTC cutoff and
   marks unavailable estimates. Calibration here cannot establish the probability of a
   real ignition, spread event or accident.
2. **Medium. Cold requests exceed the core latency budget.** Three base learners and
   a calibrator fit several correlated horizon/target pairs. Same-AOI repeat requests
   use a bounded LRU. Different AOIs can still cause concurrent expensive queries.
   The existing polygon guard limits each request to 250,000 R7 cells. This path is
   suitable for the local dashboard; the cache is not public-service rate limiting.

The route has one frontend entry point, the Impact card. It uses the existing
polygon validator, Arrow registration for both H3 levels, request-local cursors and
bound temporal parameters. Interpolated SQL fragments are fixed column alternatives.
The core imports NumPy and SciPy and has no database, HTTP or file access. Existing
routes, contracts, and map callers continue using their original data. The card
cancels abandoned requests and avoids showing an older AOI's response.

The first 80% of dates contain disjoint fit and calibration origins with a gap of
one label horizon before each following subset. Full-history ETL coefficients,
industrial entropy and RTS estimates are excluded. Prefix-invariance is checked
in both the database and the model, and recent-data changes do not alter earlier
held-out forecasts. Days without a reported detection and a change in the sensor
mix remain limitations of the proxy. The code review did not establish scientific
calibration against an independent record or susceptibility to sustained load.

Checks: 74 core and frozen HTTP tests, 29 risk/DB/map-period tests, and 8 frontend
regression tests passed. TypeScript and production build passed. Playwright verified
the dated risk card and horizon controls in Chilecito and Iberia, including the missing
persistent-source estimate in Chilecito.
