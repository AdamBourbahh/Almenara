# Coverage policy and integration results

The fixed requirement for 95% complete whole-region days has been replaced by a
comparison of 70%, 80%, 90% and 95% daily terrestrial support thresholds. The local
experiment covers 2020-11-10 through 2026-11-14. The complete source mask archive
remains retained; older support is unknown to this forecast experiment.

| Region | Mean qualified terrestrial support | Selected threshold |
| --- | ---: | --- |
| Chilecito | 86.3% | None passed |
| Iberia | 84.8% | None passed |
| Orlando | 84.1% | None passed |
| Amazonas/Manaus | 70.6% | None passed |

These percentages are spatially weighted support averages, not percentages of
complete days. Sensors are combined by cell without counting overlap twice.
Preceding-year measured land/water pixels determine terrestrial weights. Unknown
land/water area stays potentially unobserved land in the denominator.

Existing packed masks preserve binary cell qualification (>=95% valid samples,
>=50% sampled-area screen), not all original per-pixel observations. The new
measurement is consequently a qualified-cell support proxy, not exact clear-land
area or a guarantee of continuous observation. Historical observed-zero semantics
remain conservative. No unknown energy is upscaled or replaced with zero.

Thresholds are selected on the penultimate year's rolling-origin comparisons and
checked on an untouched final-year holdout. Common high-support origins and labels
keep the comparison consistent; ties prefer higher coverage. Every horizon
(1/7/14 days) needs at least 12 cases, four seasonal groups, MAE no worse than both
persistence and climatology, and >=90% empirical interval coverage. Signed bias is
also reported. A failed holdout does not trigger selection of a different threshold.

None of the four regions supports publication under these checks. Low case counts
and/or baseline performance remain visible in [coverage-policy.json](coverage-policy.json).
The API keeps forecasts null and explains the failed selection/validation gate.
These checks concern the sampled thermal-energy proxy, not independent physical
energy ground truth. Combining more masks can improve observation support but
does not guarantee forecast skill.

Run `python scripts/13_validate_coverage.py` to reproduce the comparison. Matching
source revisions reuse published preset indexes; changed inputs invalidate them.
An arbitrary AOI without a matching index retains an unavailable forecast.

The local integration first updates main from origin/main and merges all-nighter,
preserving upstream chronology ranges, map search/scaling, settings and Copilot
investigation/RAG. The validation branch then adds the final evidence and a
regression ensuring daily footprint metadata aligns with the clipped calendar.
Independent energy tests retain exact per-cell integrals and geodesic polygon
normalization. Episode PM2.5 requires the same annual fuel inputs as the API.

Final integrated verification: **494 backend tests**, **30 frontend tests**, the
TypeScript/production build and four frozen-test hashes pass. The real acceptance
runner independently verifies cell-area energy integrals and concurrent HTTP
results in all four regions. See [integration-checks.json](integration-checks.json).
