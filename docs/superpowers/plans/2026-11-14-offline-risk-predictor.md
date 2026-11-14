# Offline Risk Predictor Implementation Plan

**Goal** — Forecast observable thermal activity from the local FIRMS cube and show the forecast and its temporal validation in Impact.

**Architecture** — DuckDB creates daily AOI features from dated observations. The isolated NumPy/SciPy core builds causal features, fits three classical models and calibrates their stack. A synchronous endpoint serves a provenance-aware response that the Impact card loads on demand.

**Spec** — `SPECS.md`, the risk predictor contract and the 2026-11-14 implementation request.

- [x] Write failing core tests for probability bounds, stronger thermal activity, persistent-source separation, causality, missing data and evaluation splits. Add endpoint tests for empty AOIs, dates, provenance and caching.
- [x] Build the dense daily matrix from dated raw FRP, past-only spatial and persistence features, causal climatology, trailing activity, and explicit missingness. The existing all-history EQM/industrial values and bidirectional RTS output are ineligible for honest historical validation. The thermal-event targets are proxies until independent incident labels exist.
- [x] Fit regularized logistic regression, boosted stumps and Gaussian naive Bayes per target and horizon. Fit stack calibration before the final holdout with label-window embargoes. Report scores and reliability from unseen dates with adequate class support.
- [x] Wire the additive endpoint, TS contract and Impact card. Show the cutoff, horizon, actual target and real/synthetic distinction. Preserve the existing analysis, map and forecast-series contracts.
- [x] Run the required test and build gates and measure cold model and end-to-end times on Chilecito and Iberia. Review chronology leakage, aggregation bounds, untrusted geometry, missing coverage and concurrent request behavior.
