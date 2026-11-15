import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';

const dir = await mkdtemp(new URL('../node_modules/.scale-', import.meta.url));
after(() => rm(dir, {recursive: true, force: true}));
const source = await readFile(new URL('../src/components/Map/mapMetrics.ts', import.meta.url), 'utf8');
await writeFile(join(dir, 'mapMetrics.mjs'), ts.transpileModule(source, {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}
}).outputText);
const {colorIntensity, robustReference} = await import(pathToFileURL(join(dir, 'mapMetrics.mjs')).href);

test('robustReference is not dominated by a single mega-fire', () => {
  const values = [...Array(99).keys()].map((i) => i + 1).concat([1_000_000]);
  const reference = robustReference(values);
  assert.ok(reference < 1_000_000, 'the outlier must not set the reference');
  assert.ok(reference >= 90, `expected a high percentile, got ${reference}`);
});

test('robustReference falls back to the max for small samples and to 1 when empty', () => {
  assert.equal(robustReference([2, 1]), 2);
  assert.equal(robustReference([5]), 5);
  assert.equal(robustReference([0, 0, -1]), 1);
  assert.equal(robustReference([]), 1);
});

test('colorIntensity keeps every positive value visible and zero invisible', () => {
  assert.equal(colorIntensity(0, 1000), 0);
  assert.ok(colorIntensity(1, 1_000_000) >= 0.22, 'a single detection must stay visible');
  assert.equal(colorIntensity(1_000_000, 1_000_000), 1);
});

test('quiet day counts become legible with the period reference', () => {
  // 2026-06-04 (Alosno ignition): counts 2 and 1 against a 26-year maximum of 126.
  const oldT = colorIntensity(1, 126);
  const newT = colorIntensity(1, robustReference([2, 1]));
  assert.ok(oldT < 0.3, `old fixed scale was faint, got ${oldT}`);
  assert.ok(newT > 0.6, `period scale must make it legible, got ${newT}`);
});
