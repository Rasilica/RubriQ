import test from 'node:test';
import assert from 'node:assert/strict';
import {createSettingsAPI,createKeyStatus,credentialChoice,mountKeySettings} from '../../src/submission/static/prepare/ai-settings.mjs';
const statuses=(configured=true)=>({available:true,backend:'keychain',providers:['gemini','openai','anthropic','billingai'].map(provider=>({provider,configured}))});
test('settings transport is local and status only; save/delete use exact scoped endpoints',async()=>{
 const calls=[];const api=createSettingsAPI(async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({success:true,data:statuses()})};});
 await api.status();await api.save('gemini','secret-key');await api.remove('gemini');
 assert.deepEqual(calls.map(c=>[c.url,c.options.method]),[['/api/ai-settings','GET'],['/api/ai-settings/gemini','PUT'],['/api/ai-settings/gemini','DELETE']]);
 for(const {options} of calls){assert.equal(options.headers['X-Local-Client'],'prepare');assert.equal(options.cache,'no-store');assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');}
 assert.deepEqual(JSON.parse(calls[1].options.body),{api_key:'secret-key'});assert.equal(calls[2].options.body,undefined);
 assert.throws(()=>api.save('ollama','secret'));assert.throws(()=>api.save('gemini','bad key'));
});
test('status store fails closed, projects only metadata, and manual override wins',()=>{
 const store=createKeyStatus();assert.throws(()=>credentialChoice('gemini','',store));
 let changes=0;const off=store.subscribe(()=>changes++);store.update({...statuses(),api_key:'omit-key'});
 assert.equal(JSON.stringify(store.snapshot()).includes('omit-key'),false);assert.deepEqual(credentialChoice('gemini','',store),{useSavedKey:true,apiKey:undefined});
 assert.deepEqual(credentialChoice('gemini','override',store),{useSavedKey:false,apiKey:'override'});assert.throws(()=>credentialChoice('gemini','bad key',store));
 assert.deepEqual(credentialChoice('ollama','',store),{useSavedKey:false,apiKey:undefined});
 store.update({available:false,backend:null,providers:[]});assert.throws(()=>credentialChoice('gemini','',store));
 assert.throws(()=>store.update({available:true,providers:[{provider:'gemini',configured:'yes'}]}));assert.equal(store.configured('gemini'),false);off();store.update(statuses());assert.equal(changes,3);
});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(api){
 const nodes=new Map();
 function element(tag,className='',textContent=''){
  const callbacks=new Map();return {tag,className,textContent,value:'',children:[],disabled:false,
   set id(value){this.nodeId=value;nodes.set(value,this);},get id(){return this.nodeId;},
   append(...children){this.children.push(...children);},setAttribute(){},querySelector(tag){return this.children.find(child=>child.tag===tag);},
   addEventListener(event,callback){callbacks.set(event,callback);},click(){if(!this.disabled)callbacks.get('click')?.();}
  };
 }
 const ui={element,button(label,callback){const node=element('button','',label);node.addEventListener('click',callback);return node;},field({id,label}){const row=element('div');const input=element('input');input.id=id;row.append(element('label','',label),input);return row;}};
 const mounted=mountKeySettings({ui,api});return {mounted,get:id=>nodes.get(id)};
}
test('settings accessible without a session, clears passwords before pending writes, replaces and deletes status only',async()=>{
 let stored=false,resolve,calls=0;
 const h=harness({status:async()=>statuses(stored),save:(_provider,key)=>{calls++;assert.equal(key,'replacement');return new Promise(yes=>{resolve=()=>{stored=true;yes();};});},remove:async()=>{stored=false;}});await tick();
 assert.equal(h.mounted.panel.tag,'details');assert.equal(h.mounted.panel.children[0].tag,'summary');const input=h.get('settings-gemini-key');assert.equal(input.type,'password');assert.equal(input.autocomplete,'off');assert.equal(h.get('settings-gemini-delete').disabled,true);
 input.value='replacement';h.get('settings-gemini-save').click();assert.equal(input.value,'');assert.equal(calls,1);h.get('settings-gemini-save').click();assert.equal(calls,1);resolve();await tick();assert.equal(h.mounted.status.configured('gemini'),true);assert.equal(h.get('settings-gemini-delete').disabled,false);
 input.value='replacement';h.get('settings-gemini-save').click();assert.equal(input.value,'');resolve();await tick();assert.equal(calls,2);
 input.value='discard-this';h.get('settings-gemini-delete').click();assert.equal(input.value,'');await tick();assert.equal(h.mounted.status.configured('gemini'),false);assert.equal(h.get('settings-gemini-delete').disabled,true);
 input.value='clear-on-pagehide';h.mounted.clearInputs();assert.equal(input.value,'');input.value='clear-on-dispose';h.mounted.dispose();assert.equal(input.value,'');assert.equal(input.disabled,true);
});
test('unavailable store and failed writes fail closed without displaying secrets; explicit refresh recovers',async()=>{
 let available=false;
 const h=harness({status:async()=>available?statuses():{available:false,backend:null,providers:[]},save:async()=>{throw new Error('secret-response');}});await tick();
 assert.equal(h.get('settings-gemini-save').disabled,true);assert.match(h.get('ai-settings-status').textContent,/사용할 수 없습니다/);assert.equal(h.get('ai-settings-refresh').disabled,false);
 available=true;h.get('ai-settings-refresh').click();await tick();h.get('settings-gemini-key').value='secret-response';h.get('settings-gemini-save').click();await tick();assert.equal(h.get('settings-gemini-key').value,'');assert.equal(h.get('ai-settings-status').textContent.includes('secret-response'),false);assert.equal(h.mounted.status.configured('gemini'),false);assert.equal(h.get('ai-settings-refresh').disabled,false);
 h.get('ai-settings-refresh').click();await tick();assert.equal(h.mounted.status.configured('gemini'),true);
});
