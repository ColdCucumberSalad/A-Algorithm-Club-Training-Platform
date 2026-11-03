const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');

function fixture(){
  const detail={innerHTML:''};
  const context={window:{},document:{addEventListener(){},querySelector(selector){assert.equal(selector,'#gmDetail');return detail;}}};
  const source=fs.readFileSync(require.resolve('../static/account-management.js'),'utf8');
  const exposed=source.replace('return {loadAccounts,openSelf,openAccounts,closeById};','return {renderAccount,updateProFields};');
  assert.notEqual(source,exposed);
  vm.runInNewContext(exposed,context);
  const user={id:7,account:'buyer',closed:false,system_admin:false,active:true,balance:1,teams:[],inventory:[],units:[],items:[],
    pro:{app:'rbc_helper',active:false,expires_at:null,server_time:'2026-11-03T08:00:00Z',revision:0,unredeemed_codes:1,audit:[]}};
  return {user,api:context.window.AccountManagement,render(value=user){context.window.AccountManagement.renderAccount(value);return detail.innerHTML;}};
}

test('global account forms remain siblings including Pro controls and inventory',()=>{
  const f=fixture();
  f.user.inventory=[{id:1,item_id:1,item__name:'Ticket',team__name:'Team',quantity:2}];
  f.user.items=[{id:2,name:'Gift',team__name:'Team'}];
  const html=f.render();
  let depth=0,count=0;
  for(const match of html.matchAll(/<\/?form\b[^>]*>/g)){
    if(match[0].startsWith('</')){depth--;assert.equal(depth,0,'form closes its own sibling');}
    else{depth++;count++;assert.equal(depth,1,'forms must never nest');}
  }
  assert.equal(depth,0);assert.equal(count,5);
  assert.match(html,/data-pro-form data-user="7" data-revision="0"/);
});

test('audit and identity data cannot inject active HTML',()=>{
  const f=fixture(),injection='<img src=x onerror=alert(1)>';
  f.user.account=injection;
  f.user.pro.audit=[{action:'extend',actor:injection,reason:injection,created_at:'2026-11-03T08:00:00Z',before_expires_at:null,after_expires_at:'2026-12-04T08:00:00Z'}];
  const html=f.render();
  assert.ok(!html.includes(injection));assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
});

test('inactive accounts expose audit without mutation controls',()=>{
  const f=fixture();f.user.active=false;
  const html=f.render();assert.ok(html.includes('操作审计'));assert.ok(!html.includes('data-pro-form'));
});

test('action switching disables hidden required inputs',()=>{
  const f=fixture();
  const days={disabled:false,required:true},date={disabled:true,required:false};
  const fields=[{dataset:{proField:'extend'},querySelectorAll:()=>[days]},
    {dataset:{proField:'set_expiry'},querySelectorAll:()=>[date]}];
  const form={elements:{action:{value:'set_expiry'}},querySelectorAll:()=>fields};
  f.api.updateProFields(form);
  assert.equal(fields[0].hidden,true);assert.equal(days.disabled,true);assert.equal(days.required,false);
  assert.equal(fields[1].hidden,false);assert.equal(date.disabled,false);assert.equal(date.required,true);
  form.elements.action.value='revoke';f.api.updateProFields(form);
  assert.ok(fields.every(field=>field.hidden));assert.equal(date.disabled,true);
});
