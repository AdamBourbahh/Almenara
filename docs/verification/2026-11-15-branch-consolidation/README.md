# Branch consolidation verification

All local and origin branches were compared by ancestry and unique commits before cleanup. The original refs are recorded in branches.json. Every recorded tip is an ancestor of the consolidated main. A pre-integration Git bundle is retained locally at /tmp/almenara-before-consolidation.bundle.

Most frontend, API, physics and risk work was already upstream. The remaining streaming ETL branch adds archive clipping, global counts, NASA POWER cloud inputs, MODIS swath evidence and bounded memory. Its original ETL lineage is retained, while the obsolete parallel industrial module is superseded by the canonical stage. The Copilot branch adds calculation tools, per-sensor summaries, domain handling and calculation provenance; these coexist with Gemini-directed source research, evidence review and local numerical tools.

Conflicts retain current confidence filtering, null ancillary semantics, current regions, exact selected periods, typed quantity validation and explicit provider selection. Pipeline test detections and border cases were migrated to Chilecito; the SAMA control remains in its physical geographic zone. The coordinated fixture migration updates the pipeline-only frozen hashes. Backend frozen contract hashes remain unchanged. Synthetic data were regenerated explicitly for tests. The local real cube was republished from accepted staging with the nominal confidence filter, producing 885,626 rows; the previous cube was backed up in /tmp.

Validation: 744 combined backend/pipeline tests passed; 55 frontend tests passed; TypeScript and the production Vite build passed. The subsequent bounded repair-step adjustment passed the Copilot agent, Gemini and evidence regression subset. Full logs are included here. The final running-web research request is recorded separately in live-copilot.json; external provider availability is not guaranteed by the test suite.

Existing auxiliary worktrees were detached without removing their directories or uncommitted local files. The unrelated untracked local skills directory was left untouched. Credentials, environments, dependencies and local data cubes are not uploaded.
