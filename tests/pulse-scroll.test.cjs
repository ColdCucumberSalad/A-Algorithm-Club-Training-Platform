const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function fixture(stops = Array.from({length:14}, (_, i) => i*100), options = {}) {
  const handlers = {}, timers = new Map(), frames = new Map(), calls = [];
  let clock = 0, next = 0, captured = null;
  const track = {
    dataset:{}, clientWidth:700, scrollWidth:1400, scrollLeft:350,
    classList:{add(){},remove(){},toggle(){}},
    addEventListener(type, handler, options) { handlers[type] = {handler,options}; },
    querySelectorAll:() => stops.map(left => ({getBoundingClientRect:() => ({left:40+left-track.scrollLeft})})),
    scrollTo(options) { calls.push(options); this.scrollLeft = options.left; },
    setPointerCapture(id) { captured = id; },
    hasPointerCapture:id => captured === id,
    releasePointerCapture() { captured = null; },
  };
  const view = require('../activity-view.js').create({}, {
    track, ResizeObserver:class {observe(){}},
    matchMedia:() => ({matches:true}), selectPulseDay(){},
    setTimeout(fn, delay) { const id = ++next; timers.set(id,{fn,at:clock+delay}); return id; },
    clearTimeout:id => timers.delete(id),
    requestAnimationFrame(fn) { const id = ++next; frames.set(id,fn); return id; },
    cancelAnimationFrame:id => frames.delete(id),
  });
  const refresh=view.wireHorizontalDateScroll(track,'.activity-month-section',options);
  const emit = (type, props = {}) => handlers[type].handler({type,target:track,preventDefault(){},...props});
  const advance = ms => {
    const until = clock+ms;
    while (true) {
      const due = [...timers].filter(([,t]) => t.at <= until).sort((a,b) => a[1].at-b[1].at)[0];
      if (!due) break;
      clock = due[1].at; timers.delete(due[0]); due[1].fn();
    }
    clock = until;
  };
  const finger = {identifier:1,clientX:300,clientY:40};
  const down = () => emit('touchstart',{changedTouches:[finger],touches:[finger]});
  const up = () => emit('touchend',{changedTouches:[finger],touches:[]});
  return {track,handlers,calls,emit,advance,down,up,finger,refresh};
}

for(const ending of ['pointerup','pointercancel','pointerleave','vertical'])test(`an inactive mouse ${ending} releases pending prefetch without blocking clicks`,()=>{
 let applied=0;
 const f=fixture(undefined,{snap(track){assert.equal(track.dataset.interacting,'false');applied++;return true;}});
 f.emit('pointerdown',{pointerId:7,pointerType:'mouse',button:0,clientX:300,clientY:40});
 assert.equal(f.track.dataset.interacting,'true');
 if(ending==='vertical')f.emit('pointermove',{pointerId:7,clientX:301,clientY:60});
 else f.emit(ending,{pointerId:7});
 let blocked=false;
 f.emit('click',{detail:1,preventDefault(){blocked=true;},stopImmediatePropagation(){blocked=true;}});
 assert.equal(blocked,false);assert.equal(applied,0);
 f.advance(200);
 assert.equal(applied,1);assert.equal(f.track.dataset.interacting,'false');
});

test('native touch takeover and a stationary finger never trigger snapping', () => {
  const f = fixture(); f.down(); f.calls.length = 0;
  f.emit('pointerdown',{pointerId:1,pointerType:'touch',button:0});
  f.emit('pointercancel',{pointerId:1});
  f.track.scrollLeft = 345;
  f.emit('scroll'); f.emit('scrollend'); f.advance(1000);
  assert.equal(f.calls.length,0);
  assert.equal(f.track.scrollLeft,345);
  assert.equal(f.handlers.touchmove.options.passive,true);
});

test('release waits for momentum to stop before aligning the first visible date', () => {
  const f = fixture(); f.down(); f.calls.length = 0; f.up();
  f.advance(100); f.track.scrollLeft = 425; f.emit('scroll');
  f.advance(150); f.track.scrollLeft = 465; f.emit('scroll');
  f.advance(199); assert.equal(f.calls.length,0);
  f.advance(1); assert.equal(f.calls.at(-1).left,400);
});

test('native scrollend snaps promptly after release, and another touch interrupts settling', () => {
  const f = fixture(); f.down(); f.up(); f.track.scrollLeft = 465;
  f.emit('scrollend'); assert.equal(f.calls.at(-1).left,400);
  f.track.scrollLeft = 445; f.down(); f.calls.length = 0;
  f.emit('scrollend'); f.advance(700);
  assert.equal(f.calls.length,0);
});

test('touch cancellation waits instead of forcing an immediate snap', () => {
  const f = fixture(); f.down(); f.calls.length = 0;
  f.emit('touchcancel',{changedTouches:[f.finger],touches:[]});
  assert.equal(f.calls.length,0); f.advance(200);
  assert.equal(f.calls.at(-1).left,300);
});

test('scroll events from snapping do not prevent later scrolls from settling', () => {
  const f = fixture(); f.emit('scrollend'); f.emit('scroll');
  f.advance(500); f.calls.length = 0;
  f.track.scrollLeft = 465; f.emit('scroll'); f.advance(200);
  assert.equal(f.calls.at(-1).left,400);
});

test('mouse dragging still follows the pointer and snaps on release', () => {
  const f = fixture();
  f.emit('pointerdown',{pointerId:7,pointerType:'mouse',button:0,clientX:300,clientY:40});
  f.emit('pointermove',{pointerId:7,clientX:180,clientY:40});
  f.emit('pointerup',{pointerId:7});
  assert.equal(f.track.scrollLeft,400);
  f.emit('click',{detail:1,preventDefault(){},stopImmediatePropagation(){}});
});

test('unequal month widths snap using visual positions across nested offset parents', () => {
  const f = fixture([0,115,251,366,502,638,753]);
  f.track.scrollLeft = 430; f.emit('scrollend');
  assert.equal(f.calls.at(-1).left,366);
  f.refresh(); f.advance(500);
  f.track.scrollLeft = 580; f.emit('scroll'); f.advance(200);
  assert.equal(f.calls.at(-1).left,502);
  f.advance(500); f.track.scrollLeft = 700; f.emit('scrollend');
  assert.equal(f.track.scrollLeft,700);
});

test('a heatmap that fits does not intercept dragging or disable date clicks', () => {
  const f = fixture(); f.track.scrollWidth = f.track.clientWidth;
  f.emit('pointerdown',{pointerId:7,pointerType:'mouse',button:0,clientX:300,clientY:40});
  f.emit('pointermove',{pointerId:7,clientX:180,clientY:40});
  f.emit('pointerup',{pointerId:7});
  let blocked = false;
  f.emit('click',{detail:1,preventDefault(){blocked=true;},stopImmediatePropagation(){blocked=true;}});
  assert.equal(f.calls.length,0); assert.equal(blocked,false);
});

test('continuous layout with repeated week positions keeps the final month reachable', () => {
  const f = fixture([0,0,100,100,200,200,300,400,500,600,700,800]);
  f.track.scrollLeft = 695; f.emit('scrollend');
  assert.equal(f.calls.at(-1).left,600);
  f.advance(500); f.track.scrollLeft = 700; f.emit('scrollend');
  assert.equal(f.track.scrollLeft,700);
});
