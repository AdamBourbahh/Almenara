import assert from 'node:assert/strict';
import {test, after} from 'node:test';
import {readFile, writeFile, mkdtemp, rm} from 'node:fs/promises';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import ts from 'typescript';

const dir=await mkdtemp(new URL('../node_modules/.period-',import.meta.url));
after(()=>rm(dir,{recursive:true,force:true}));
for(const [name,path] of [['client','api/client'],['store','store/useAnalysisStore']]) {
 let source=await readFile(new URL(`../src/${path}.ts`,import.meta.url),'utf8');
 source=source.replaceAll('import.meta.env','{}').replace('"../api/client"','"./client.mjs"');
 await writeFile(join(dir,`${name}.mjs`),ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText);
}
const {useAnalysisStore:state}=await import(pathToFileURL(join(dir,'store.mjs')).href);
const pause=()=>new Promise(resolve=>setTimeout(resolve,250));
const history={data_source:'real',calendar_series:[],forecast_series:null,map_hexagons:[]};

test('day/month selection loads exact spatial periods, reuses cache and keeps full history',async()=>{
 state.setState({analysisData:history,loading:false,selectedYear:2020,selectedDate:null,selectedMonth:null});
 const calls=[];
 globalThis.fetch=async(url,options)=>{
  const u=new URL(url, "http://localhost");calls.push({u,body:JSON.parse(options.body)});
  return new Response(JSON.stringify({data_source:'real',map_hexagons:[{mean_annual_fre:calls.length}]}));
 };
 state.getState().setSelectedMonth(2);
 await pause();
 assert.equal(calls[0]?.u.pathname,'/api/map-period');
 assert.equal(calls[0].u.searchParams.get('start_date'),'2020-02-01');
 assert.equal(calls[0].u.searchParams.get('end_date'),'2020-02-29');
 assert.equal(state.getState().mapPeriod,'2020-02');
 state.getState().setSelectedDate('2020-02-29');
 await pause();
 assert.equal(calls[1].u.searchParams.get('start_date'),'2020-02-29');
 assert.equal(calls[1].u.searchParams.get('end_date'),'2020-02-29');
 assert.equal(state.getState().mapPeriod,'2020-02-29');
 assert.equal(state.getState().analysisData,history);
 state.getState().setSelectedMonth(2);
 await pause();
 assert.equal(calls.length,2);
 assert.equal(state.getState().mapHexagons[0].mean_annual_fre,1);
});

test('late daily responses cannot replace a newer day, and empty days clear the map',async()=>{
 state.setState({selectedDate:'2020-03-01',selectedMonth:3});
 let resolveOld;
 globalThis.fetch=()=>new Promise(resolve=>{resolveOld=resolve;});
 const old=state.getState().loadMapYear();
 state.setState({selectedDate:'2020-03-02'});
 globalThis.fetch=async()=>new Response(JSON.stringify({data_source:'real',map_hexagons:[]}));
 await state.getState().loadMapYear();
 resolveOld(new Response(JSON.stringify({data_source:'real',map_hexagons:[{mean_annual_fre:99}]})));
 await old;
 assert.equal(state.getState().mapPeriod,'2020-03-02');
 assert.deepEqual(state.getState().mapHexagons,[]);
 assert.equal(state.getState().mapLoading,false);
 state.setState({selectedDate:'2020-03-03'});
 globalThis.fetch=async()=>{throw new TypeError('offline');};
 await state.getState().loadMapYear();
 assert.equal(state.getState().mapError,'offline');
 assert.deepEqual(state.getState().mapHexagons,[]);
});

test('risk forecast follows day, month and year and keeps the date when the area changes', async () => {
 const store = state.getState();
 const dates = [];
 const calendar = [{date:'2001-01-01',year:2001,doy:1},{date:'2026-11-14',year:2026,doy:318}];
 globalThis.fetch = async (url, options) => {
  const path = new URL(url, 'http://localhost').pathname;
  if (path === '/api/predict-risk') {
   dates.push(JSON.parse(options.body).as_of_date);
   return new Response(JSON.stringify({data_source:'real',assessment:null}));
  }
  return new Response(JSON.stringify({...history,calendar_series:calendar}));
 };
 state.setState({selectedYear:2020,selectedMonth:2,selectedDate:null});
 await store.fetchRiskPredictionForAoi();
 state.setState({selectedMonth:null});
 await store.fetchRiskPredictionForAoi();
 state.setState({selectedDate:'2020-02-17',selectedMonth:2});
 await store.loadPresetRegion('iberia_med');
 await store.fetchRiskPredictionForAoi();
 await pause();
 assert.deepEqual(dates, ['2020-02-29','2020-12-31','2020-02-17']);
});
