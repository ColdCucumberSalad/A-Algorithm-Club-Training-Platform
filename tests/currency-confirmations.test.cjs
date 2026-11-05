const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup({confirmed = false, tickets = 2, cosmeticFailure = false, duplicate = false, cosmeticGate} = {}) {
  const calls = [], dialogs = [], synced = [];let revision=0;
  const context = {
    console, document: {querySelector: () => null, getElementById: () => null},
    window: {
      SpecialThemes:{sync:data=>synced.push(data),version:()=>revision,isCurrent:value=>value===revision},
      clubDialog: {confirm: async options => {dialogs.push(options); return confirmed;}, notice: async options => dialogs.push(options)},
      clubApi: {
        requestId: () => 'test-request',
        request: async (url, options = {}) => {
          calls.push({url, options});
          if(url==='/api/profile/cosmetics'){
            if(cosmeticGate)await cosmeticGate;
            if(cosmeticFailure)throw Error('offline');
            return {ok:true,json:async()=>({themes:[{key:'taffy'}],badges:[{key:'taffy'}],frames:[{key:'taffy-goggles'}]})};
          }
          let data = url.includes('inventory') ? {inventory:[{item_type:'makeup_ticket', quantity:tickets}]} :
            url.includes('makeup') ? {success:true, week_id:14} :
            url.includes('purchase') ? {balance:7, total_price:3, duplicate} : {balance:10, can_purchase:true};
          return {ok:true, json:async () => data};
        }
      }
    }
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require.resolve('../currency.js'), 'utf8'), context);
  return {module:context.window.CurrencyModule, calls, dialogs, synced,newSelection:()=>revision++};
}

test('canceling ticket use never spends a ticket or opens permission', async () => {
  const state = setup();
  assert.equal(await state.module.performMakeupCheckin('2026-10-28'), false);
  assert.equal(state.calls.filter(call => call.options.method === 'POST').length, 0);
  assert.match(state.dialogs[0].text, /补签券 ×1/);
});
test('confirmed ticket use sends exactly one permission request', async () => {
  const state = setup({confirmed:true});
  await state.module.performMakeupCheckin('2026-10-28');
  assert.equal(state.calls.filter(call => call.options.method === 'POST').length, 1);
});
test('previously unlocked date does not prompt for another ticket', async () => {
  const state = setup({tickets:0});
  await state.module.performMakeupCheckin('2026-10-28', {alreadyOpen:true});
  assert.equal(state.dialogs.length, 0);
  assert.equal(state.calls.filter(call => call.options.method === 'POST').length, 1);
});
test('empty backpack does not send a ticket consumption request', async () => {
  const state = setup({tickets:0});
  await state.module.performMakeupCheckin('2026-10-28');
  assert.equal(state.calls.filter(call => call.options.method === 'POST').length, 0);
  assert.equal(state.dialogs[0].title, '补签券不足');
});
test('canceling purchase never sends a purchase request', async () => {
  const state = setup();
  await state.module.purchaseItem(1, 1, {name:'补签券', price:3});
  assert.equal(state.calls.length, 0);
});
test('confirmed purchase keeps the idempotency token and reports success in site dialog', async () => {
  const state = setup({confirmed:true});
  assert.equal(await state.module.purchaseItem(1, 1, {name:'补签券', price:3}), true);
  assert.equal(state.calls.length, 1);
  assert.equal(JSON.parse(state.calls[0].options.body).request_id, 'test-request');
  assert.equal(state.dialogs.at(-1).title, '购买成功');
});


test('multi-use card confirms the combined benefit and sends the selected quantity', async () => {
  const state = setup({confirmed:true});
  assert.equal(await state.module.purchaseItem(7, 4, {name:'体验券', price:3, allow_multiple_purchase:true}), true);
  assert.equal(JSON.parse(state.calls[0].options.body).quantity, 4);
  assert.match(state.dialogs[0].text, /一张可用 4 次/);
  assert.match(state.dialogs[0].text, /需支付 12 RBC/);
});

for(const kind of ['title','theme','badge','frame','cosmetic'])test('ordinary '+kind+' purchase refreshes the shared cosmetic library',async()=>{
 const state=setup({confirmed:true});
 assert.equal(await state.module.purchaseItem(5,1,{name:'Cosmetic',price:3,item_type:kind}),true);
 assert.deepEqual(state.calls.map(call=>call.url),['/api/currency/shop/purchase','/api/profile/cosmetics']);
 assert.equal(state.synced.length,1);assert.equal(state.synced[0].themes[0].key,'taffy');
});
test('a confirmed duplicate purchase also refreshes the library',async()=>{
 const state=setup({confirmed:true,duplicate:true});
 assert.equal(await state.module.purchaseItem(5,1,{name:'Theme',price:3,item_type:'theme'}),true);
 assert.equal(state.synced.length,1);assert.match(state.dialogs.at(-1).text,/未重复扣款/);
});
test('cosmetic refresh failure preserves the confirmed purchase result and does not retry payment',async()=>{
 const state=setup({confirmed:true,cosmeticFailure:true});
 assert.equal(await state.module.purchaseItem(5,1,{name:'Theme',price:3,item_type:'theme'}),true);
 assert.equal(state.calls.filter(call=>call.options.method==='POST').length,1);
 assert.equal(state.dialogs.at(-1).title,'购买成功');assert.match(state.dialogs.at(-1).text,/外观列表暂未刷新/);
});

test('a delayed post-purchase library read cannot override a newer selection',async()=>{
 let finish;const gate=new Promise(resolve=>finish=resolve),state=setup({confirmed:true,cosmeticGate:gate});
 const purchase=state.module.purchaseItem(5,1,{name:'Theme',price:3,item_type:'theme'});
 await new Promise(resolve=>setImmediate(resolve));state.newSelection();finish();
 assert.equal(await purchase,true);assert.equal(state.synced.length,0);assert.equal(state.dialogs.at(-1).title,'购买成功');
});
