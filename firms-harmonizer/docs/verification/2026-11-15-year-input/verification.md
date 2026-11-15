# Editable year regression

Clearing the controlled year input previously rebuilt its value as `-01-01`.
Slicing that string back into the numeric field made it impossible to type a new
year character by character. A separate draft year now preserves partial input;
only a complete year updates the draft date, and Apply commits the chosen period.

The Chromium regression clears the field, types 2020 character by character and
applies it. Before the fix it failed with an empty year; after the fix it selected
2020 successfully. This test uses an explicitly synthetic, isolated in-memory UI
fixture and aborts API requests; it does not modify the real archive or user chat.

Run the script with `playwright-core` available to Node and Chromium installed:

```sh
NODE_PATH=/tmp/almenara-browser/node_modules node docs/verification/2026-11-15-year-input/browser-regression.cjs
```

Production build and all 30 frontend tests passed. Other concurrent workspace
changes were retained; the fix only changes the chronology component.
