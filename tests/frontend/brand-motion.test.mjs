import test from 'node:test';
import assert from 'node:assert/strict';
import {initMotion, motionAllowed} from '../../src/submission/static/brand/motion.mjs';

function environment({reduced=false, observer=true}={}) {
  const win = new EventTarget();
  const media = Object.assign(new EventTarget(), {matches:reduced});
  const doc = Object.assign(new EventTarget(), {defaultView:win, hidden:false});
  const animations = [];
  const pulse = {animate() {const animation={state:'running',play(){this.state='running';},pause(){this.state='paused';},cancel(){this.state='cancelled';}};animations.push(animation);return animation;}};
  const loop={dataset:{},isConnected:true,hasAttribute:name=>name==='data-motion-loop',querySelectorAll:()=>[pulse]};
  doc.documentElement={};
  doc.querySelectorAll=()=>[loop];
  win.matchMedia=()=>media;
  win.getComputedStyle=()=>({getPropertyValue:()=>''});
  let intersections;
  if(observer)win.IntersectionObserver=class {constructor(fn){intersections=fn;}observe(){}unobserve(){}disconnect(){}};
  win.MutationObserver=class {observe(){}disconnect(){}};
  return {win,doc,loop,media,animations,show(){intersections?.([{target:loop,isIntersecting:true}]);}};
}

test('motion policy requires visibility and respects both pause controls',()=>{
  const state={reduced:false,hidden:false,visible:true,paused:false};
  assert.equal(motionAllowed(state),true);
  for(const [key,value] of [['reduced',true],['hidden',true],['visible',false],['paused',true]])assert.equal(motionAllowed({...state,[key]:value}),false);
});
test('BFCache restore restarts observer even after initial pageshow',()=>{
  const e=environment();initMotion(e.doc);
  e.win.dispatchEvent(new Event('pageshow'));
  e.win.dispatchEvent(new Event('pagehide'));
  assert.equal(e.animations[0].state,'cancelled');
  const restore=new Event('pageshow');Object.defineProperty(restore,'persisted',{value:true});
  e.win.dispatchEvent(restore);e.show();
  assert.equal(e.animations.length,2);
  assert.equal(e.animations[1].state,'running');
  initMotion(e.doc).dispose();
});
test('loop pauses offscreen, on hidden tab and explicit pause',()=>{
  const e=environment();const control=initMotion(e.doc);
  assert.equal(e.animations[0].state,'paused');e.show();assert.equal(e.animations[0].state,'running');
  e.doc.hidden=true;e.doc.dispatchEvent(new Event('visibilitychange'));assert.equal(e.animations[0].state,'paused');
  e.doc.hidden=false;e.loop.dataset.motionPaused='true';control.refresh();assert.equal(e.animations[0].state,'paused');
  e.loop.dataset.motionPaused='false';control.refresh();assert.equal(e.animations[0].state,'running');control.dispose();
});
test('no observer leaves a static fallback without infinite animation objects',()=>{
  const e=environment({observer:false});initMotion(e.doc);assert.equal(e.animations.length,0);
});
test('reduced motion avoids starting pulse animation objects',()=>{
  const e=environment({reduced:true});initMotion(e.doc);assert.equal(e.animations.length,0);
});
test('reveal is one-shot and system reduced motion cancels an entrance',async()=>{
  const e=environment();const calls=[];let intersect;
  const animation={finished:Promise.resolve(),cancelled:false,cancel(){this.cancelled=true;}};
  const heading={hasAttribute:name=>name==='data-reveal',querySelectorAll:()=>[],animate(frames,options){calls.push({frames,options});return animation;}};
  e.doc.querySelectorAll=()=>[heading];
  e.win.getComputedStyle=()=>({getPropertyValue:token=>({'--motion-distance':'14px','--motion-blur':'3px'}[token] || '')});
  e.win.IntersectionObserver=class {constructor(fn){intersect=fn;}observe(){}unobserve(){}disconnect(){}};
  const control=initMotion(e.doc);
  intersect([{target:heading,isIntersecting:true}]);
  intersect([{target:heading,isIntersecting:true}]);
  assert.equal(calls.length,1);assert.equal(calls[0].options.duration,650);
  assert.equal(calls[0].frames[1].opacity,1);
  assert.equal(calls[0].frames[0].transform,'translateY(14px)');
  assert.equal(calls[0].frames[0].filter,'blur(3px)');
  e.media.matches=true;e.media.dispatchEvent(new Event('change'));
  assert.equal(animation.cancelled,true);
  await Promise.resolve();control.dispose();
});
test('removed demo nodes release animations during subtree updates',()=>{
  const e=environment();let mutate;
  e.win.MutationObserver=class {constructor(fn){mutate=fn;}observe(){}disconnect(){}};
  const control=initMotion(e.doc);e.show();
  e.loop.isConnected=false;mutate([{addedNodes:[{nodeType:3}]}]);
  assert.equal(e.animations[0].state,'cancelled');
  control.dispose();
});
