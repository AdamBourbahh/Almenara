import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';
import {polygonToCells} from 'h3-js';
const root = new URL('../', import.meta.url);
const dir = await mkdtemp(new URL('../node_modules/.cutover-',import.meta.url));
after(()=>rm(dir,{recursive:true,force:true}));
async function compile(name, relative, enabled=false) {
 let source=await readFile(new URL(relative,root),'utf8');
 source=source.replaceAll('import.meta.env', JSON.stringify({VITE_ALLOW_SYNTHETIC_FALLBACK:enabled?'1':'0'}));
 source=source.replace('"../api/client"','"./client.mjs"');
 const file=join(dir,name+'.mjs');
 await writeFile(file,ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText);
 return import(pathToFileURL(file).href);
}
const client=await compile('client','src/api/client.ts');
const opted=await compile('opted','src/api/client.ts',true);
const store=await compile('store','src/store/useAnalysisStore.ts');
const regions=JSON.parse(await readFile(new URL('../../data/regions.json',import.meta.url),'utf8'));
test('real presets match populated registered regions and open Chilecito',()=>{
 assert.deepEqual(Object.keys(store.PRESET_REGIONS).sort(),['chilecito_la_rioja','iberia_med','orlando_florida','amazonas_manaus'].sort());
 for(const [key,p] of Object.entries(store.PRESET_REGIONS)) {
  const [w,s,e,n]=regions[key].bounds;
  assert.deepEqual(p.coordinates,[[[w,s],[e,s],[e,n],[w,n],[w,s]]]);
  assert.ok(polygonToCells(p.coordinates[0],7,true).length<250000);
 }
 assert.equal(store.useAnalysisStore.getState().selectedPreset,'chilecito_la_rioja');
});
test('backend provenance reaches both client operations and store',async()=>{
 for(const source of ['real','synthetic']) {
  globalThis.fetch=async()=>new Response(JSON.stringify({data_source:source,calendar_series:[],forecast_series:null}));
  assert.equal((await client.analyzeAoi({})).isSynthetic,source==='synthetic');
  assert.equal((await client.runChaosMonkey({})).isSynthetic,source==='synthetic');
  await store.useAnalysisStore.getState().executeAnalysis();
  assert.equal(store.useAnalysisStore.getState().isSynthetic,source==='synthetic');
 }
});
test('network and gateway failures surface unless fallback explicitly enabled',async()=>{
 const request={aoi:{type:'Polygon',coordinates:[[[-67.6,-29.3],[-67.5,-29.3],[-67.5,-29.2],[-67.6,-29.3]]]},start_year:2022,end_year:2022};
 for(const status of [0,500,503]) {
  globalThis.fetch=async()=>{if(!status)throw new TypeError('offline'); return new Response('{}',{status});};
  await assert.rejects(client.analyzeAoi(request));
  await assert.rejects(client.runChaosMonkey({...request,target_year:2022}));
 }
 globalThis.fetch=async()=>{throw new TypeError('offline');};
 const aoi={type:'Polygon',coordinates:[[[-67.6,-29.3],[-67.5,-29.3],[-67.5,-29.2],[-67.6,-29.3]]]};
 assert.equal((await opted.analyzeAoi({aoi,start_year:2022,end_year:2022})).data.data_source,'synthetic');
});
