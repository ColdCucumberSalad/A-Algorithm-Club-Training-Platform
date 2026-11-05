const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../currency-admin.js'),'utf8');
function fixture(saved){
 let value='',keys=['','rbc-pendant'];
 const gift={get value(){return value},set value(next){value=keys.includes(next)?next:''},set innerHTML(html){keys=[...html.matchAll(/value="([^"]*)"/g)].map(m=>m[1]);value=keys[0]}};
 const elements={'#itemGiftBadge':gift,'#itemType':{value:'physical'},'#shopCosmeticKey':{value:''},'#shopCosmeticFields':{},'#shopCosmeticHint':{},'.cosmetic-stock-preview img':{}};
 const modal={querySelector:key=>elements[key]},context={modal,item:{gift_badge_key:saved},escape:x=>x,window:{CosmeticMedia:{safe:()=>false}}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('    let giftOptionsLoaded='),source.indexOf("    modal.querySelector('#itemType').addEventListener('change',updateCosmeticFields)")),context);
 return {gift,refresh(){vm.runInContext('updateCosmeticFields()',context)},catalog(value){modal.assetCatalog=value}};
}
test('late catalog loading restores saved custom gifts and preserves later explicit no-gift selection',()=>{
 const f=fixture('garden');f.refresh();assert.equal(f.gift.value,'');
 f.catalog([{kind:'badge',key:'garden',name:'Garden',is_active:true}]);f.refresh();assert.equal(f.gift.value,'garden');
 f.gift.value='';f.refresh();assert.equal(f.gift.value,'');
});
test('editing a product keeps its saved gift even if that resource was deactivated',()=>{
 const f=fixture('garden');f.catalog([{kind:'badge',key:'garden',name:'Garden',is_active:false}]);f.refresh();assert.equal(f.gift.value,'garden');
});
