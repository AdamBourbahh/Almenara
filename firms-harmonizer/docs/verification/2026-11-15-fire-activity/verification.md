# Madrid activity regression

Real-data screenshot approximation: longitude −4.85 to −4.068, latitude 40.13 to
40.636. These are study-envelope bounds, not an incident perimeter.

The real map-period API returned:

| UTC date | Map detections | Active cells |
| --- | ---: | ---: |
| 2026-07-27 | 1191 | 73 |
| 2026-07-28 | 72 | 19 |
| 2026-07-29 | 1 | 1 |
| 2026-07-30 | 2 | 2 |
| 2026-07-31 | 6 | 9 |
| 2026-08-01 | 15 | 5 |
| 2026-08-04 | 0 | 0 |

The apparent 27 July cutoff was not an archive cutoff. Tiny counts were visually
similar to zero bars. Dates without observations do not establish extinction.

The reproduced chatbot failure logged `Unsupported numerical claim`, followed by
a generic local fallback. Regression tests now exercise bounded numeric correction,
citation-number exclusion and direct active-burning answers offline. Live requests
also encountered Groq HTTP 429 quota failures, which remain external constraints.
A final live `is this a fire?` request used `groq-agent/openai/gpt-oss-120b` and led
with probable active burning, followed by exact server-calculated observations.

Validation: 482 backend tests passed; 57 focused Copilot tests passed; 29 frontend
tests passed; TypeScript/production build passed. Chromium verifies 5 px small
positive bars against a 1 px zero baseline. [Screenshot](july28.png).

Reported control date is separate from satellite activity. The reviewed report
[El País, 4 August 2026](https://elpais.com/espana/madrid/2026-08-04/controlado-el-incendio-de-la-sierra-oeste-de-madrid-tras-14-dias-ardiendo.html)
describes control after fourteen days; control is not full extinction.
