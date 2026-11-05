async page => {
 await page.setViewportSize({width:1365,height:900});
 await page.setContent('<!doctype html><html lang="zh"><body><button>打开装扮管理</button></body></html>');
 for(const path of ['styles.css','static/shop-titles.css','static/cosmetic-studio.css'])await page.addStyleTag({path});
 await page.addScriptTag({path:'theme-model.js'});
 await page.evaluate(()=>{
  window.CosmeticMedia={safe:()=>false};window.MemberTitles={frameAvatar:x=>x,badgeMarkup:()=>''};
  window.savedDraft=null;window.loadCount=0;
  const existing={kind:'theme',key:'existing-theme',name:'已存在的主题',revision:7,palettes:SiteTheme.defaults().palettes};
  window.clubApi={request:async(url,options)=>{
   if(options?.method==='POST'){window.savedDraft=JSON.parse(options.body);return {ok:true,json:async()=>({asset:{...savedDraft,revision:1}})}}
   if(++window.loadCount===1)return new Promise(resolve=>window.finishCatalog=()=>resolve({ok:true,json:async()=>({assets:[existing]})}));
   return {ok:true,json:async()=>({assets:[existing]})};
  }};
 });
 await page.addScriptTag({path:'static/cosmetic-studio.js'});
 await page.evaluate(()=>CosmeticStudio.open());
 await page.locator('[data-close]').last().focus();
 await page.evaluate(()=>finishCatalog());
 await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,50)));
 if(!await page.evaluate(()=>document.activeElement?.textContent==='完成'))throw Error('Initial catalog redraw lost close focus');
 await page.locator('[data-close]').first().click();
 await page.evaluate(()=>{loadCount=0;CosmeticStudio.open()});
 await page.locator('[data-tab="editor"]').click();
 if(!await page.evaluate(()=>document.activeElement?.dataset.tab==='editor'))throw Error('Tab redraw lost selected tab focus');
 for(const mode of ['dark','light']){
  await page.locator(`[data-mode="${mode}"]`).click();
  if(!await page.evaluate(mode=>document.activeElement?.dataset.mode===mode,mode))throw Error('Preview mode redraw lost focus');
 }
 for(const shiftKey of [false,true]){
  await page.locator('body > button').focus();
  const trapped=await page.evaluate(shiftKey=>{const event=new KeyboardEvent('keydown',{key:'Tab',shiftKey,bubbles:true,cancelable:true});document.dispatchEvent(event);return event.defaultPrevented&&document.querySelector('.studio-overlay').contains(document.activeElement)},shiftKey);
  if(!trapped)throw Error('Studio did not recapture escaped keyboard focus');
 }
 await page.locator('[name="key"]').fill('new-garden');await page.locator('[name="name"]').fill('我的花园主题');
 await page.locator('[data-color="accent"]').fill('#445566');
 await page.evaluate(()=>{window.nameField=document.querySelector('[name="name"]');finishCatalog()});
 await page.waitForFunction(()=>window.loadCount===1&&document.querySelector('[name="name"]')?.value==='我的花园主题');
 await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,50)));
 if(!await page.evaluate(()=>nameField===document.querySelector('[name="name"]')))throw Error('Catalog completion redrew the active editor');
 if(await page.locator('[name="key"]').getAttribute('readonly')!==null)throw Error('Draft switched to an existing resource');
 if(await page.locator('[data-color="accent"]').inputValue()!=='#445566')throw Error('Draft palette was replaced');
 const hints=await page.locator('.studio-upload-hint').allTextContents();
 if(hints.length!==3||!hints[0].includes('54 × 54')||!hints[1].includes('1920 × 1080')||!hints[2].includes('1920 × 1080'))throw Error('Theme upload size recommendations are missing');
 await page.locator('[name="kind"]').selectOption('frame');
 if(!(await page.locator('.studio-upload-hint').textContent()).includes('120 × 120'))throw Error('Frame upload recommendation is missing');
 await page.locator('[name="kind"]').selectOption('theme');
 await page.setViewportSize({width:390,height:844});
 if(!await page.evaluate(()=>document.querySelector('.studio-dialog').getBoundingClientRect().width<=390))throw Error('Mobile studio overflows');
 await page.locator('.studio-upload-grid').scrollIntoViewIfNeeded();
 await page.screenshot({path:'.local/studio-mobile-review.png'});
 await page.locator('form [type="submit"]').click();
 await page.waitForFunction(()=>window.savedDraft!==null);
 if(!await page.evaluate(()=>savedDraft.key==='new-garden'&&savedDraft.name==='我的花园主题'&&savedDraft.palettes.light.accent==='#445566'&&!('revision' in savedDraft)))throw Error('Saved payload no longer represents the new draft');
 console.log('Passed: slow initial catalog preserves new draft, editable key, palette, create payload and recommended upload sizes at mobile width.');
}
