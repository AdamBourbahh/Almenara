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

test('opening a selected hex clears unrelated day context and avoids duplicate sends', async () => {
  store.getState().clearCopilotMessages();
  store.setState({ activeSpikeDay: { date: '2022-08-01' } });
  const calls = [];
  globalThis.fetch = async (_url, options) => {
    calls.push(JSON.parse(options.body));
    return new Response(JSON.stringify(reply));
  };
  store.getState().openCopilot({ hex: { h3_index: '872830828ffffff' } });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].selected_day, null);
  assert.equal(calls[0].selected_hex.h3_index, '872830828ffffff');
  assert.deepEqual(calls[0].conversation, []);
});
