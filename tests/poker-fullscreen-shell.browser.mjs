import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium,webkit}=require('../.local/poker-ui/node_modules/playwright');
const engine=process.env.POKER_BROWSER==='webkit'?webkit:chromium;
const output=`output/playwright/poker-fullscreen-shell/${engine.name()}`;
fs.mkdirSync(output,{recursive:true});
const allowed=new Set(['/tests/fixtures/poker-ui.html','/tests/fixtures/poker-ui.js','/poker.js','/poker.css','/styles.css','/extensions.css','/static/vendor/daisyui/poker-components.css']);
const server=createServer((req,res)=>{
  const file=new URL(req.url,'http://localhost').pathname;
  if(!allowed.has(file)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript; charset=utf-8':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');
  let content=fs.readFileSync(path.join(process.cwd(),file),'utf8');
  if(file.endsWith('poker-ui.html')) content=content.replace('<main>', '<main class="main-content" style="transform:translateZ(0);filter:opacity(1);overflow:hidden"><header style="height:100px">网站顶栏</header><section id="extensionsView" class="page-view active" style="perspective:1200px;overflow:hidden"><div id="rootBefore"></div>').replace('</main>','<div id="rootAfter"></div></section></main><div style="height:1200px"></div>');
  res.end(content);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await engine.launch({headless:true});
const results=[];
try{
  for(const [width,height]of [[402,680],[390,844],[844,390],[667,375]]){
    const page=await browser.newPage({viewport:{width,height},isMobile:true,hasTouch:true});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{Element.prototype.requestFullscreen=()=>Promise.reject(new Error('Native fullscreen unavailable'));});
    await page.goto(`http://127.0.0.1:${server.address().port}/tests/fixtures/poker-ui.html`);
    await page.locator('[data-fullscreen]').waitFor();
    await page.evaluate(()=>window.scrollTo(0,100));
    await page.locator('[data-fullscreen]').click();
    const geometry=await page.locator('#pokerView').evaluate(el=>{
      const r=el.getBoundingClientRect(),stage=el.querySelector('.poker-room-screen').getBoundingClientRect();
      return {x:r.x,y:r.y,width:r.width,height:r.height,stage:{x:stage.x,y:stage.y,width:stage.width,height:stage.height},viewport:{width:innerWidth,height:innerHeight}};
    });
    await page.screenshot({path:`${output}/fullscreen-${width}.png`});
    assert.ok(Math.abs(geometry.x)<1&&Math.abs(geometry.y)<1&&Math.abs(geometry.width-width)<1&&Math.abs(geometry.height-height)<1,JSON.stringify(geometry));
    assert.equal(await page.locator('#pokerView').evaluate(el=>el.parentElement===document.body),true);
    await page.locator('[data-action=ready]').click();
    await page.locator('[data-action=fold]').waitFor();
    await page.locator('[data-raise]').fill('100');
    await page.waitForTimeout(1700);
    assert.equal(await page.locator('[data-raise]').inputValue(),'100');
    if(width<height){
      await page.setViewportSize({width:height,height:width});
      await page.waitForFunction(()=>!document.querySelector('#pokerView').classList.contains('poker-fullscreen-portrait'));
      assert.equal(await page.locator('#pokerView').evaluate(el=>Math.round(el.getBoundingClientRect().width)),height);
    }
    await page.locator('[data-exit-fullscreen]').click();
    assert.equal(await page.locator('#pokerView').evaluate(el=>el.parentElement.id),'extensionsView');
    assert.equal(await page.locator('#pokerView').evaluate(el=>el.nextElementSibling.id),'rootAfter');
    assert.equal(await page.locator('body').evaluate(el=>el.classList.contains('poker-fullscreen-page')),false);
    await page.locator('[data-fullscreen]').click();
    await page.evaluate(()=>window.PokerModule.close());
    assert.equal(await page.locator('#pokerView').evaluate(el=>el.parentElement.id),'extensionsView');
    assert.equal(await page.locator('#pokerView').isVisible(),false);
    assert.deepEqual(errors,[]);results.push({width,height,geometry,errors});await page.close();
  }
  fs.writeFileSync(`${output}/results.json`,JSON.stringify(results,null,2));
  console.log(`${engine.name()}: actual page ancestry, fullscreen rejection, polling, rotation, exit and cleanup passed.`);
}finally{await browser.close();server.close();}
