import assert from 'node:assert/strict';
import { test, after } from 'node:test';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

const dir = await mkdtemp(new URL('../node_modules/.copilot-', import.meta.url));
after(() => rm(dir, { recursive: true, force: true }));
for (const [name, path] of [['client', 'api/client'], ['store', 'store/useAnalysisStore']]) {
  let source = await readFile(new URL(`../src/${path}.ts`, import.meta.url), 'utf8');
  source = source.replaceAll('import.meta.env', '{}').replace('"../api/client"', '"./client.mjs"');
  await writeFile(join(dir, `${name}.mjs`), ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 }
  }).outputText);
}
const { explainSpike } = await import(pathToFileURL(join(dir, 'client.mjs')).href);
const { useAnalysisStore: store } = await import(pathToFileURL(join(dir, 'store.mjs')).href);
const reply = { data_source: 'real', explanation_markdown: 'Two detections [5]', citations: [], model_used: 'test' };

test('copilot sends history, exact period and geometry, then uses response provenance', async () => {
  store.getState().clearCopilotMessages();
  store.setState({ selectedPreset: 'iberia_med', selectedYear: 2026, selectedMonth: 7, selectedDate: null });
  store.getState().attachCopilotContext();
  const calls = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(JSON.parse(options.body));
    return new Response(JSON.stringify(reply));
  };
  await store.getState().askCopilot('Madrid on 24 July 2026?');
  await store.getState().askCopilot('What caused it?');
  assert.equal(calls[0].period_start, '2026-07-01');
  assert.equal(calls[0].period_end, '2026-07-31');
  assert.ok(calls[0].aoi.coordinates.length);
  assert.deepEqual(calls[0].conversation, []);
  assert.deepEqual(calls[1].conversation.map(x => x.role), ['user', 'assistant']);
  assert.equal(calls[1].conversation[0].content, 'Madrid on 24 July 2026?');
  globalThis.fetch = async () => new Response(JSON.stringify({ ...reply, data_source: 'synthetic' }));
  assert.equal((await explainSpike({})).isSynthetic, true);
});

test('clear cancels pending chat and late response cannot reappear', async () => {
  store.getState().clearCopilotMessages();
  let resolveOld;
  globalThis.fetch = () => new Promise(resolve => { resolveOld = resolve; });
  const pending = store.getState().askCopilot('Madrid 24 July 2026?');
  assert.equal(store.getState().copilotLoading, true);
  store.getState().clearCopilotMessages();
  resolveOld(new Response(JSON.stringify(reply)));
  await pending;
  assert.deepEqual(store.getState().copilotMessages, []);
  assert.equal(store.getState().copilotLoading, false);
});

test('unavailable backend surfaces an error and never fabricates a fire response', async () => {
  globalThis.fetch = async () => { throw new TypeError('Network unavailable'); };
  await assert.rejects(explainSpike({}), /Network unavailable/);
  await store.getState().askCopilot('What happened?');
  assert.equal(store.getState().copilotError, 'Network unavailable');
  assert.equal(store.getState().copilotMessages.filter(m => m.role === 'assistant').length, 0);
});

test('attaching a hex preserves chat and waits for the user question', async () => {
  store.getState().clearCopilotMessages();
  store.setState({ activeSpikeDay: { date: '2022-08-01' }, copilotMessages: [{ role: 'user', content: 'Madrid 2026' }] });
  const calls = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(JSON.parse(options.body));
    return new Response(JSON.stringify(reply));
  };
  store.getState().openCopilot({ hex: { h3_index: '872830828ffffff' } });
  assert.equal(calls.length, 0);
  assert.equal(store.getState().copilotMessages.length, 1);
  await store.getState().askCopilot('How many detections in this cell?');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].selected_day, null);
  assert.equal(calls[0].selected_hex.h3_index, '872830828ffffff');
  assert.deepEqual(calls[0].conversation, []);
});

test('selection automatically attaches exact area and day; removal stops sending them', async () => {
  store.getState().clearCopilotMessages();
  store.setState({ selectedYear: 2024, selectedMonth: null, selectedDate: null, analysisData: null });
  store.getState().setSelectedDate('2024-02-29');
  const calls = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(JSON.parse(options.body));
    return new Response(JSON.stringify(reply));
  };
  await store.getState().askCopilot('How much energy in GJ?');
  assert.equal(calls[0].period_start, '2024-02-29');
  assert.equal(calls[0].period_end, '2024-02-29');
  assert.deepEqual(calls[0].aoi, store.getState().currentAoi);
  store.getState().removeCopilotContext();
  await store.getState().askCopilot('How many detections?');
  assert.equal(calls[1].period_start, null);
  assert.equal(calls[1].period_end, null);
  assert.equal(calls[1].aoi, null);
  assert.equal(calls[1].previous_context, null);
  assert.deepEqual(calls[1].conversation, []);
  assert.equal(store.getState().copilotMessages.length, 4);
  assert.equal(store.getState().copilotMessages[0].context.end, '2024-02-29');
  store.getState().setSelectedDate('2024-02-29');
  assert.equal(store.getState().copilotContext.start, '2024-02-29');
  await store.getState().loadMapYear();
});

