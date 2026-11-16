import test from 'node:test';
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
const hooks=registerHooks({resolve(specifier,context,nextResolve){return nextResolve(specifier==='/review-assets/primitives.mjs'?new URL('../../src/submission/static/review/primitives.mjs',import.meta.url).href:specifier,context);}});
const {mountLibrary}=await import('../../src/submission/static/prepare/library.mjs');
hooks.deregister();
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const item={saved_id:'saved-1',project_name:'보관',saved_at:'2026-10-10T00:00:00Z'};
const listing={items:[item],total:1,page:1,page_size:20};
const response=data=>({ok:true,status:200,json:async()=>({success:true,data})});
function harness(t,request){
 const original=globalThis.document;const nodes=new Map();let focused;
 function node(tag='div'){
  const listeners=new Map();return {tag,children:[],textContent:'',disabled:false,isConnected:true,open:false,
   append(...children){this.children.push(...children);},replaceChildren(...children){this.children=[...children];},setAttribute(name,value){this[name]=value;},
   addEventListener(name,fn){listeners.set(name,[...(listeners.get(name)??[]),fn]);},removeEventListener(name,fn){listeners.set(name,(listeners.get(name)??[]).filter(f=>f!==fn));},emit(name){for(const fn of listeners.get(name)??[])fn({preventDefault(){}});},click(){if(!this.disabled)this.emit('click');},focus(){focused=this;},showModal(){this.open=true;},close(){this.open=false;this.emit('close');}};
 }
 for(const id of ['library-list','library-status','library-pagination','library-refresh','library-delete-dialog','library-delete-cancel','library-delete-confirm','library-delete-name','save-status'])nodes.set(id,node());
 globalThis.document={createElement:node,querySelector:id=>nodes.get(id.slice(1))};t.after(()=>{globalThis.document=original;});
 const calls=[];t.mock.method(globalThis,'fetch',async(url,options)=>{calls.push({url,options});return request?request(url,options):response(url.includes('?')?listing:{...item,already_saved:false,has_semantic_archive:true,has_check:true});});
 let active={session_id:'session',access_token:'token'},state={allowed:true},canOpen=true;const opened=[],busy=[];
 const mounted=mountLibrary({getSession:()=>active,getSaveState:()=>state,canOpen:()=>canOpen,acceptSession:value=>opened.push(value),setOpening:value=>busy.push(value)});
 const get=id=>nodes.get(id);const button=node('button');
 return {mounted,calls,get,button,opened,busy,setState:value=>{state=value;},setSession:value=>{active=value;},setCanOpen:value=>{canOpen=value;},focused:()=>focused};
}
test('library mount lists without reopening; blocked edits cannot dispatch save; confirmed save has no payload',async t=>{
 const h=harness(t);await tick();assert.equal(h.calls.length,1);assert.equal(h.calls[0].options.method,'GET');assert.equal(h.opened.length,0);
 h.setState({allowed:false,reason:'pending confirmation'});await h.mounted.save(h.button);assert.equal(h.calls.length,1);assert.equal(h.get('save-status').children[0].role,'alert');
 h.setState({allowed:true});await h.mounted.save(h.button);await tick();const call=h.calls.find(c=>c.url.endsWith('/save'));assert.ok(call);assert.equal(call.options.method,'POST');assert.equal(call.options.body,undefined);assert.equal(call.options.cache,'no-store');assert.equal(h.button.disabled,false);
 h.mounted.dispose();
});
test('changed sessions discard pending save receipt and keep dirty save action blocked',async t=>{
 let resolve;const h=harness(t,url=>url.includes('?')?response(listing):new Promise(yes=>{resolve=yes;}));await tick();
 const pending=h.mounted.save(h.button);h.setSession({session_id:'replacement'});h.mounted.sessionChanged();resolve(response({...item,already_saved:false}));await pending;assert.equal(h.calls.filter(c=>c.url.includes('?')).length,1);
 h.setSession(null);await h.mounted.save(h.button);assert.equal(h.calls.length,2);h.mounted.dispose();
});
test('save failure restores controls according to current unsent edit state',async t=>{
 let reject;const h=harness(t,url=>url.includes('?')?response(listing):new Promise((_yes,no)=>{reject=no;}));await tick();
 const pending=h.mounted.save(h.button);h.setState({allowed:false,reason:'unsent'});reject(new Error('network'));await pending;
 assert.equal(h.button.disabled,true);assert.equal(h.get('save-status').children[0].role,'alert');h.mounted.dispose();
});
test('explicit open is blocked by a live session then accepts a validated document-only archive',async t=>{
 const role=name=>({role:name,document:null,extraction_status:'failed',rendering_status:'not_started',warnings:[],preview_page_count:null,artifact_kind:null});
 const stored={...item,session_id:'reopened',access_token:'new-token',expires_at:'2099-01-01',guide:role('guide'),report:role('report'),saved_environment:[],current_environment:[]};
 const h=harness(t,url=>response(url.includes('?')?listing:stored));await tick();const open=h.get('library-list').children[0].children[1].children[0];
 h.setCanOpen(false);open.click();await tick();assert.equal(h.calls.length,1);h.setCanOpen(true);open.click();await tick();assert.deepEqual(h.opened,[stored]);assert.deepEqual(h.busy,[true,false]);h.mounted.dispose();
});
test('saved deletion requires explicit dialog confirmation and restores refresh focus',async t=>{
 const h=harness(t,(url,options)=>response(options.method==='DELETE'?{deleted:true}:listing));await tick();const remove=h.get('library-list').children[0].children[1].children[1];
 remove.click();assert.equal(h.get('library-delete-dialog').open,true);assert.equal(h.focused(),h.get('library-delete-cancel'));h.get('library-delete-cancel').click();assert.equal(h.focused(),remove);assert.equal(h.calls.length,1);
 remove.click();h.get('library-delete-confirm').click();await tick();await tick();assert.equal(h.get('library-delete-dialog').open,false);assert.equal(h.calls.filter(c=>c.options.method==='DELETE').length,1);assert.equal(h.focused(),h.get('library-refresh'));h.mounted.dispose();
});
