import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';
import {gridDisk, latLngToCell} from 'h3-js';

const dir = await mkdtemp(new URL('../node_modules/.aoicells-', import.meta.url));
after(() => rm(dir, {recursive: true, force: true}));
const source = await readFile(new URL('../src/lib/aoiCells.ts', import.meta.url), 'utf8');
await writeFile(join(dir, 'aoiCells.mjs'), ts.transpileModule(source, {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}
}).outputText);
const {cellsFromPolygon, polygonFromCells, removalKeepsConnected} = await import(pathToFileURL(join(dir, 'aoiCells.mjs')).href);

const box = {
  coordinates: [[[-7.35, 37.25], [-6.85, 37.25], [-6.85, 37.7], [-7.35, 37.7], [-7.35, 37.25]]]
};

test('a cell AOI round-trips through its hexagon outline', () => {
  const cells = cellsFromPolygon(box);
  assert.ok(cells.length > 0, 'the box must contain cells');
  const polygon = polygonFromCells(cells);
  assert.ok(polygon, 'the cell union must produce a polygon');
  const back = cellsFromPolygon(polygon);
  assert.equal(back.length, cells.length);
  assert.deepEqual(new Set(back), new Set(cells));
});

test('an empty cell set has no polygon', () => {
  assert.equal(polygonFromCells([]), null);
});

test('disconnected islands keep only the largest one', () => {
  const a = latLngToCell(37.5, -7.1, 7);
  const b = latLngToCell(40.4, -3.7, 7);
  const polygon = polygonFromCells([a, b]);
  assert.ok(polygon);
  const back = cellsFromPolygon(polygon);
  assert.equal(back.length, 1);
  assert.ok(back.includes(a) || back.includes(b));
});

test('two adjacent cells keep their shared boundary', () => {
  const a = latLngToCell(37.5, -7.1, 7);
  const b = gridDisk(a, 1).find((cell) => cell !== a);
  const polygon = polygonFromCells([a, b]);
  assert.ok(polygon);
  assert.deepEqual(new Set(cellsFromPolygon(polygon)), new Set([a, b]));
});

test('removing a bridge cell is rejected, an edge cell is allowed', () => {
  const a = latLngToCell(37.5, -7.1, 7);
  const ringA = new Set(gridDisk(a, 1));
  const b = gridDisk(a, 1).find((cell) => cell !== a);
  const c = gridDisk(b, 1).find((cell) => cell !== b && !ringA.has(cell));
  assert.ok(c, 'expected a cell that is two steps away');
  assert.equal(removalKeepsConnected([a, b, c], b), false, 'b bridges a and c');
  assert.equal(removalKeepsConnected([a, b, c], a), true, 'the b-c edge survives');
  assert.equal(removalKeepsConnected(gridDisk(a, 2), gridDisk(a, 2)[0]), true, 'a disk stays connected');
});
