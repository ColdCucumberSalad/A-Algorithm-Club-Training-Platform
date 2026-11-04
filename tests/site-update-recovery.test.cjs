const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../workbench.js'),'utf8');

async function render(recovery,state='failed'){
 const nodes=new Map(),controls=[{},{},{}];
 const form={elements:{mode:{},time:{}},querySelectorAll:()=>controls};
 const context={workbenchProfile:{site_admin:true},siteUpdateLoading:false,siteUpdatePending:false,siteUpdateTimer:0,
  workbench$:selector=>{if(selector==='#wbSiteUpdateForm')return form;if(!nodes.has(selector))nodes.set(selector,{});return nodes.get(selector);},
  communityRequest:async()=>({available:true,state,recovery_required:recovery,current:'a'.repeat(40),latest:'b'.repeat(40),schedule:{mode:'auto',time:'04:00'}}),
  clearTimeout(){},setTimeout(){return 1;},escapeHtml:String};
 vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('async function loadSiteUpdates('),source.indexOf('async function requestSiteUpdate(')),context);
 await context.loadSiteUpdates();
 return nodes;
}

test('manual update stays disabled and recovery warning survives harmless successful operations',async()=>{
 for(const state of ['failed','succeeded']){
  const nodes=await render(true,state);
  assert.equal(nodes.get('#wbSiteInstall').disabled,true);
  assert.equal(nodes.get('#wbSiteCheck').disabled,false);
  assert.match(nodes.get('#wbSiteUpdateStatus').textContent,/人工恢复/);
 }
});

test('a normal new revision remains available for manual update',async()=>{
 const nodes=await render(false,'succeeded');
 assert.equal(nodes.get('#wbSiteInstall').disabled,false);
});
