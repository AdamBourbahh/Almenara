import assert from 'node:assert/strict';
import {after, afterEach, before, test} from 'node:test';
import {writeFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {chromium} from 'playwright';

const requireFrontend=createRequire(new URL('../frontend/package.json',import.meta.url));
const {cellToLatLng}=requireFrontend('h3-js');
const origin=process.env.COPILOT_BROWSER_URL ?? 'http://127.0.0.1:15173';
const output=new URL('../../docs/verification/2026-11-15-copilot-quality/',import.meta.url);
let browser,page,lastMap;
const requests=[],responses=[],records=[],external=[];
before(async()=>{
  await mkdir(output,{recursive:true});
  browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH ?? '/usr/bin/chromium',headless:true,
    args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  await page.addInitScript(()=>Object.defineProperty(navigator,'onLine',{get:()=>false}));
  page.on('request',request=>{
    const url=new URL(request.url());
    if(!['127.0.0.1','localhost'].includes(url.hostname)) external.push(request.url());
    if(url.pathname.startsWith('/api/')) requests.push({url:request.url(),body:request.postDataJSON()});
  });
  page.on('response',async response=>{
    if(response.url().includes('/api/map-period')) {
      try {lastMap=await response.json();} catch {}
    }
    if(response.url().includes('/api/explain-spike')||response.url().endsWith('/api/analyze')) {
      try {
        const body=await response.json();
        responses.push({url:response.url(),body:response.url().endsWith('/api/analyze') ? {
          data_source:body.data_source,query_hash:body.query_hash,aoi_area_km2:body.aoi_area_km2,
          calendar_days:body.calendar_series.length,first_date:body.calendar_series[0]?.date,
          last_date:body.calendar_series.at(-1)?.date,map_hexagons:body.map_hexagons.length
        } : body});
      } catch {}
    }
  });
  await page.goto(origin);
  await page.getByRole('button',{name:'Choose dates',exact:true}).waitFor({timeout:60000});
  await page.waitForFunction(()=>!document.querySelector('[aria-label="Choose dates"]')?.disabled,{timeout:60000});
});
afterEach(async context=>{
  records.push({case:context.name,result:context.passed?'passed':'failed',requests:requests.splice(0),responses:responses.splice(0)});
});
after(async()=>{
  await page.screenshot({path:new URL('browser-final.png',output).pathname});
  await writeFile(new URL('browser.json',output),JSON.stringify({records,external_requests:external},null,2));
  await browser.close();
});
async function picker(mode,start,end){
  await page.getByRole('button',{name:'Choose dates',exact:true}).click();
  await page.getByRole('button',{name:mode,exact:true}).click();
  await page.getByLabel(mode==='Year'?'Choose year':mode==='Month'?'Choose month':mode==='Day'?'Choose day':'Start date',{exact:true}).fill(start);
  if(end) await page.getByLabel('End date',{exact:true}).fill(end);
}
async function apply(){await page.getByRole('button',{name:'Apply dates',exact:true}).click();}
async function openChat(){
  if(!await page.getByLabel('Fire AI Copilot',{exact:true}).count()) await page.getByRole('button',{name:'Fire Copilot',exact:true}).click();
}
async function closeChat(){if(await page.getByTitle('Close Copilot',{exact:true}).count()) await page.getByTitle('Close Copilot',{exact:true}).click();}
async function ask(question){
  await openChat();
  const response=page.waitForResponse(r=>r.url().includes('/api/explain-spike')&&r.request().method()==='POST',{timeout:60000});
  await page.getByLabel('Question for Fire Copilot',{exact:true}).fill(question);
  await page.getByTitle('Send question',{exact:true}).click();
  const received=await response;
  assert.equal(received.status(),200);
  const request=received.request().postDataJSON(),body=await received.json();
  assert.equal(body.data_source,'real');
  await page.waitForFunction(()=>!document.querySelector('[aria-label="Question for Fire Copilot"]')?.disabled);
  return {request,body};
}
async function searchCoordinates(lat,lon){
  await closeChat();
  const analysis=page.waitForResponse(r=>r.url().endsWith('/api/analyze')&&r.request().method()==='POST',{timeout:60000});
  const search=page.getByLabel('Search locations within the four approved regions',{exact:true});
  await search.fill(`${lat}, ${lon}`);await search.press('Enter');
  assert.equal((await analysis).status(),200);
  await page.waitForFunction(()=>!document.querySelector('[aria-label="Choose dates"]')?.disabled,{timeout:60000});
}

test('browser loads real history in offline mode without any external request',async()=>{
  await page.getByText('Source: local FIRMS observations',{exact:true}).waitFor();
  assert.ok(responses.some(r=>r.body.data_source==='real'&&r.body.calendar_days>9000));
  assert.deepEqual(external,[]);
});
test('partial year entry remains editable and Cancel preserves the applied year',async()=>{
  const before=await page.getByLabel('Timeline selection',{exact:true}).innerText();
  await picker('Year','20');
  assert.equal(await page.getByLabel('Choose year',{exact:true}).inputValue(),'20');
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  assert.equal(await page.getByLabel('Timeline selection',{exact:true}).innerText(),before);
  await picker('Year','2024');await apply();
  assert.equal(await page.getByLabel('Timeline selection',{exact:true}).innerText(),'2024');
});
test('leap-day selection reaches the backend with exactly one UTC date',async()=>{
  await picker('Day','2024-02-29');await apply();
  const {request,body}=await ask('How many detections here?');
  assert.equal(request.period_start,'2024-02-29');assert.equal(request.period_end,'2024-02-29');
  assert.equal(body.map_context.period_start,'2024-02-29');
});
test('inclusive cross-year selection drives both yearly map requests and the same chat interval',async()=>{
  await closeChat();await picker('Date range','2025-12-31','2026-01-02');await apply();
  const {request,body}=await ask('How much energy in GJ here?');
  assert.equal(request.period_start,'2025-12-31');assert.equal(request.period_end,'2026-01-02');
  assert.equal(body.map_context.period_start,request.period_start);assert.equal(body.map_context.period_end,request.period_end);
  const urls=requests.filter(r=>r.url.includes('map-period')).map(r=>new URL(r.url));
  assert.ok(urls.some(u=>u.searchParams.get('start_date')==='2025-12-31'&&u.searchParams.get('end_date')==='2025-12-31'));
  assert.ok(urls.some(u=>u.searchParams.get('start_date')==='2026-01-01'&&u.searchParams.get('end_date')==='2026-01-02'));
});
test('a reversed range is visibly rejected and leaves the applied interval intact',async()=>{
  await closeChat();const before=await page.getByLabel('Timeline selection',{exact:true}).innerText();
  await picker('Date range','2026-07-25','2026-07-23');
  assert.equal(await page.getByRole('button',{name:'Apply dates',exact:true}).isDisabled(),true);
  assert.match(await page.getByRole('alert').innerText(),/end date on or after/);
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  assert.equal(await page.getByLabel('Timeline selection',{exact:true}).innerText(),before);
});
test('removing context stops geometry, dates and prior context from reaching the API',async()=>{
  await openChat();await page.getByRole('button',{name:'Remove map context',exact:true}).click();
  const {request}=await ask('How many detections?');
  assert.equal(request.aoi,null);assert.equal(request.period_start,null);assert.equal(request.period_end,null);
  assert.equal(request.previous_context,null);assert.deepEqual(request.conversation,[]);
});
test('an explicit new day reattaches context and excludes the previous interval history',async()=>{
  await closeChat();await picker('Day','2026-07-24');await apply();
  const {request}=await ask('How many detections here?');
  assert.equal(request.period_start,'2026-07-24');assert.deepEqual(request.conversation,[]);
});
test('changing the area preserves the chosen date and sends the new polygon',async()=>{
  await searchCoordinates(40.4,-4.3);
  const {request,body}=await ask('How many detections here?');
  assert.equal(request.period_start,'2026-07-24');assert.deepEqual(request.conversation,[]);
  assert.ok(request.aoi.coordinates[0].every(([lon,lat])=>lon>=-4.51&&lon<=-4.09&&lat>=40.19&&lat<=40.61));
  assert.deepEqual(body.map_context.aoi,request.aoi);
});
test('clicking a real rendered hex attaches its exact H3 index and date',async()=>{
  await closeChat();
  await page.waitForFunction(()=>!document.body.innerText.includes('Loading 2026-07-24'));
  assert.ok(lastMap?.map_hexagons?.length);
  const target=lastMap.map_hexagons.find(h=>h.raw_pixel_count>0&&h.mean_annual_fre>0);
  const [lat,lon]=cellToLatLng(target.h3_index);
  await searchCoordinates(lat,lon);
  const box=await page.locator('[data-map-viewport]').boundingBox();
  await page.mouse.click(box.x+box.width/2,box.y+box.height/2);
  await page.getByLabel('Added map context',{exact:true}).waitFor({timeout:15000});
  const {request,body}=await ask('How many detections in this hexagon?');
  assert.equal(request.selected_hex.h3_index,target.h3_index);
  assert.equal(body.map_context.h3_index,target.h3_index);
  assert.equal(request.period_start,'2026-07-24');
});
test('clearing chat removes prior messages and a fresh question carries no hidden conversation',async()=>{
  await page.getByTitle('Clear chat history',{exact:true}).click();
  const {request}=await ask('What is FRP?');
  assert.deepEqual(request.conversation,[]);assert.equal(request.previous_context,null);
  assert.equal(await page.getByText('Error running copilot',{exact:true}).count(),0);
  assert.deepEqual(external,[]);
});
