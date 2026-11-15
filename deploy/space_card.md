---
title: FIRMS Harmonizer
emoji: 🔥
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Harmonized MODIS and VIIRS fire energy, 2000–2026
---

# FIRMS Harmonizer

Harmonized MODIS and VIIRS active-fire energy for four study regions (Chilecito, the Iberian
Peninsula, Orlando and Amazonas/Manaus), built for the NASA Space Apps Challenge 2026.

The app combines a hexagonal fire-energy map, a daily burning calendar, phenology and audit
diagnostics, a thermal risk outlook and an evidence-first Fire Copilot. Every response states
whether it comes from real NASA FIRMS observations or the labelled synthetic demo cube.

This Space is deployed automatically from the project repository. Runtime data is loaded at
start-up from the companion dataset named in the `DATA_REPO` variable. The Space sleeps after
a period without visitors; the first request after that takes about a minute.
