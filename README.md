# Almenara — FIRMS Harmonizer

Harmonized MODIS + VIIRS fire radiative energy for the **NASA Space Apps Challenge 2026** (*Harmonization of MODIS and VIIRS Hot Spots*).

- **Application, features and known limits:** [`firms-harmonizer/README.md`](firms-harmonizer/README.md)
- **Delivery log, fixes and verification:** [`Miguelspecs.md`](Miguelspecs.md)
- **Backend plan and phase evidence:** [`Implementation_backend_plan.md`](Implementation_backend_plan.md)
- **Scientific specification and contracts:** [`SPECS.md`](SPECS.md)
- **Ownership and technical guardrails:** [`AGENTS.md`](AGENTS.md)
- **Live demo:** <https://firms-harmonizer-612652227111.europe-west1.run.app>

## Use of artificial intelligence

This project was built with AI assistance and also ships an optional AI feature. Every tool is listed below. Team members reviewed, tested and take responsibility for all AI-assisted work; automated tests, frozen contract hashes and the verification reports under [`docs/verification/`](docs/verification/) gate what is merged.

### AI used to build the project

| Tool | Provider | Used for |
| :--- | :--- | :--- |
| **Claude Code** with Claude Opus 5.5, Claude Fable 5.2, Claude Sonnet 5.5 and Claude Haiku 5.5 | Anthropic | Code generation, refactoring, tests, reviews, verification runs and documentation. AI-assisted commits carry a `Co-Authored-By: Claude …` trailer in the git history. |
| **Claude (claude.ai Artifacts)** | Anthropic | Drafting and publishing the pitch deck (see [`docs/pitch/`](docs/pitch/)). |
| **Aider, Cursor, Windsurf, Cline and GitHub Copilot** | Aider, Anysphere, Codeium, Cline, GitHub | Supported AI coding assistants. The repository ships a shared rule file for each (`firms-harmonizer/.aider.conf.yml`, `.cursorrules`, `.windsurfrules`, `.clinerules`, `.github/copilot-instructions.md`), all generated from [`AGENTS.md`](AGENTS.md) so that any assistant a team member uses follows the same ownership rules and guardrails. The per-track prompts given to these assistants are kept in [`firms-harmonizer/prompts/`](firms-harmonizer/prompts/). |

### AI inside the application (optional, off by default)

| Component | Provider | Role |
| :--- | :--- | :--- |
| **Gemini** (`gemini-3.8-flash`, default provider) | Google | Fire Copilot online mode: chooses read-only tools, writes prose around locally computed numbers, and proposes candidate sources through Google Search grounding. |
| **Open-weight models hosted on Groq** (`openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `llama-3.3-70b-versatile`) | Groq (models by OpenAI and Meta) | Explicit alternative Copilot provider (`COPILOT_PROVIDER=groq`). Never a silent fallback. |
| **Tavily Search API** | Tavily | Optional AI-oriented web search for Copilot source discovery; DuckDuckGo search is used when no key is set. |

`COPILOT_OFFLINE=1` is the default: with it, no AI service is contacted and the Copilot answers from deterministic local calculations. In online mode the language model never produces the scientific quantities; energy, biomass, emissions and statistics are computed by local Python and DuckDB code and only displayed by the model's answer.

### Not generative AI

The harmonization itself (EQM calibration, the RTS Kalman smoother, Von Mises phenology, Chow and Wasserstein diagnostics) and the "Risk AI" forecast are classical statistical models trained locally on the NASA archive. No large language model is involved in them. The Copilot's read-aloud voice uses the browser's built-in speech synthesis.
