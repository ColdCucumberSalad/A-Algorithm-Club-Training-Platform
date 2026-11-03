// Run with: node tests/poker-ui.browser.mjs (see docs/poker-ui.md).
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../.local/poker-ui/node_modules/playwright');
import fs from 'node:fs';
import assert from 'node:assert/strict';
const output='output/playwright/poker-realistic';fs.mkdirSync(output,{recursive:true});
const repo = fileURLToPath(new URL('../', import.meta.url));
const allowed = new Set(['/tests/fixtures/poker-ui.html','/tests/fixtures/poker-ui.js','/poker.js','/poker.css','/styles.css','/extensions.css','/static/vendor/daisyui/poker-components.css']);
const server = createServer((request, response) => {
  const pathname = new URL(request.url, 'http://localhost').pathname;
  if (pathname === '/favicon.ico') { response.writeHead(204); response.end(); return; }
  if (!allowed.has(pathname)) { response.writeHead(404); response.end(); return; }
  const file = path.join(repo, pathname);
  response.setHeader('Content-Type', pathname.endsWith('.js') ? 'text/javascript; charset=utf-8' : pathname.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/html; charset=utf-8');
  fs.createReadStream(file).on('error', () => {response.writeHead(404);response.end();}).pipe(response);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const fixtureUrl = `http://127.0.0.1:${server.address().port}/tests/fixtures/poker-ui.html`;
const browser=await chromium.launch({headless:true});
try {
const results=[];
async function makePage(width,height,reducedMotion='no-preference',mobile=false,nativeMobile=false){
  const page=await browser.newPage({viewport:{width,height},reducedMotion,hasTouch:mobile,isMobile:mobile});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
  await page.addInitScript(()=>{window.motionEvents=[];const original=Element.prototype.animate;Element.prototype.animate=function(frames,options){window.motionEvents.push({className:this.className,options,frames});return original.call(this,frames,options);};});
  if(mobile&&!nativeMobile) await page.addInitScript(()=>{Element.prototype.requestFullscreen=()=>Promise.reject(new Error('Test unsupported native fullscreen'));});
  if(nativeMobile) await page.addInitScript(()=>{window.orientationCalls=[];screen.orientation.lock=async value=>window.orientationCalls.push(value);screen.orientation.unlock=()=>window.orientationCalls.push('unlock');});
  await page.goto(fixtureUrl);
  await page.locator('[data-action=ready]').waitFor();
  return {page,errors};
}
{
  const {page,errors}=await makePage(844,390,'no-preference',true,true);
  await page.locator('[data-fullscreen]').click();
  await page.waitForFunction(()=>document.fullscreenElement===document.querySelector('#pokerView')&&window.orientationCalls.includes('landscape'));
  await page.evaluate(()=>document.exitFullscreen());
  await page.waitForFunction(()=>!document.querySelector('#pokerView').classList.contains('poker-fullscreen'));
  assert.ok(await page.evaluate(()=>window.orientationCalls.includes('unlock')));
  assert.deepEqual(errors,[]);results.push({scenario:'native phone fullscreen requests landscape and browser exit releases orientation',errors});await page.close();
}
{
  const {page,errors}=await makePage(1440,900);
  await page.locator('[data-action=ready]').click();
  await page.locator('[data-fullscreen]').click();
  await page.waitForFunction(()=>document.fullscreenElement===document.querySelector('#pokerView'));
  await page.waitForTimeout(500);
  const geometry=await page.evaluate(()=>{
    const table=document.querySelector('.poker-table').getBoundingClientRect(), controls=document.querySelector('.poker-controls').getBoundingClientRect();
    return {tableHeight:table.height,controlsBottom:controls.bottom,height:innerHeight,controlsTop:controls.top,tableBottom:table.bottom,rootClass:document.querySelector('#pokerView').className,tablePosition:getComputedStyle(document.querySelector('.poker-table')).position,controlsPosition:getComputedStyle(document.querySelector('.poker-controls')).position};
  });
  assert.ok(geometry.controlsBottom<=geometry.height&&geometry.tableHeight>300);
  assert.ok(geometry.controlsTop>=geometry.tableBottom-1,JSON.stringify(geometry));
  await page.screenshot({path:`${output}/fullscreen-desktop.png`});
  await page.locator('[data-raise]').fill('180');
  await page.evaluate(()=>{const room=PokerPreview.room;room.pot+=5;PokerPreview.setRoom(room);});
  await page.waitForTimeout(1700);
  assert.equal(await page.locator('[data-raise]').inputValue(),'180');
  assert.ok(await page.evaluate(()=>document.fullscreenElement===document.querySelector('#pokerView')));
  for(const [width,height] of [[1440,720],[3840,2160]]){
    await page.locator('[data-fullscreen]').click();
    await page.waitForFunction(()=>!document.fullscreenElement);
    await page.waitForTimeout(150);
    await page.setViewportSize({width,height});await page.waitForTimeout(150);
    await page.locator('[data-fullscreen]').click();
    await page.waitForFunction(()=>document.fullscreenElement===document.querySelector('#pokerView'));
    assert.ok(await page.evaluate(()=>{const r=document.querySelector('.poker-controls').getBoundingClientRect(),table=document.querySelector('.poker-table').getBoundingClientRect();return r.bottom<=innerHeight&&r.top>=table.bottom-1&&table.height>300;}));
  }
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>!document.querySelector('#pokerView').classList.contains('poker-fullscreen'));
  await page.locator('[data-fullscreen]').focus();await page.keyboard.press('f');
  await page.waitForFunction(()=>document.querySelector('#pokerView').classList.contains('poker-fullscreen'));
  await page.evaluate(()=>PokerModule.close());
  await page.waitForFunction(()=>!document.fullscreenElement&&!document.body.classList.contains('poker-fullscreen-page'));
  assert.deepEqual(errors,[]);results.push({scenario:'native desktop fullscreen includes controls, polling, Escape/F and cleanup',geometry,errors});await page.close();
}
for(const [width,height] of [[390,844],[844,390],[667,375]]){
  const {page,errors}=await makePage(width,height,'no-preference',true);
  await page.locator('[data-fullscreen]').click();
  await page.waitForFunction(()=>document.querySelector('#pokerView').classList.contains('poker-fullscreen-mobile'));
  await page.locator('[data-action=ready]').click();
  await page.locator('[data-action=raise]').waitFor();
  await page.waitForTimeout(600);
  assert.equal(await page.locator('[data-raise]').getAttribute('placeholder'),'加注');
  assert.equal(await page.locator('[data-raise]').inputValue(),'40');
  assert.equal(await page.locator('.poker-raise-presets').isVisible(),false);
  assert.equal(await page.locator('[data-raise-range]').count(),0);
  assert.ok(await page.locator('[data-exit-fullscreen]').isVisible());
  const geometry=await page.evaluate(()=>{
    const screen=document.querySelector('.poker-room-screen'),table=document.querySelector('.poker-table'),controls=document.querySelector('.poker-controls');
    return {width:screen.clientWidth,height:screen.clientHeight,tableWidth:table.clientWidth,controlsWidth:controls.offsetWidth,controlsRight:controls.offsetLeft+controls.offsetWidth,exitX:document.querySelector('[data-exit-fullscreen]').offsetLeft,exitY:document.querySelector('[data-exit-fullscreen]').offsetTop,buttons:[...document.querySelectorAll('.poker-action-buttons > button, .poker-raise-control')].map(x=>({x:x.offsetLeft,y:x.offsetTop,height:x.offsetHeight}))};
  });
  assert.ok(geometry.width>geometry.height);
  assert.ok(geometry.controlsRight<=geometry.width&&geometry.exitX<30&&geometry.exitY<30);
  assert.ok(geometry.controlsWidth<=72,'phone controls should occupy a single narrow rail');
  assert.equal(await page.locator('[data-action=fold]').evaluate(el=>getComputedStyle(el).writingMode),'vertical-rl');
  assert.ok(await page.locator('.poker-mobile-status').evaluate(el=>el.parentElement.classList.contains('poker-room-screen')));
  assert.equal(await page.locator('.poker-controls .poker-control-info').count(),0);
  assert.ok(await page.locator('.poker-mobile-status').evaluate(el=>el.offsetLeft<30));
  assert.equal(await page.locator('[data-drawer-toggle] span').count(),0);
  await page.locator('[data-drawer-toggle]').click();
  assert.ok(await page.locator('.poker-mobile-tools').evaluate(el=>el.parentElement.classList.contains('poker-table')));
  await page.locator('[data-sound]').click();
  assert.equal(await page.locator('[data-sound]').getAttribute('aria-pressed'),'true');
  await page.locator('[data-help]').click();
  assert.ok(await page.locator('.poker-room-help').isVisible());
  await page.locator('[data-help]').click();
  await page.locator('[data-drawer-toggle]').click();
  assert.ok(geometry.buttons.every((b,i)=>b.height>=44&&(!i||b.y>geometry.buttons[i-1].y)));
  assert.equal(geometry.tableWidth,geometry.width,'floating controls must not reserve table width');
  await page.screenshot({path:`${output}/fullscreen-phone-${width}.png`});
  await page.locator('[data-drawer-toggle]').click();
  assert.equal(await page.locator('.poker-controls').evaluate(el=>el.inert),true);
  const expandedTable=await page.locator('.poker-table').evaluate(el=>el.clientWidth);
  assert.equal(expandedTable,geometry.tableWidth,'opening or closing the drawer must keep table width stable');
  await page.evaluate(()=>{const room=PokerPreview.room;room.pot+=5;PokerPreview.setRoom(room);});
  await page.waitForTimeout(1700);
  assert.equal(await page.locator('[data-drawer-toggle]').getAttribute('aria-expanded'),'false');
  await page.locator('[data-drawer-toggle]').click();
  await page.locator('[data-raise-toggle]').click();
  assert.ok(await page.locator('.poker-raise-presets').isVisible());
  assert.equal(await page.locator('[data-quick]').count(),4);
  await page.screenshot({path:`${output}/fullscreen-phone-presets-${width}.png`});
  await page.locator('[data-quick]').filter({hasText:'满池'}).click();
  assert.equal(await page.locator('[data-raise]').inputValue(),'60');
  assert.equal(await page.locator('.poker-raise-presets').isVisible(),false);
  // Nine-seat placement, resizing and controls remain live inside the same persistent fullscreen root.
  await page.evaluate(()=>PokerPreview.next('nine'));
  await page.waitForFunction(()=>JSON.parse(render_game_to_text()).seats.length===9);
  await page.screenshot({path:`${output}/fullscreen-phone-nine-${width}.png`});
  if(width===390){
    await page.setViewportSize({width:844,height:390});
    await page.waitForFunction(()=>!document.querySelector('#pokerView').classList.contains('poker-fullscreen-portrait'));
    assert.ok(await page.locator('[data-exit-fullscreen]').isVisible());
    await page.screenshot({path:`${output}/fullscreen-phone-rotated.png`});
  }
  await page.locator('[data-raise-toggle]').click();
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.poker-raise-presets').isVisible(),false);
  assert.ok(await page.locator('#pokerView').evaluate(el=>el.classList.contains('poker-fullscreen')));
  await page.locator('[data-leave]').click();
  assert.ok(await page.locator('.poker-dialog').isVisible());
  await page.locator('.poker-dialog [data-cancel]').click();
  await page.locator('[data-raise]').fill('80');
  await page.locator('[data-raise]').press('Enter');
  await page.waitForFunction(()=>JSON.parse(render_game_to_text()).actor==='2');
  assert.equal(await page.evaluate(()=>PokerPreview.requests.filter(x=>x.data?.action==='raise').at(-1).data.amount),80);
  await page.locator('[data-exit-fullscreen]').click();
  assert.equal(await page.locator('#pokerView').evaluate(el=>el.classList.contains('poker-fullscreen')),false);
  assert.equal(await page.locator('.poker-controls').evaluate(el=>el.inert),false);
  assert.equal(await page.locator('[data-exit-fullscreen]').isVisible(),false);
  assert.deepEqual(errors,[]);results.push({scenario:`phone ${width}x${height}: fallback landscape, drawer, polling, raise, nine seats, exit`,geometry,errors});await page.close();
}
const {page,errors}=await makePage(1440,1100);
await page.locator('[data-action=ready]').click();
await page.locator('[data-raise]').waitFor();
assert.ok(await page.evaluate(()=>window.motionEvents.filter(e=>e.className.includes('poker-card')).length)>=12);
await page.waitForTimeout(850);await page.evaluate(()=>scrollTo(0,0));
await page.screenshot({path:`${output}/desktop-preflop.png`,fullPage:true});
assert.equal(await page.locator('[data-raise]').getAttribute('placeholder'),'加注');
assert.equal(await page.locator('[data-raise]').inputValue(),'40');
await page.locator('[data-raise-toggle]').click();
await page.locator('[data-quick]').filter({hasText:'满池'}).click();
assert.equal(await page.locator('[data-raise]').inputValue(),'55');
await page.locator('[data-raise]').fill('180');
assert.equal(await page.locator('input[type=range]').count(),0);
assert.equal(await page.locator('[data-quick]').count(),4);
assert.equal(await page.locator('[data-raise]').inputValue(),'180');
await page.locator('[data-raise]').focus();
await page.locator('[data-raise]').fill('1');
const invalidBefore=await page.evaluate(()=>PokerPreview.requests.filter(r=>r.data?.action==='raise').length);
await page.locator('[data-action=raise]').click();
assert.match(await page.locator('.poker-notice').innerText(),/有效/);
assert.equal(await page.evaluate(()=>PokerPreview.requests.filter(r=>r.data?.action==='raise').length),invalidBefore);
await page.locator('[data-raise]').fill('180');
await page.evaluate(()=>window.savedInput=document.querySelector('[data-raise]'));
await page.waitForTimeout(1750);
assert.ok(await page.evaluate(()=>window.savedInput===document.querySelector('[data-raise]')),'unchanged polls must keep the input node');
await page.evaluate(()=>{const room=PokerPreview.room;room.pot+=5;PokerPreview.setRoom(room);});
await page.waitForTimeout(1700);
assert.equal(await page.locator('[data-raise]').inputValue(),'180');
assert.ok(await page.locator('[data-raise]').evaluate(el=>el===document.activeElement));
await page.locator('[data-sound]').click();await page.waitForTimeout(120);
assert.equal(await page.locator('[data-sound]').getAttribute('aria-pressed'),'true');
await page.locator('[data-action=raise]').click();
await page.waitForFunction(()=>JSON.parse(render_game_to_text()).actor==='2');
assert.equal(await page.evaluate(()=>PokerPreview.requests.filter(r=>r.data?.action==='raise').at(-1).data.amount),180);
assert.ok(await page.evaluate(()=>window.motionEvents.some(e=>String(e.className).includes('poker-flying-token'))));
await page.locator('[data-preview=flop]').click();await page.waitForFunction(()=>JSON.parse(render_game_to_text()).street==='flop');
await page.waitForTimeout(750);await page.screenshot({path:`${output}/desktop-flop.png`,fullPage:true});
await page.locator('.poker-room-screen').screenshot({path:`${output}/desktop-preview.png`});
const motionsBefore=await page.evaluate(()=>window.motionEvents.length);await page.waitForTimeout(1650);assert.equal(await page.evaluate(()=>window.motionEvents.length),motionsBefore);
await page.locator('[data-preview=showdown]').click();await page.waitForFunction(()=>JSON.parse(render_game_to_text()).street==='finished');
await page.waitForTimeout(1200);assert.equal(await page.locator('.poker-seat-winner').count(),1);await page.screenshot({path:`${output}/desktop-showdown.png`,fullPage:true});
await page.locator('[data-preview=deal]').click();await page.waitForFunction(()=>JSON.parse(render_game_to_text()).hand===2);
await page.evaluate(()=>{PokerPreview.next('flop');const room=PokerPreview.room;room.street='finished';room.actions=null;room.actor=null;room.result={payouts:{'1':90,'2':90},showdown:true,hands:{'1':'顺子','2':'顺子'},pots:[{amount:180,winners:['1','2']}]};PokerPreview.setRoom(room);});
await page.waitForFunction(()=>document.querySelectorAll('.poker-seat-winner').length===2);
await page.waitForTimeout(1200);assert.equal(await page.locator('.poker-flying-token').count(),0);
await page.locator('[data-preview=deal]').click();await page.waitForFunction(()=>JSON.parse(render_game_to_text()).hand===3);
await page.locator('[data-action=fold]').click();await page.waitForFunction(()=>document.querySelector('.poker-seat-own').classList.contains('poker-seat-folded'));
await page.locator('[data-help]').click();assert.ok(await page.locator('.poker-room-help').isVisible());
await page.locator('[data-lobby]').click();await page.waitForTimeout(800);assert.equal(await page.locator('.poker-flying-token').count(),0);
await page.evaluate(()=>{PokerPreview.setSeated(false);PokerPreview.setCapacity({players:10,limit:10,available:0});});
await page.waitForFunction(()=>document.querySelector('.poker-capacity')?.textContent.includes('人数已满'));
assert.equal(await page.locator('[data-create]:disabled').count(),3);
results.push({scenario:'desktop deal/bet/flop/showdown/fold/raise persistence/sound/help/lobby',errors});assert.deepEqual(errors,[]);
await page.evaluate(()=>PokerModule.close());
assert.equal(await page.evaluate(()=>JSON.parse(render_game_to_text()).mode),'closed');
await page.close();
for(const width of [360,390,768]){
  const {page,errors}=await makePage(width,844);
  await page.locator('[data-action=ready]').click();await page.locator('[data-action=raise]').waitFor();
  await page.locator('[data-preview=nine]').click();await page.waitForFunction(()=>JSON.parse(render_game_to_text()).seats.length===9);
  await page.waitForTimeout(800);await page.evaluate(()=>scrollTo(0,0));
  const layout=await page.evaluate(()=>{
    const stage=document.querySelector('.poker-table').getBoundingClientRect();
    const seats=[...document.querySelectorAll('.poker-seat-plate')].map(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};});
    const overlaps=[];for(let i=0;i<seats.length;i++)for(let j=i+1;j<seats.length;j++){const a=seats[i],b=seats[j];if(Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x)>1&&Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y)>1)overlaps.push([i,j]);}
    return {overflow:document.documentElement.scrollWidth>innerWidth,overlaps,outside:seats.some(r=>r.x<stage.x||r.x+r.w>stage.right)};
  });
  assert.equal(layout.overflow,false);assert.deepEqual(layout.overlaps,[]);assert.equal(layout.outside,false);
  if(width<701){
    assert.ok(await page.evaluate(()=>{const nodes=[...document.querySelectorAll('.poker-action-buttons > button,.poker-raise-control')];const tops=nodes.map(el=>el.getBoundingClientRect().top);return Math.max(...tops)-Math.min(...tops)<6;}),'phone non-fullscreen controls must stay in one horizontal row');
    assert.ok(await page.locator('.poker-raise-control').isVisible());
    const ownVisible=await page.evaluate(()=>document.querySelector('.poker-seat-own .poker-seat-plate').getBoundingClientRect().bottom <= document.querySelector('.poker-controls').getBoundingClientRect().top);
    assert.ok(ownVisible,'mobile controls must not cover your seat');
    assert.equal(await page.locator('[data-close-sizer]').count(),0);
    await page.evaluate(()=>scrollTo(0,0));
  }
  await page.screenshot({path:`${output}/nine-${width}.png`,fullPage:true});
  await page.locator('[data-preview=flop]').click();await page.waitForFunction(()=>JSON.parse(render_game_to_text()).street==='flop');
  await page.waitForTimeout(750);await page.screenshot({path:`${output}/flop-${width}.png`,fullPage:true});
  results.push({scenario:`nine seats / flop ${width}`,layout,errors});assert.deepEqual(errors,[]);await page.close();
}
{
  const {page,errors}=await makePage(2560,1600);
  await page.evaluate(()=>document.querySelector('main').style.maxWidth='none');
  await page.locator('[data-action=ready]').click();await page.locator('[data-action=raise]').waitFor();
  const checks=[];
  for(const width of [2560,3840]){
    await page.setViewportSize({width,height:1600});
    await page.waitForTimeout(700);
    const geometry=await page.evaluate(()=>{const r=document.querySelector('.poker-table').getBoundingClientRect();return {width:r.width,height:r.height,ratio:r.width/r.height,center:r.x+r.width/2,viewport:innerWidth};});
    assert.ok(geometry.width<=1320&&geometry.width>=1300);
    assert.ok(geometry.height>=640);
    assert.ok(geometry.ratio<2.1&&geometry.ratio>1.9);
    assert.ok(Math.abs(geometry.center-geometry.viewport/2)<2);
    checks.push(geometry);
    await page.screenshot({path:`${output}/wide-${width}.png`,fullPage:true});
  }
  results.push({scenario:'2K and 4K desktop: centered table with stable proportions',checks,errors});assert.deepEqual(errors,[]);await page.close();
}
{
  const {page,errors}=await makePage(390,844,'reduce');
  await page.locator('[data-action=ready]').click();await page.locator('[data-action=raise]').waitFor();
  await page.locator('[data-preview=flop]').click();await page.waitForFunction(()=>JSON.parse(render_game_to_text()).street==='flop');
  assert.equal(await page.evaluate(()=>window.motionEvents.length),0);
  await page.locator('[data-preview=showdown]').click();await page.waitForFunction(()=>JSON.parse(render_game_to_text()).street==='finished');
  assert.equal(await page.evaluate(()=>window.motionEvents.length),0);assert.ok(await page.locator('.poker-result').isVisible());
  results.push({scenario:'reduced motion keeps result and controls',errors});assert.deepEqual(errors,[]);await page.close();
}
{
  const {page,errors}=await makePage(390,650);
  await page.locator('[data-action=ready]').click();await page.locator('[data-action=raise]').waitFor();
  await page.locator('[data-action=raise]').scrollIntoViewIfNeeded();
  const clear=await page.evaluate(()=>{const a=document.querySelector('.poker-seat-own').getBoundingClientRect(),b=document.querySelector('.poker-controls').getBoundingClientRect();return a.bottom<=b.top&&a.top>=0;});
  assert.ok(clear,'short-screen actions must leave the player hand visible');
  await page.screenshot({path:`${output}/short-mobile.png`,fullPage:true});
  results.push({scenario:'short phone 390x650: scroll hand and actions together',errors});assert.deepEqual(errors,[]);await page.close();
}
{
  const {page,errors}=await makePage(844,390,'no-preference',true);
  await page.evaluate(()=>{const room=PokerPreview.room;room.mode='practice';PokerPreview.setRoom(room);});
  await page.waitForTimeout(1700);
  await page.locator('[data-fullscreen]').click();
  await page.locator('[data-action=ready]').click();
  await page.locator('[data-action=raise]').waitFor();
  await page.locator('[data-leave]').click();
  await page.waitForFunction(()=>JSON.parse(render_game_to_text()).mode==='lobby');
  assert.equal(await page.locator('.poker-dialog').count(),0);
  assert.equal(await page.locator('#pokerView').evaluate(el=>el.classList.contains('poker-fullscreen')),false);
  assert.equal(await page.evaluate(()=>PokerPreview.requests.filter(x=>x.data?.action==='leave').length),1);
  assert.deepEqual(errors,[]);results.push({scenario:'practice leave immediately returns to lobby and cleans fullscreen without dialog',errors});await page.close();
}
fs.writeFileSync(`${output}/results.json`,JSON.stringify(results,null,2));
await browser.close();console.log(JSON.stringify(results,null,2));

} finally { await browser.close(); server.close(); }
