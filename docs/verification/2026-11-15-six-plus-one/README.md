# Copilot: six reviewed zones plus a fresh holdout

Seven recorded queries pass: [six-zone round](round-06.json), then the [fresh holdout](holdout-02.json), which passed its first attempt. Live testing stopped there. This certificate covers those exact queries; it is not a universal chatbot or environmental validation. Source hashes and limits are in [certificate.json](certificate.json).

At baseline `39c8a9c`, `backend/api/copilot_agent.py:468-475` caught model/tool failures and invoked the local investigator. Online failures now return an explicit insufficient-context response with a provider-error identifier. Explicit offline use remains available. Model reads allow 15 seconds; the multi-tool workflow retains a 55-second deadline. Local scientific work adds time, so this is not a 15-second end-to-end API guarantee.

The new scientific-audit tool exposes selected-period mapped FRE and gap counts, full-archive Chow/W1 and the latest supported directional von Mises fit. Server results remain verbatim. Nulls cannot authorize invented causes; zero-energy annual display sentinels are not fitted burning peaks. A broad pilot envelope cannot replace the selected location in model context.

| Zone | H3 R7 polygon | Fallback | Data match | Hallucination detected | Result |
|---|---|---|---|---|---|
| Arid Argentina, Dec-Jan | `87b254925ffffff` | False | True | False | PASS |
| Amazon basin | `878af68f2ffffff` | False | True | False | PASS |
| Florida | `8744f690cffffff` | False | True | False | PASS |
| Atlantic Iberia | `87185ba0cffffff` | False | True | False | PASS |
| Mediterranean Iberia | `873915d61ffffff` | False | True | False | PASS |
| Persistent-source candidate | `873954066ffffff` | False | True | False | PASS |
| Fresh northern-African holdout | `873829872ffffff` | False | True | False | PASS |

Polygons are the exact closed H3 boundaries in GeoJSON longitude/latitude order. Full requests, responses and model calls are saved. Argentina uses 2022-12-15 through 2023-01-15, the persistent-source case uses 2013, and the others use 2023. These selected-cell identifiers have no tracked QA/docs/scripts matches at baseline. [Selection provenance](selection-provenance.json) includes measured annual land-cover classes and dominant fractions; region names are not measured biome labels.

The runner calls the actual `/api/analyze` scientific pipeline and `/api/explain-spike` routes over real Parquet, with real Gemini requests. No model response, tool output or citation is mocked, and expected reference numbers are not included in the question. This is not fresh NASA acquisition or browser UI testing.

Independent DuckDB SQL reads cell observations and raw counts. Separate arithmetic verifies within-cell sensor-mean FRE times exact H3 area, annual-regression Chow F/p, empirical-CDF Wasserstein distance and circular moments/Best-Fisher von Mises parameters. Qualified clear zeros are decoded directly from packed mask Parquet without production coverage adapters. Counts match exactly. Floating-point tolerances: 1e-12 relative for returned values; 1e-10 for independent statistics; 1e-10 absolute. All requested quantities match, including correctly rounded prose numbers.

Complete prose and structured output were reviewed for unsupported quantities, geographic/incident identity, ignition, cloudy-weather claims and invented null causes. Case-specific review notes and response hashes are retained. Numerical equality alone is not proof of no hallucinations.

Early rounds exposed an invented null explanation and an unsupported annual peak sentinel. An oracle setup initially omitted measured clear-zero mask evidence; that validator was corrected before certification. [Round 04](round-04.json) retains a real read timeout as FAIL. The [first holdout](holdout-01.json) matched numbers but incorrectly called a northern-African cell Iberian; it is marked as a geographic hallucination. After fixing context, all six zones were rerun and reviewed before a different held-out cell. Failed answers were not replaced with successful ones.

Fresh checks after the last production change: **684 backend tests**, **55 frontend tests**, TypeScript/production build and all four frozen hashes pass. Existing tests now expect explicit online errors; numerical-unit, citation and identity rejection assertions remain. New regressions reproduced their bugs before correction. Public schemas are unchanged.

Measured cloud cover is absent, so cloudy-weather behavior is **not certified**. Reconstruction is enabled, but these cells have no eligible missing-energy episodes requiring RTS reconstruction; positive recovery is **not certified**. The persistent-source cell has a published-match industrial probability near 0.962; this is not independent field confirmation of gas flaring. Unknown days are not cloud observations or proof of no fire. Semantic review is specific to these responses, not every possible conversational intent.

Credentials were process-environment only and were not committed. See the [focused diff review](DIFFERENTIAL_REVIEW.md). Reproduce with `scripts/14_certify_copilot.py --output <new-round.json>` and an environment credential. `--reviewed-six <six.json> --holdout-cell <new-cell>` requires six numerical and semantic passes before a holdout. Check each new holdout against retained attempt history too.