test('date selection updates an attached hex and snapshots current scientific filters', async () => {
  store.getState().clearCopilotMessages();
  store.setState({ excludeIndustrial: false, enableKalman: false, analysisData: null });
  store.getState().openCopilot({ hex: { h3_index: '872830828ffffff' } });
  store.getState().setSelectedDate('2020-02-29');
  let body;
  globalThis.fetch = async (_url, options) => {
    body = JSON.parse(options.body);
    return new Response(JSON.stringify(reply));
  };
  await store.getState().askCopilot('How many GJ?');
  assert.equal(body.period_start, '2020-02-29');
  assert.equal(body.period_end, '2020-02-29');
  assert.equal(body.selected_hex.h3_index, '872830828ffffff');
  assert.equal(body.exclude_industrial_flaring, false);
  assert.equal(body.enable_kalman_gap_filling, false);
  store.getState().removeCopilotContext();
  await store.getState().askCopilot('How many detections?');
  assert.equal(body.selected_hex, null);
  assert.deepEqual(body.conversation, []);
  await store.getState().loadMapYear();
});

test('new chronology attaches fresh context and preserves visible chat', async () => {
  store.getState().clearCopilotMessages();
  store.setState({ selectedYear: 2024, selectedMonth: null, selectedDate: null, analysisData: null });
  const calls = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(JSON.parse(options.body));
    return new Response(JSON.stringify(reply));
  };
  await store.getState().askCopilot('Madrid in July 2026');
  store.getState().setSelectedYear(2025);
  await store.getState().askCopilot('How many detections?');
  await store.getState().askCopilot('And in GJ?');
  assert.equal(calls[1].period_start, '2025-01-01');
  assert.equal(calls[1].period_end, '2025-12-31');
  assert.deepEqual(calls[1].conversation, []);
  assert.deepEqual(calls[2].conversation.map(m => m.content), ['How many detections?', reply.explanation_markdown]);
  assert.equal(store.getState().copilotMessages.length, 6);
  await store.getState().loadMapYear();
});

test('resolved scope survives a long conversation and is cleared by a new attachment', async () => {
  store.getState().clearCopilotMessages();
  const scope = { label: 'Madrid study envelope', aoi: store.getState().currentAoi,
    period_start: '2026-07-24', period_end: '2026-07-24' };
  const calls = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(JSON.parse(options.body));
    return new Response(JSON.stringify({ ...reply, map_context: scope }));
  };
  await store.getState().askCopilot('Madrid on 24 July 2026');
  for (let i = 0; i < 7; i++) await store.getState().askCopilot('And its energy?');
  assert.ok(!calls.at(-1).conversation.some(m => m.content === 'Madrid on 24 July 2026'));
  assert.deepEqual(calls.at(-1).previous_context, scope);
  store.getState().setSelectedYear(2025);
  await store.getState().askCopilot('How many GJ?');
  assert.equal(calls.at(-1).previous_context, null);
});


test('drawing an area preserves the exact selected day and attaches it automatically', async () => {
  store.getState().clearCopilotMessages();
  store.setState({ selectedYear: 2026, selectedMonth: 7, selectedDate: '2026-07-24', selectedDay: 24,
    selectedDoy: 205, minDate: null, maxDate: null });
  const aoi = [[[-4.3,40.3],[-4.1,40.3],[-4.1,40.5],[-4.3,40.5],[-4.3,40.3]]];
  const history = { data_source: 'real', calendar_series: [], forecast_series: null, map_hexagons: [] };
  globalThis.fetch = async () => new Response(JSON.stringify(history));
  await store.getState().setCustomAoi(aoi);
  assert.equal(store.getState().selectedDate, '2026-07-24');
  assert.equal(store.getState().copilotContext.start, '2026-07-24');
  assert.equal(store.getState().copilotContext.end, '2026-07-24');
  assert.deepEqual(store.getState().copilotContext.aoi.coordinates, aoi);
  assert.match(store.getState().copilotContext.label, /40\.400/);
  assert.equal(store.getState().copilotContext.hex, null);
});

test('hovering the chronology does not replace a deliberately added context', async () => {
  store.getState().clearCopilotMessages();
  store.setState({ minDate: null, maxDate: null, analysisData: null });
  store.getState().setSelectedDate('2026-07-24');
  store.getState().setSelectedDate('2026-07-25', false);
  assert.equal(store.getState().copilotContext.start, '2026-07-24');
  store.getState().setSelectedYear(2025, false);
  store.getState().setSelectedMonth(9, false);
  assert.equal(store.getState().copilotContext.start, '2026-07-24');
  store.getState().setSelectedMonth(9, true);
  assert.equal(store.getState().copilotContext.start, '2025-09-01');
  await store.getState().loadMapYear();
});
