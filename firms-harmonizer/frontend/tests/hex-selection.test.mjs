import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';
import {latLngToCell, gridDisk, polygonToCells, cellArea} from 'h3-js';

const dir = await mkdtemp(new URL('../node_modules/.hex-selection-', import.meta.url));
after(() => rm(dir, {recursive:true, force:true}));
const source = await readFile(new URL('../src/components/Map/hexSelection.ts', import.meta.url), 'utf8');
await writeFile(join(dir, 'hexSelection.mjs'), ts.transpileModule(source, {
  compilerOptions: {target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.ES2022}
}).outputText);
const {polygonFromHexagons, hexagonsInView, selectedHexagonArea, MAX_SELECTED_HEXAGONS} =
  await import(pathToFileURL(join(dir, 'hexSelection.mjs')).href);

for (const [name,lat,lon] of [['Chilecito',-29.25,-67.5],['Iberia',40.4,-4.5],['Orlando',28.65,-81.35],['Manaus',-3.1,-60]]) {
  test(`${name}: the polygon contains exactly the selected cells and excludes an unselected hole`, () => {
    const center = latLngToCell(lat,lon,7);
    const cells = gridDisk(center,2).filter(cell=>cell!==center);
    const polygon = polygonFromHexagons(cells);
    assert.equal(polygon.coordinates.length,2);
    assert.deepEqual(polygonToCells(polygon.coordinates,7,true).sort(),cells.sort());
    assert(!polygonToCells(polygon.coordinates,7,true).includes(center));
  });
}

test('single cell and duplicate input retain exact selection and area', () => {
  const cell = latLngToCell(40.4,-4.5,7);
  const polygon = polygonFromHexagons([cell,cell]);
  assert.deepEqual(polygonToCells(polygon.coordinates,7,true),[cell]);
  assert.equal(selectedHexagonArea([cell,cell]),cellArea(cell,'km2'));
});

test('separate groups, invalid cells and over-limit selections are rejected instead of bridged', () => {
  assert.throws(()=>polygonFromHexagons([]),/at least one/);
  assert.throws(()=>polygonFromHexagons(['not-a-cell']),/resolution 7/);
  assert.throws(()=>polygonFromHexagons([latLngToCell(40.4,-4.5,4)]),/resolution 7/);
  assert.throws(()=>polygonFromHexagons([latLngToCell(40.4,-4.5,7),latLngToCell(41.4,-4.5,7)]),/connected/);
  const cells = gridDisk(latLngToCell(40.4,-4.5,7),10).slice(0,MAX_SELECTED_HEXAGONS+1);
  assert.throws(()=>polygonFromHexagons(cells),/at most/);
});

test('grid generation refuses overview and malformed bounds before expensive filling', () => {
  assert.deepEqual(hexagonsInView(-180,-85,180,85),[]);
  assert.deepEqual(hexagonsInView(179,-1,-179,1),[]);
  assert.deepEqual(hexagonsInView(NaN,40,-4,41),[]);
  const cells=hexagonsInView(-4.6,40.3,-4.4,40.5);
  assert(cells.length>0 && cells.length<=6000);
});
