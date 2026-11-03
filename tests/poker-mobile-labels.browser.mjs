import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require('../.local/poker-ui/node_modules/playwright');
const allowed=new Set(['/tests/fixtures/poker-ui.html','/tests/fixtures/poker-ui.js','/poker.js','/poker.css','/styles.css','/extensions.css','/static/vendor/daisyui/poker-components.css']);
const server=createServer((req,res)=>{
  const file=new URL(req.url,'http://localhost').pathname;
  if(!allowed.has(file)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript; charset=utf-8':file.endsWith('.css')?'text/css':'text/html; charset=utf-8');
  res.end(fs.readFileSync(path.join(process.cwd(),file)));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({headless:true});
const output='output/playwright/poker-mobile-labels';fs.mkdirSync(output,{recursive:true});
const results=[];
try{
  for(const [width,height] of [[390,844],[844,390],[667,375]]){
    const page=await browser.newPage({viewport:{width,height},isMobile:true,hasTouch:true});
    await page.addInitScript(()=>{Object.defineProperty(Element.prototype,'requestFullscreen',{value:undefined,configurable:true});});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/tests/fixtures/poker-ui.html`);
    await page.locator('[data-fullscreen]').click();
    for(const [state,label,action] of [['ready','准备开局','ready'],['cancel','取消准备','ready'],['refill','领取练习筹码','refill']]){
      if(state!=='ready'){
        await page.evaluate(state=>{const room=window.PokerPreview.room;room.seats[0].ready=state==='cancel';room.seats[0].stack=state==='refill'?0:1000;window.PokerPreview.setRoom(room);},state);
      }
      const button=page.locator(`[data-action=${action}]`);
      await page.waitForFunction(({action,label})=>document.querySelector(`[data-action=${action}]`)?.textContent===label,{action,label});
      const geometry=await button.evaluate(el=>{
        const range=document.createRange();range.selectNodeContents(el);
        const text=range.getBoundingClientRect(),box=el.getBoundingClientRect();
        return {textFits:text.left>=box.left-1&&text.right<=box.right+1&&text.top>=box.top-1&&text.bottom<=box.bottom+1,
          width:el.offsetWidth,height:el.offsetHeight,rail:document.querySelector('.poker-controls').offsetWidth,
          whiteSpace:getComputedStyle(el).whiteSpace};
      });
      assert.ok(geometry.textFits,JSON.stringify({width,state,geometry}));
      assert.equal(geometry.whiteSpace,'nowrap');assert.equal(geometry.rail,30);
      results.push({width,height,state,...geometry});
      await page.screenshot({path:`${output}/${state}-${width}.png`});
    }
    await page.evaluate(()=>{const room=window.PokerPreview.room;room.seats[0].stack=1000;room.seats[0].ready=false;window.PokerPreview.setRoom(room);window.PokerPreview.next('deal');});
    await page.locator('[data-raise]').waitFor();
    await page.locator('[data-raise]').fill('100000');
    assert.equal(await page.locator('.poker-controls').evaluate(el=>el.offsetWidth),46);
    await page.locator('[data-raise]').fill('20');
    assert.equal(await page.locator('.poker-controls').evaluate(el=>el.offsetWidth),30);
    assert.deepEqual(errors,[]);await page.close();
  }
  fs.writeFileSync(`${output}/results.json`,JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
}finally{await browser.close();server.close();}
