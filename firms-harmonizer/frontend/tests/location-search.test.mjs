import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';
const source=await readFile(new URL('../src/components/Map/locationSearch.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {approvedRegion,locationBounds,searchLocations}=await import('data:text/javascript;base64,'+Buffer.from(js).toString('base64'));
const regions=[{label:'Iberia',bounds:[-9.5,36,4,44]},{label:'Orlando',bounds:[-82,28,-80.7,29.3]},
 {label:'Chilecito',bounds:[-69.5,-31,-65.5,-27.5]},{label:'Manaus',bounds:[-62,-5,-58,-1]}];
test('locations and coordinate selections are bounded to the four approved areas',()=>{
 assert.equal(approvedRegion(-3.7,40.4,regions).label,'Iberia');
 assert.equal(approvedRegion(2.35,48.86,regions),undefined);
 assert.equal(locationBounds(2.35,48.86,.2,regions),null);
 assert.deepEqual(locationBounds(3.99,43.99,.2,regions),[3.79,43.79,4,44]);
});
test('out-of-region and malformed provider results never appear, even if provider ignores bbox',async()=>{
 const calls=[];
 globalThis.fetch=async url=>{
  calls.push(new URL(url));
  return new Response(JSON.stringify({features:[
   {geometry:{coordinates:[-3.7,40.4]},properties:{name:'Madrid',country:'Spain'}},
   {geometry:{coordinates:[2.35,48.86]},properties:{name:'Paris'}},
   {geometry:{coordinates:['bad',40]},properties:{name:'Malformed'}},null]}));
 };
 const results=await searchLocations('Madrid',regions,new AbortController().signal);
 assert.equal(calls.length,4);
 assert.ok(calls.every((url,i)=>url.searchParams.get('bbox')===regions[i].bounds.join(',')));
 assert.deepEqual(results.map(x=>x.label),['Madrid, Spain']);
});
test('offline failure is explicit and an aborted search never supplies late results',async()=>{
 globalThis.fetch=async()=>{throw new TypeError('offline')};
 await assert.rejects(searchLocations('Madrid',regions,new AbortController().signal),/unavailable/);
 const controller=new AbortController();controller.abort();
 assert.deepEqual(await searchLocations('Madrid',regions,controller.signal),[]);
});
