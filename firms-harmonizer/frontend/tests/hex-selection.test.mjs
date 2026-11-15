import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';
import {latLngToCell, gridDisk, gridRing, gridPathCells, cellToLatLng, polygonToCells, cellArea} from 'h3-js';

const dir = await mkdtemp(new URL('../node_modules/.hex-selection-', import.meta.url));
after(() => rm(dir, {recursive:true, force:true}));
const source = await readFile(new URL('../src/components/Map/hexSelection.ts', import.meta.url), 'utf8');
await writeFile(join(dir, 'hexSelection.mjs'), ts.transpileModule(source, {
  compilerOptions: {target:ts.ScriptTarget.ES2022, module:ts.ModuleKind.ES2022}
}).outputText);
const {polygonFromHexagons, hexagonsInView, selectedHexagonArea, MAX_SELECTED_HEXAGONS,
  fillHexagonPerimeter, paintHexagons, hexagonsAlongPointerSegment} =
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

for (const [name,lat,lon] of [['Chilecito',-29.25,-67.5],['Iberia',40.4,-4.5],['Orlando',28.65,-81.35],['Manaus',-3.1,-60]]) {
  test(`${name}: Fill adds only the enclosed cells and an open perimeter cannot fill`, () => {
    const center=latLngToCell(lat,lon,7),ring=gridRing(center,2);
    assert.deepEqual(fillHexagonPerimeter(ring),gridDisk(center,2).sort());
    assert.throws(()=>fillHexagonPerimeter(ring.slice(1)),/Close a perimeter/);
    assert.equal(polygonFromHexagons(fillHexagonPerimeter(ring)).coordinates.length,1);
  });
}

test('Fill retains concave exterior bays rather than filling the convex hull', () => {
  const left=latLngToCell(40.4,-4.5,7),right=gridRing(left,5)[0];
  const perimeter=[...new Set([...gridRing(left,1),...gridRing(right,1),...gridPathCells(left,right).slice(1,-1)])];
  const expected=[...new Set([...perimeter,left,right])].sort();
  assert.deepEqual(fillHexagonPerimeter(perimeter),expected);
});

test('oversized Fill is rejected atomically and cannot add cells outside a disconnected selection', () => {
  const center=latLngToCell(40.4,-4.5,7),ring=gridRing(center,10),before=[...ring];
  assert.throws(()=>fillHexagonPerimeter(ring),/exceed.*256/);
  assert.deepEqual(ring,before);
  assert.throws(()=>fillHexagonPerimeter([...gridRing(center,1),latLngToCell(41.4,-4.5,7)]),/separate groups/);
});

test('paint/erase revisits are idempotent and a full selection retains its existing cells', () => {
  const cells=gridDisk(latLngToCell(40.4,-4.5,7),10);
  assert.deepEqual(paintHexagons([cells[0]],[cells[1],cells[0],cells[1]],true),[cells[0],cells[1]]);
  assert.deepEqual(paintHexagons([cells[0],cells[1]],[cells[0],cells[0]],false),[cells[1]]);
  assert.deepEqual(paintHexagons(cells.slice(0,MAX_SELECTED_HEXAGONS),cells,true),cells.slice(0,MAX_SELECTED_HEXAGONS));
});

test('a fast pointer segment includes intermediate cells, not only its endpoints', () => {
  const start=[0,0],end=[1000,0];
  const unproject=([x])=>[-4.6+x*.0002,40.4];
  const cells=hexagonsAlongPointerSegment(start,end,unproject);
  assert(cells.length>5);
  for (const x of [0,200,400,600,800,1000]) {
    const [lon,lat]=unproject([x,0]);
    assert(cells.includes(latLngToCell(lat,lon,7)));
  }
  for (let i=1;i<cells.length;i++) assert(gridDisk(cells[i-1],1).includes(cells[i]));
  const first=cellToLatLng(cells[0]);
  assert.deepEqual(hexagonsAlongPointerSegment(start,start,()=>[first[1],first[0]]),[cells[0]]);
});
