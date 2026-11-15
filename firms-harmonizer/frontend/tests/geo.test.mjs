import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';

const dir = await mkdtemp(new URL('../node_modules/.geo-', import.meta.url));
after(() => rm(dir, {recursive: true, force: true}));
const source = await readFile(new URL('../src/lib/geo.ts', import.meta.url), 'utf8');
await writeFile(join(dir, 'geo.mjs'), ts.transpileModule(source, {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}
}).outputText);
const {polygonAreaKm2, MAX_AOI_AREA_KM2} = await import(pathToFileURL(join(dir, 'geo.mjs')).href);

test('an equatorial one-degree box is about 12,300 km²', () => {
  const box = [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]];
  const area = polygonAreaKm2(box);
  assert.ok(Math.abs(area - 12300) < 150, `expected ~12,300 km², got ${area}`);
});

test('the preflight limit mirrors the server', () => {
  assert.equal(MAX_AOI_AREA_KM2, 1_250_000);
});

test('a continental box exceeds the limit and a hole is subtracted', () => {
  const huge = [[[-100, -50], [50, -50], [50, 50], [-100, 50], [-100, -50]]];
  assert.ok(polygonAreaKm2(huge) > MAX_AOI_AREA_KM2);
  const outer = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]];
  const hole = [[[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]];
  const withHole = polygonAreaKm2([outer[0], hole[0]]);
  const withoutHole = polygonAreaKm2(outer);
  assert.ok(withHole < withoutHole);
});
