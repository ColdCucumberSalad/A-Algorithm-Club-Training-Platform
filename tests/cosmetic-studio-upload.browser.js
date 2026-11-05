async page => {
 for(const failFirst of [false,true]){
  await page.setContent('<!doctype html><html lang="zh"><body><button>打开装扮管理</button></body></html>');
  for(const path of ['styles.css','static/shop-titles.css','static/cosmetic-studio.css'])await page.addStyleTag({path});
  await page.addScriptTag({path:'theme-model.js'});
  await page.evaluate(()=>{
   window.CosmeticMedia={safe:()=>false};window.MemberTitles={frameAvatar:x=>x,badgeMarkup:()=>''};
   window.uploadCalls=[];window.pendingUpload={};window.savedDraft=null;
   window.clubApi={request:async(url,options)=>{
    if(url.endsWith('/upload')){const name=options.body.get('file').name;uploadCalls.push(name);return new Promise(resolve=>pendingUpload[name]=(ok,value)=>resolve({ok,json:async()=>ok?{url:value}:{error:value}}));}
    if(options?.method==='POST'){savedDraft=JSON.parse(options.body);return {ok:true,json:async()=>({asset:{...savedDraft,revision:1}})}}
    return {ok:true,json:async()=>({assets:[]})};
   }};
  });
  await page.addScriptTag({path:'static/cosmetic-studio.js'});await page.evaluate(()=>CosmeticStudio.open());
  await page.locator('[data-tab="editor"]').click();await page.locator('[name="key"]').fill('queued-theme');await page.locator('[name="name"]').fill('排队上传主题');
  const image=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jH3cAAAAASUVORK5CYII=','base64');
  await page.locator('[data-upload="background"]').setInputFiles({name:'background.png',mimeType:'image/png',buffer:image});
  await page.waitForFunction(()=>pendingUpload['background.png']);
  await page.locator('[data-upload="poster"]').setInputFiles({name:'poster.png',mimeType:'image/png',buffer:image});
  if(!await page.locator('form [type=submit]').isDisabled())throw Error('Save enabled while uploads queued');
  if(!await page.evaluate(()=>uploadCalls.length===1))throw Error('Image uploads did not serialize');
  await page.locator('[data-close]').first().click();if(!await page.locator('.studio-overlay').count())throw Error('Editor closed before uploads completed');
  await page.evaluate(()=>document.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
  if(await page.evaluate(()=>savedDraft!==null))throw Error('Premature submit persisted partial images');
  await page.evaluate(fail=>pendingUpload['background.png'](!fail,fail?'背景上传失败':'/api/cosmetic-assets/media/'+'a'.repeat(64)+'.png'),failFirst);
  await page.waitForFunction(()=>pendingUpload['poster.png']);
  if(!await page.locator('form [type=submit]').isDisabled())throw Error('First completion enabled save with another upload pending');
  if(!await page.locator('[data-tab="library"]').isDisabled())throw Error('Draft switching enabled with pending upload');
  await page.evaluate(()=>pendingUpload['poster.png'](true,'/api/cosmetic-assets/media/'+'b'.repeat(64)+'.png'));
  await page.waitForFunction(()=>!document.querySelector('form [type=submit]').disabled);
  if(failFirst&&!await page.locator('[data-studio-status]').evaluate(el=>el.classList.contains('is-error')&&el.textContent.includes('背景上传失败')))throw Error('Later success hid earlier upload failure');
  await page.locator('form [type=submit]').click();await page.waitForFunction(()=>savedDraft!==null);
  await page.waitForFunction(()=>document.querySelector('[data-studio-status]').textContent.includes('已保存'));
  if(await page.locator('[data-tab="library"]').isDisabled()||await page.locator('form [type=submit]').isDisabled())throw Error('Editor remained locked after save');
  if(!await page.evaluate(fail=>savedDraft.poster==='/api/cosmetic-assets/media/'+'b'.repeat(64)+'.png'&&savedDraft.background===(fail?'':'/api/cosmetic-assets/media/'+'a'.repeat(64)+'.png'),failFirst))throw Error('Saved draft lost selected images');
 }
 console.log('Passed: queued uploads block save/close/resource switching until all settle; both selected URLs persist; earlier upload failures stay visible.');
}
