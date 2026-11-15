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
 source=source.replace(/import regionRegistry from [^;]+;/, 'const regionRegistry = '+await readFile(new URL('../../data/regions.json', import.meta.url),'utf8')+';');
 source=source.replaceAll('import.meta.env', JSON.stringify({VITE_ALLOW_SYNTHETIC_FALLBACK:enabled?'1':'0'}));
 source=source.replace('"../api/client"','"./client.mjs"').replaceAll('"./synthetic"','"./synthetic.mjs"');
 const file=join(dir,name+'.mjs');
 await writeFile(file,ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText);
 return import(pathToFileURL(file).href);
}
await compile('synthetic','src/api/synthetic.ts');
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

test('selected year loads distinct annual hexagons, caches them, and keeps full history',async()=>{
 const state=store.useAnalysisStore;
 const history={data_source:'real',calendar_series:[],forecast_series:null,map_hexagons:[]};
 state.setState({analysisData:history,loading:false,selectedYear:2022});
 const requested=[];
 globalThis.fetch=async(_url,options)=>{
  const body=JSON.parse(options.body);requested.push(body);
  return new Response(JSON.stringify({...history,map_hexagons:[{h3_index:'872830828ffffff',mean_annual_fre:body.start_year,raw_pixel_count:body.start_year}]}));
 };
 state.getState().setSelectedYear(2005);
 await new Promise(resolve=>setTimeout(resolve,350));
 assert.equal(state.getState().mapYear,2005);
 assert.equal(state.getState().mapHexagons[0].mean_annual_fre,2005);
 assert.equal(requested[0].start_year,requested[0].end_year);
 assert.equal(state.getState().analysisData,history);
 state.getState().setSelectedYear(2023);
 await new Promise(resolve=>setTimeout(resolve,350));
 assert.equal(state.getState().mapHexagons[0].mean_annual_fre,2023);
 state.getState().setSelectedYear(2005);
 await new Promise(resolve=>setTimeout(resolve,350));
 assert.equal(state.getState().mapYear,2005);
 assert.equal(requested.length,2);
});

test('late annual responses cannot overwrite the newly selected year and errors remain visible',async()=>{
 const state=store.useAnalysisStore;
 state.setState({loading:false,selectedYear:2007});
 let resolveOld;
 globalThis.fetch=()=>new Promise(resolve=>{resolveOld=resolve;});
 const old=state.getState().loadMapYear();
 state.setState({selectedYear:2008});
 globalThis.fetch=async()=>new Response(JSON.stringify({data_source:'real',map_hexagons:[{mean_annual_fre:800}]}));
 await state.getState().loadMapYear();
 resolveOld(new Response(JSON.stringify({data_source:'real',map_hexagons:[{mean_annual_fre:700}]})));
 await old;
 assert.equal(state.getState().mapYear,2008);
 assert.equal(state.getState().mapHexagons[0].mean_annual_fre,800);
 state.setState({selectedYear:2009});
 globalThis.fetch=async()=>{throw new TypeError('offline');};
 await state.getState().loadMapYear();
 // A failed period keeps the last rendered map so the view does not go blank.
 assert.equal(state.getState().mapYear,2008);
 assert.equal(state.getState().mapHexagons[0].mean_annual_fre,800);
 assert.equal(state.getState().mapLoading,false);
 assert.equal(state.getState().mapError,'offline');
});

test('mapped energy integrates exact cell areas and applies the same visible-cell filter',async()=>{
 const {summarizeMappedYear,colorIntensity}=await compile('mapMetrics','src/components/Map/mapMetrics.ts');
 const {cellArea,UNITS}=await import('h3-js');
 const a={h3_index:'87390c014ffffff',mean_annual_fre:1000,raw_pixel_count:3,is_industrial_site:false};
 const b={h3_index:'872830828ffffff',mean_annual_fre:2000,raw_pixel_count:7,is_industrial_site:true};
 const result=summarizeMappedYear([a,b],true);
 assert.deepEqual(result.hexagons,[a]);
 assert.equal(result.detections,3);
 assert.ok(Math.abs(result.energyGJ-cellArea(a.h3_index,UNITS.km2))<1e-9);
 const all=summarizeMappedYear([a,b],false);
 assert.equal(all.detections,10);
 assert.ok(Math.abs(all.energyGJ-(cellArea(a.h3_index,UNITS.km2)+2*cellArea(b.h3_index,UNITS.km2)))<1e-9);
 assert.deepEqual(summarizeMappedYear([],true),{hexagons:[],detections:0,energyGJ:0,footprintKm2:0});
 assert.ok(colorIntensity(100,1000)<colorIntensity(900,1000));
 assert.ok(colorIntensity(10000,26000)<colorIntensity(20000,26000));
});


test('research CSV uses a real UTF-8 BOM and leaves unknown physical estimates blank',async()=>{
 const previousDocument=globalThis.document;
 const previousCreate=URL.createObjectURL;
 const previousRevoke=URL.revokeObjectURL;
 let blob;
 globalThis.document={body:{appendChild(){},removeChild(){}},createElement(){return {click(){}};}};
 URL.createObjectURL=(value)=>{blob=value;return 'blob:test';};
 URL.revokeObjectURL=()=>{};
 try {
  client.exportToIpccCsv({query_hash:'audit',forecast_series:null,calendar_series:[{
   date:'2024-01-01',year:2024,doy:1,raw_hotspot_count:0,raw_frp_mw:0,
   observation_status:'unknown',harmonized_fre_mj_km2:0,biomass_burned_tonnes:0,
   active_sensors:[],is_gap_filled:false,is_forecast:false,pm25_emitted_kg:null
  }]});
  const text=await blob.text();
  assert.equal(new Uint8Array(await blob.arrayBuffer()).slice(0,3).join(','),'239,187,191');
  assert.ok(!text.startsWith('???'));
  const [header,row]=text.replace(/^\uFEFF/,'').split('\r\n').map(line=>line.split(','));
  assert.equal(row[header.indexOf('Harmonized FRE (MJ/km2)')],'');
  assert.equal(row[header.indexOf('Biomass Burned (kt)')],'');
  assert.equal(row[header.indexOf('Observation Status')],'unknown');
 } finally {
  globalThis.document=previousDocument;URL.createObjectURL=previousCreate;URL.revokeObjectURL=previousRevoke;
 }
});
