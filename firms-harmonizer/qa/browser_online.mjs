import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {chromium} from 'playwright';

const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH ?? '/usr/bin/chromium',headless:true,
  args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  // Keep the basemap local while this separate run exercises the online Copilot.
  await page.addInitScript(()=>Object.defineProperty(navigator,'onLine',{get:()=>false}));
  await page.goto(process.env.COPILOT_BROWSER_URL ?? 'http://127.0.0.1:15173');
  await page.waitForFunction(()=>!document.querySelector('[aria-label="Choose dates"]')?.disabled,{},{timeout:60000});
  const loaded=page.waitForResponse(r=>r.url().endsWith('/api/analyze')&&r.request().method()==='POST');
  await page.getByLabel('Search locations within the four approved regions').fill('40.4, -4.3');
  await page.getByLabel('Search locations within the four approved regions').press('Enter');
  assert.equal((await loaded).status(),200);
  await page.getByRole('button',{name:'Choose dates',exact:true}).click();
  await page.getByRole('button',{name:'Day',exact:true}).click();
  await page.getByLabel('Choose day',{exact:true}).fill('2026-07-24');
  await page.getByRole('button',{name:'Apply dates',exact:true}).click();
  await page.getByRole('button',{name:'Fire Copilot',exact:true}).click();
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/explain-spike')&&r.request().method()==='POST',{timeout:60000});
  await page.getByLabel('Question for Fire Copilot').fill('how much energy in GJ was released here?');
  await page.getByTitle('Send question',{exact:true}).click();
  const response=await pending,body=await response.json(),request=response.request().postDataJSON();
  assert.equal(response.status(),200);assert.equal(body.data_source,'real');
  assert.match(body.model_used,/^(?:gemini|groq)-agent\//);
  assert.equal(request.period_start,'2026-07-24');assert.equal(body.map_context.period_start,request.period_start);
  assert.deepEqual(body.map_context.aoi,request.aoi);
  await page.waitForFunction(()=>!document.querySelector('[aria-label="Question for Fire Copilot"]')?.disabled);
  const directory=new URL('../../docs/verification/2026-11-15-copilot-quality/',import.meta.url);
  await page.screenshot({path:new URL('browser-online.png',directory).pathname});
  await writeFile(new URL('browser-online.json',directory),JSON.stringify({request,response:body,result:'passed',
    expected:{data_source:'real',selected_day:'2026-07-24'},criterion:'Actual browser to HTTP API to the configured provider; exact selected geometry/date and real provenance'},null,2));
  console.log(body.model_used,body.data_source,body.explanation_markdown.slice(0,150));
} finally {
  await browser.close();
}
