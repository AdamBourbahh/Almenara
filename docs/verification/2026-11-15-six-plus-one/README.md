# Copilot six-zone validation — work in progress

This branch is an explicit checkpoint requested by the user before leaving home.
It is not a completed certification. Online model failures now return an explicit
unverified-answer status instead of silently invoking the local investigator.
Explicit offline operation remains available. Model reads allow 15 seconds per
call; the multi-tool workflow retains a bounded overall deadline.

The new scientific-audit tool exposes selected-period mapped FRE, full-record
Chow/W1 diagnostics, the latest von Mises fit and reconstructed/unknown days.
The live runner compares real API results with pipeline outputs and direct
Parquet energy integration. Model requests are not mocked. Failed rounds will
be retained. A held-out zone requires six numerically and semantically reviewed
passes before execution.

Validation is ongoing. Existing tests that assumed automatic online-to-local
substitution must be reconciled with the requested explicit-error behavior.
The first completed live zone (arid Argentina, cross-year selection) returned a
Gemini answer and matched its numeric reference. This alone does not certify six
zones or establish absence of hallucinations.

Cloud-cover values are entirely missing from the current cube. The Amazon case
tests a tropical selection and missing coverage evidence, not independently
measured cloudy weather. The persistent-source case is a published-match
candidate, not independent field confirmation of gas flaring.

No credentials belong in this directory or in committed environment files.
