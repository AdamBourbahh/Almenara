import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';

const dir = await mkdtemp(new URL('../node_modules/.copilot-drawer-', import.meta.url));
after(() => rm(dir, {recursive: true, force: true}));
const source = await readFile(new URL('../src/components/Audit/copilotPresentation.ts', import.meta.url), 'utf8');
await writeFile(join(dir, 'p.mjs'), ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}}).outputText);
const P = await import(pathToFileURL(join(dir, 'p.mjs')).href);

const cube = {id: '[6]', source_type: 'NASA_DATASET'};
const report = {id: '[W1]', source_type: 'WEB_NEWS_REPORT'};
const formula = {label: 'Consumed dry biomass', formula: '412.500 GJ × 0.368 t/GJ = 151.800 t', value: 151.8, unit: 't'};
const kinds = (response) => P.evidenceBadges(response).map((badge) => badge.kind);

test('badges follow the server provenance in a fixed order', () => {
  const response = {citations: [cube, report, report], web_search_used: true,
    evidence_sources: ['web', 'knowledge', 'verified_calculation', 'local_cube'], verified_calculations: {items: [formula]}};
  assert.deepEqual(kinds(response), ['local_cube', 'verified_calculation', 'web', 'knowledge']);
  const web = P.evidenceBadges(response).find((badge) => badge.kind === 'web');
  assert.equal(web.label, 'Web investigation · 2 sources');
  assert.ok(P.evidenceBadges(response).every((badge) => badge.detail.length > 20));
});

test('a declined question shows only the guardrail badge', () => {
  assert.deepEqual(kinds({citations: [cube], web_search_used: true, guardrail_triggered: true,
    evidence_sources: ['guardrail']}), ['guardrail']);
  assert.deepEqual(kinds({citations: [], web_search_used: false, guardrail_triggered: true}), ['guardrail']);
});

test('responses from before the provenance field are inferred, never over-claimed', () => {
  assert.deepEqual(kinds({citations: [cube], web_search_used: false}), ['local_cube']);
  assert.deepEqual(kinds({citations: [report], web_search_used: true}), ['web']);
  assert.deepEqual(kinds({citations: [], web_search_used: false, verified_calculations: {items: [formula]}}),
    ['local_cube', 'verified_calculation']);
  assert.deepEqual(kinds({citations: [], web_search_used: false}), []);
  assert.deepEqual(kinds(null), []);
  assert.equal(P.evidenceBadges({citations: [], web_search_used: true})[0].label, 'Web investigation');
});

test('only well-formed calculation rows are shown', () => {
  assert.deepEqual(P.calculationItems({verified_calculations: {items: [formula, null, {label: 'x'}, {label: 'y', formula: ' '}]}}), [formula]);
  assert.deepEqual(P.calculationItems({verified_calculations: null}), []);
  assert.deepEqual(P.calculationItems({verified_calculations: {items: 'not a list'}}), []);
  assert.deepEqual(P.calculationItems(undefined), []);
});

test('refusal text drops the bullet list that becomes tappable prompts', () => {
  const prompts = ['How much fire energy was consumed in this area during 2022?', 'How has the peak shifted?'];
  const content = `I am a specialized Wildfire & Land Management Copilot.\n\nQuestions I can answer here:\n\n- ${prompts[0]}\n- ${prompts[1]}`;
  assert.equal(P.refusalBody(content, prompts), 'I am a specialized Wildfire & Land Management Copilot.');
  assert.equal(P.refusalBody(content, []), content);
  assert.equal(P.refusalBody('- An unrelated list item', prompts), '- An unrelated list item');
});

test('starter prompts adapt to the attached area and period', () => {
  const year = P.starterPrompts({label: 'Chilecito, La Rioja (Argentina)', start: '2023-01-01', end: '2023-12-31'});
  assert.equal(year.caption, 'Chilecito, La Rioja (Argentina) · 2023');
  assert.equal(year.prompts.length, 4);
  assert.equal(year.prompts[0], 'Compare biomass consumed in this area between 2019 and 2023');
  assert.ok(year.prompts.some((prompt) => prompt.includes('fire season peak shifted')));
  assert.ok(year.prompts.some((prompt) => prompt.includes('largest thermal events')));
  assert.ok(year.prompts.some((prompt) => prompt.includes('industrial gas flaring')));
  const day = P.starterPrompts({label: 'Selected area at 40.400°, -4.200°', start: '2026-07-24', end: '2026-07-24'});
  assert.equal(day.caption, 'Selected area at 40.400°, -4.200° · 2026-07-24');
  assert.match(day.prompts[0], /on 2026-07-24\?$/);
  const range = P.starterPrompts({label: 'Area', start: '2022-07-01', end: '2022-08-31'});
  assert.equal(range.caption, 'Area · 2022-07-01 to 2022-08-31');
});

test('comparison years stay inside complete years of the record', () => {
  assert.match(P.starterPrompts({label: 'A', start: '2026-01-01', end: '2026-12-31'}).prompts[0], /between 2021 and 2025$/);
  assert.match(P.starterPrompts({label: 'A', start: '2001-01-01', end: '2001-12-31'}).prompts[0], /between 2001 and 2005$/);
  assert.match(P.starterPrompts({label: 'A', start: 'unparsed', end: 'malformed'}).prompts[0], /between 2021 and 2025$/);
});

test('without an attached area the prompts name their own place or need none', () => {
  const none = P.starterPrompts(null);
  assert.equal(none.caption, null);
  assert.equal(none.prompts.length, 4);
  assert.ok(none.prompts.every((prompt) => !/this area|\bhere\b/.test(prompt)));
});

test('no prompt or badge addresses the reader by role', () => {
  const text = JSON.stringify([P.starterPrompts(null), P.starterPrompts({label: 'A', start: '2022-01-01', end: '2022-12-31'}),
    P.evidenceBadges({citations: [], web_search_used: true, evidence_sources: ['local_cube', 'verified_calculation', 'web', 'knowledge', 'guardrail']})]);
  assert.doesNotMatch(text, /land manager|firefighter|dispatcher|as a /i);
});
