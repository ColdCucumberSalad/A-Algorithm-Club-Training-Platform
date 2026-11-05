const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../currency.js'),'utf8');
const start=source.indexOf('  function applyShopCategory('),end=source.indexOf('  function bindShopCategories(',start);
function fixture(kinds){
 const cards=kinds.map(kind=>({dataset:{shopKind:kind},hidden:false}));
 const buttons=['all','decorations'].map(category=>({dataset:{shopCategory:category},classList:{toggle(){}},setAttribute(key,value){this[key]=value;}}));
 const empty={hidden:true},container={dataset:{},querySelectorAll(selector){return selector==='[data-shop-kind]'?cards:buttons;},querySelector(){return empty;}};
 const context={};vm.createContext(context);vm.runInContext(source.slice(start,end),context);
 return {...context,cards,buttons,empty,container};
}
test('decorations shows titles, badges and themes without rebuilding or reloading cards',()=>{
 const f=fixture(['general','title','badge','theme','consumable']);
 f.applyShopCategory(f.container,'decorations');assert.deepEqual(f.cards.map(c=>c.hidden),[true,false,false,false,true]);
 assert.equal(f.container.dataset.shopCategory,'decorations');assert.equal(f.buttons[1]['aria-pressed'],'true');
 f.applyShopCategory(f.container,'all');assert.ok(f.cards.every(c=>!c.hidden));assert.equal(f.empty.hidden,true);
});
test('an empty decorations category displays its empty state',()=>{
 const f=fixture(['physical','redeem_code']);f.applyShopCategory(f.container,'decorations');assert.equal(f.empty.hidden,false);
});

test('physical, redeem and tools filters keep their own inventory kinds',()=>{
 const f=fixture(['physical','redeem_code','makeup_ticket','consumable','general','cosmetic']);
 for(const [category,expected]of [['physical',[false,true,true,true,true,true]],['redeem',[true,false,true,true,true,true]],['tools',[true,true,false,false,false,true]]]){f.applyShopCategory(f.container,category);assert.deepEqual(f.cards.map(c=>c.hidden),expected);}
});
