import {createRequire} from 'node:module';
import {createServer} from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {chromium} = require('../.local/poker-ui/node_modules/playwright');
const repo = path.resolve('.');
const allowed = new Set(['/tests/fixtures/poker-ui.html', '/tests/fixtures/poker-ui.js', '/poker.js', '/poker.css', '/styles.css', '/extensions.css', '/static/vendor/daisyui/poker-components.css']);
['/theme-model.js','/theme-settings.js','/theme-settings.css'].forEach(file=>allowed.add(file));
const server = createServer((req, res) => {
  const file = new URL(req.url, 'http://localhost').pathname;
  if (!allowed.has(file)) {res.writeHead(404); res.end(); return;}
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript; charset=utf-8' : file.endsWith('.css') ? 'text/css' : 'text/html; charset=utf-8');
  let content = fs.readFileSync(path.join(repo, file), 'utf8');
  if (file.endsWith('poker-ui.html')) content = content.replace('</html>', '<link rel="stylesheet" href="/theme-settings.css"><script src="/theme-model.js"></script><script src="/theme-settings.js"></script></html>');
  if (file.endsWith('poker-ui.js')) content += `
    window.chipWallet = {balance:3, chips:500};
    window.clubApi.request = async (url, options) => {
      const data = options?.body && JSON.parse(options.body);
      if (window.showTable && url.endsWith('/fixture')) return {ok:true,json:async()=>({room:{...window.PokerPreview.room,mode:window.showTable},user_id:1,...window.chipWallet})};
      if (data) {
        if (data.action === 'buy') {window.chipWallet.balance -= data.coins; window.chipWallet.chips += data.coins*1000;}
        if (data.action === 'withdraw') {window.chipWallet.balance += data.coins; window.chipWallet.chips -= data.coins*1000;}
      }
      return {ok:true, json:async()=>({...window.chipWallet, enabled:true, current_room:window.showTable?'fixture':null, rooms:[], capacity:{players:0,limit:10,available:10}})};
    };`;
  res.end(content);
});
await new Promise(resolve=>server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({headless:true});
fs.mkdirSync('output/playwright/poker-chips', {recursive:true});
try {
  for (const width of [1280, 390]) {
    const page = await browser.newPage({viewport:{width,height:900}});
    const errors=[]; page.on('pageerror', error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/tests/fixtures/poker-ui.html`);
    await page.locator('[data-exchange=buy]').waitFor();
    assert.equal(await page.locator('.poker-wallet-value').innerText(), '剩余筹码\n500');
    assert.equal(await page.locator('[data-exchange=withdraw]').isDisabled(), true);
    await page.locator('[data-exchange=buy]').click();
    await page.locator('input[name=coins]').fill('2');
    assert.match(await page.locator('.poker-dialog [data-preview]').innerText(), /2,000/);
    await page.locator('.poker-dialog [type=submit]').click();
    await page.waitForFunction(()=>document.querySelector('.poker-wallet strong')?.textContent === '2,500');
    await page.locator('[data-exchange=withdraw]').click();
    await page.locator('input[name=coins]').fill('2');
    await page.locator('.poker-dialog [type=submit]').click();
    await page.waitForFunction(()=>document.querySelector('.poker-wallet strong')?.textContent === '500');
    assert.deepEqual(await page.evaluate(()=>window.chipWallet), {balance:3,chips:500});
    await page.locator('[data-create=coins]').click();
    assert.equal(await page.getByText('底注（筹码）', {exact:false}).count(), 1);
    assert.equal(await page.locator('[name=buy_in]').inputValue(), '1000');
    await page.locator('[data-cancel]').click();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth), false);
    const geometry = await page.locator('.poker-wallet').evaluate(el=>{
      const value=el.querySelector('.poker-wallet-value').getBoundingClientRect();
      const actions=el.querySelector('.poker-wallet-actions').getBoundingClientRect();
      return {right:actions.left >= value.right, height:actions.height};
    });
    assert.ok(geometry.right); assert.ok(geometry.height >= 44);
    await page.screenshot({path:`output/playwright/poker-chips/wallet-${width}.png`, fullPage:true});
    assert.deepEqual(errors, []);
    await page.close();
  }
  for (const width of [1280,390]) for (const theme of ['original','light','dark','custom']) {
    const page = await browser.newPage({viewport:{width,height:760}});
    const errors=[];page.on('pageerror', error=>errors.push(error.message));
    await page.addInitScript(theme=>{
      const mode=theme==='custom'?'dark':theme;
      const config={mode,glass:false,animations:false};
      if(theme==='custom') config.blocks={dark:{dialog:{enabled:true,background:'#142a35',accent:'#a9d6e5',textMode:'light'}}};
      localStorage.setItem('rbc-site-theme-v3',JSON.stringify(config));
    },theme);
    await page.goto(`http://127.0.0.1:${server.address().port}/tests/fixtures/poker-ui.html`);
    await page.locator('[data-create=coins]').waitFor();
    for (const mode of ['coins','friendly','practice']) {
      await page.locator(`[data-create=${mode}]`).click();
      await page.locator('.poker-dialog').waitFor();
      await page.waitForFunction(theme=>theme==='original'||document.querySelector('.poker-dialog')?.dataset.siteThemed==='true',theme);
      const metrics=await page.locator('.poker-dialog').evaluate(el=>{
        const style=getComputedStyle(el),r=el.getBoundingClientRect();
        return {bg:style.backgroundColor,accent:getComputedStyle(el.querySelector('.primary-button')).backgroundColor,
          overflow:el.scrollWidth>el.clientWidth,onscreen:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight,
          label:el.getAttribute('aria-labelledby'),bodyBlock:el.querySelector('form').dataset.themeBlock};
      });
      assert.ok(metrics.onscreen,JSON.stringify({width,theme,mode,metrics}));assert.equal(metrics.overflow,false);assert.ok(metrics.label);
      assert.equal(metrics.bodyBlock,undefined);
      if(theme==='light') assert.equal(metrics.bg,'rgb(255, 255, 255)');
      if(theme==='dark') assert.equal(metrics.bg,'rgb(44, 44, 46)');
      if(theme==='custom') {assert.equal(metrics.bg,'rgb(20, 42, 53)');assert.equal(metrics.accent,'rgb(169, 214, 229)');}
      if(mode!=='coins') assert.match(await page.locator('.poker-dialog-note').innerText(),/不进入可兑换筹码余额/);
      await page.screenshot({path:`output/playwright/poker-chips/dialog-${mode}-${theme}-${width}.png`});
      await page.getByRole('button',{name:'关闭弹窗',exact:true}).click();
    }
    await page.locator('[data-exchange=buy]').click();
    await page.screenshot({path:`output/playwright/poker-chips/dialog-buy-${theme}-${width}.png`});
    await page.locator('[name=coins]').press('Escape');
    await page.locator('.poker-dialog').waitFor({state:'detached'});
    await page.evaluate(()=>{window.chipWallet.chips=2500;window.PokerModule.open();});
    await page.locator('[data-exchange=withdraw]').click();
    assert.equal(await page.locator('[name=coins]').getAttribute('max'),'2');
    await page.screenshot({path:`output/playwright/poker-chips/dialog-withdraw-${theme}-${width}.png`});
    await page.getByRole('button',{name:'关闭弹窗',exact:true}).click();
    await page.evaluate(()=>{window.showTable='friendly';window.PokerModule.open();});
    await page.locator('[data-leave]').click();
    assert.match(await page.locator('.poker-dialog-note').innerText(),/不进入可兑换筹码余额/);
    await page.screenshot({path:`output/playwright/poker-chips/dialog-leave-${theme}-${width}.png`});
    await page.locator('[data-cancel]').click();
    assert.deepEqual(errors,[]);await page.close();
  }
  console.log('Chip wallet and dialogs passed: desktop/mobile, original/light/dark/custom themes, creation, exchange, practice isolation copy, leave, and Escape.');
} finally {await browser.close(); server.close();}
