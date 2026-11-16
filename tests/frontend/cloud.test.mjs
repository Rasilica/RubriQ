import test from 'node:test';
import assert from 'node:assert/strict';
import {cloudPreview,validateCloudRewrite,createCloudRequest} from '../../src/submission/static/prepare/newcloud.mjs';
import {createResources} from '../../src/submission/static/prepare/state.mjs';
import {createAPI} from '../../src/submission/static/prepare/api.mjs';
const block={block_id:'b1',raw_text:'😀 이 수치는 42입니다.'};
const source='a'.repeat(64);
const preview=()=>cloudPreview({block,source,provider:'gemini',model:'service-model',text:block.raw_text,start:0,end:block.raw_text.length});
const result=context=>({provider:context.provider,model:context.model,source_sha256:source,block_id:'b1',...context.range,original:context.original,suggestion:'수치는 42입니다. 😀',llm_executed:true,warnings:[]});
test('preview is immutable exact Unicode context and accepts explicit providers only',()=>{
  const value=preview();assert.equal(value.original,block.raw_text);assert.equal(value.range.end,[...block.raw_text].length);assert.equal(Object.isFrozen(value),true);assert.equal(Object.isFrozen(value.range),true);assert.equal(Object.isFrozen(value.block),true);
  for(const provider of ['gemini','openai','anthropic'])assert.equal(cloudPreview({...value,text:block.raw_text,start:0,end:block.raw_text.length,provider}).provider,provider);
  for(const patch of [{provider:''},{provider:'ollama'},{model:''},{model:'a'.repeat(201)},{model:'bad/model'},{model:'공백 모델'},{model:'-start'},{source:'invalid'},{text:'changed'},{start:1,end:2},{start:0,end:0},{start:-1,end:1},{end:100}])assert.throws(()=>cloudPreview({block,source,provider:'gemini',model:'service-model',text:block.raw_text,start:0,end:block.raw_text.length,...patch}));
  for(const count of [4000,4001]){const raw='😀'.repeat(count);const action=()=>cloudPreview({block:{...block,raw_text:raw},source,provider:'openai',model:'m',text:raw,start:0,end:raw.length});if(count===4000)assert.equal(action().range.end,4000);else assert.throws(action);}
});
test('cloud response is source/provider/model/range bound and display fields bounded',()=>{
  const context=preview();
  assert.equal(validateCloudRewrite(result(context),context).suggestion,'수치는 42입니다. 😀');
  for(const patch of [{provider:'openai'},{model:'different'},{source_sha256:'b'.repeat(64)},{block_id:'b2'},{start:1},{end:100},{original:'different'},{suggestion:''},{suggestion:42},{suggestion:'a'.repeat(8001)},{llm_executed:false},{warnings:'bad'},{warnings:['a'.repeat(1001)]},{warnings:Array(21).fill('warning')},{usage:'bad'},{usage:[]},{usage:{input_tokens:-1,output_tokens:1}},{usage:{input_tokens:1.5,output_tokens:1}},{usage:{input_tokens:1,output_tokens:Number.MAX_SAFE_INTEGER+1}},{usage:{input_tokens:1}}])assert.throws(()=>validateCloudRewrite({...result(context),...patch},context));
});
test('cloud API key appears only in request header; consent and source binding travel in JSON',async()=>{
  let call;const api=createAPI(async(path,options)=>{call={path,options};return {ok:true,json:async()=>({success:true,data:{}})};});
  const body={block_id:'b1',start:0,end:3,provider:'anthropic',model:'model',consent:true,source_sha256:source};const signal=new AbortController().signal;
  await api.cloudRewrite({session_id:'id',access_token:'session-secret'},'report',body,{apiKey:'key-secret',signal});
  assert.equal(call.path,'/api/document-pairs/id/report/cloud-rewrite');assert.equal(call.options.headers['X-AI-API-Key'],'key-secret');assert.equal(call.options.headers['X-Session-Token'],'session-secret');assert.equal(call.options.headers['X-Local-Client'],'prepare');assert.equal(call.options.method,'POST');assert.equal(call.options.signal,signal);assert.deepEqual(JSON.parse(call.options.body),body);
  for(const value of [call.path,call.options.body])assert.equal(value.includes('key-secret'),false);
  assert.equal(call.options.credentials,'omit');assert.equal(call.options.cache,'no-store');assert.equal(call.options.redirect,'error');
});
test('consent is mandatory, paid requests cannot duplicate or retry automatically',async()=>{
  const states=[];const calls=[];let resolve;const resources=createResources();
  const request=createCloudRequest({resources,request:(context,key,signal)=>{calls.push({context,key,signal});return new Promise(yes=>{resolve=yes;});},onState:value=>states.push(value)});
  const context=preview();assert.throws(()=>request.run(context,'key',false));
  for(const key of ['', 'a'.repeat(513),'space key','key\nvalue','한글'])assert.throws(()=>request.run(context,key,true));
  const first=request.run(context,'key',true);assert.throws(()=>request.run(context,'key',true));resolve(result(context));await first;
  assert.throws(()=>request.run(context,'key',true));assert.equal(calls.length,1);assert.equal(states.at(-1).status,'complete');assert.equal(JSON.stringify(states).includes('key'),false);
});
test('stale, failed and malformed responses do not leak key or revive invalidated context',async()=>{
  const resources=createResources();const states=[];let resolve,reject,signal;
  const request=createCloudRequest({resources,request:(_,key,abort)=>{signal=abort;return new Promise((yes,no)=>{resolve=yes;reject=no;});},onState:value=>states.push(value)});
  let context=preview();const first=request.run(context,'secret',true);resources.begin('cloud-rewrite');assert.equal(signal.aborted,true);resolve(result(context));await first;assert.deepEqual(states.map(x=>x.status),['running']);
  context=preview();const second=request.run(context,'secret',true);resources.clear();reject(new Error('secret'));await second;assert.deepEqual(states.map(x=>x.status),['running','running']);
  context=preview();const failed=request.run(context,'secret',true);reject(new Error('secret'));await failed;assert.deepEqual(states.at(-1),{status:'error'});assert.throws(()=>request.run(context,'secret',true));
  context=preview();const malformed=request.run(context,'secret',true);resolve({...result(context),model:'wrong'});await malformed;assert.deepEqual(states.at(-1),{status:'error'});
});

import {mountCloudPanel} from '../../src/submission/static/prepare/newcloud.mjs';
function panelHarness(api,keyStatus){
  const nodes=new Map();
  function element(tag,className='',text=''){
    const listeners=new Map();const node={tag,className,textContent:text,value:'',checked:false,disabled:false,children:[],attributes:{},selectionStart:0,selectionEnd:0,
      set id(value){this.nodeId=value;nodes.set(value,this);},get id(){return this.nodeId;},
      append(...children){this.children.push(...children);},replaceChildren(...children){this.children=[...children];},
      setAttribute(name,value){this.attributes[name]=value;},
      querySelector(tag){return this.children.find(child=>child.tag===tag);},
      addEventListener(name,fn){listeners.set(name,[...(listeners.get(name)??[]),fn]);},removeEventListener(name,fn){listeners.set(name,(listeners.get(name)??[]).filter(item=>item!==fn));},
      emit(name){for(const fn of listeners.get(name)??[])fn();},click(){if(!this.disabled)this.emit('click');},
    };return node;
  }
  const button=(label,action)=>{const node=element('button','',label);node.addEventListener('click',action);return node;};
  const field=({id,label,options,onChange})=>{const node=element('div');const control=element(options?'select':'input');control.options=options;control.id=id;control.addEventListener(options?'change':'input',()=>onChange(control.value));node.append(element('label','',label),control);return node;};
  const text=element('textarea');text.value=block.raw_text;text.selectionEnd=block.raw_text.length;
  const resources=createResources();const mounted=mountCloudPanel({ui:{element,button,field},api,keyStatus,resources,session:{session_id:'s',access_token:'token'},role:'report',doc:{source:{content_sha256:source}},block,text});
  const change=(id,value)=>{const node=nodes.get(id);node.value=value;node.emit(node.tag==='select'?'change':'input');};
  const fill=()=>{change('cloud-provider','gemini');change('cloud-model','service-model');change('cloud-api-key','secret-api-key');};
  const contents=node=>[node.textContent,...node.children.map(contents)].join(' ');
  const confirm=()=>{nodes.get('cloud-preview-button').click();nodes.get('cloud-consent').checked=true;nodes.get('cloud-consent').emit('change');};
  return {nodes,text,resources,mounted,change,fill,contents,confirm};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('panel requires preview and consent, clears password at submit, renders literal suggestions without changing source',async()=>{
  let calls=0,resolve;const h=panelHarness({cloudRewrite:async(_session,role,body,options)=>{calls++;assert.equal(role,'report');assert.equal(options.apiKey,'secret-api-key');assert.equal(body.consent,true);return new Promise(yes=>{resolve=yes;});}});
  const get=id=>h.nodes.get(id);assert.equal(get('cloud-api-key').type,'password');assert.equal(get('cloud-api-key').autocomplete,'off');assert.equal(get('cloud-model').value,'');assert.equal(get('cloud-submit').disabled,true);
  get('cloud-preview-button').click();assert.match(h.contents(get('cloud-result')),/제공자·모델 ID와 사용할 키/);assert.equal(calls,0);
  h.fill();get('cloud-preview-button').click();assert.equal(calls,0);assert.match(h.contents(get('cloud-preview')),/Gemini · service-model · 선택 문구/);assert.match(h.contents(get('cloud-preview')),/😀 이 수치는 42입니다/);assert.equal(get('cloud-submit').disabled,true);
  get('cloud-consent').checked=true;get('cloud-consent').emit('change');assert.equal(get('cloud-submit').disabled,false);get('cloud-submit').click();assert.equal(get('cloud-api-key').value,'');assert.equal(get('cloud-submit').disabled,true);get('cloud-submit').click();assert.equal(calls,1);
  resolve({...result(preview()),suggestion:'<script>literal text</script>',usage:{input_tokens:12,output_tokens:0}});await tick();assert.match(h.contents(get('cloud-result')),/<script>literal text<\/script>/);assert.match(h.contents(get('cloud-result')),/이 윤문 기능은 AI 의미 검사를 수행하지 않습니다/);assert.match(h.contents(get('cloud-result')),/입력 12토큰 · 출력 0토큰/);assert.equal(h.text.value,block.raw_text);assert.equal(get('cloud-submit').disabled,true);assert.equal(h.contents(h.mounted.panel).includes('secret-api-key'),false);
});
test('provider/model/selection/input transitions invalidate consent; disposal clears key and late result',async()=>{
  let resolve,signal;const h=panelHarness({cloudRewrite:(_s,_r,_b,options)=>{signal=options.signal;return new Promise(yes=>{resolve=yes;});}});const get=id=>h.nodes.get(id);
  h.fill();h.confirm();h.text.emit('select');assert.equal(get('cloud-submit').disabled,false);
  h.text.selectionStart=2;h.text.emit('select');assert.equal(get('cloud-submit').disabled,true);assert.equal(get('cloud-preview').children.length,0);
  h.text.selectionStart=0;h.confirm();h.change('cloud-model','changed');assert.equal(get('cloud-submit').disabled,true);assert.equal(get('cloud-consent').checked,false);
  h.change('cloud-model','service-model');h.confirm();h.change('cloud-provider','openai');assert.equal(get('cloud-api-key').value,'');assert.equal(get('cloud-preview').children.length,0);
  h.fill();h.confirm();h.text.value='changed';h.text.emit('input');assert.equal(get('cloud-submit').disabled,true);h.text.value=block.raw_text;
  h.confirm();h.text.selectionStart=1;h.text.selectionEnd=2;h.text.emit('select');assert.equal(get('cloud-submit').disabled,true);h.text.selectionStart=0;h.text.selectionEnd=block.raw_text.length;
  h.confirm();get('cloud-submit').click();h.change('cloud-api-key','replacement-secret');assert.equal(signal.aborted,true);h.mounted.dispose();assert.equal(get('cloud-api-key').value,'');resolve(result(preview()));await tick();assert.equal(get('cloud-result').children.length,0);
});
test('panel errors require a new preview and consent and never expose provider errors or echoed keys',async()=>{
  let calls=0;const h=panelHarness({cloudRewrite:async()=>{calls++;throw new Error('secret-api-key');}});const get=id=>h.nodes.get(id);
  h.fill();h.confirm();get('cloud-submit').click();await tick();assert.match(h.contents(get('cloud-result')),/다시 요청하면 비용/);assert.equal(h.contents(get('cloud-result')).includes('secret-api-key'),false);get('cloud-submit').click();assert.equal(calls,1);
  h.change('cloud-api-key','secret-api-key');assert.equal(get('cloud-submit').disabled,true);h.confirm();get('cloud-submit').click();await tick();assert.equal(calls,2);
  const leak=panelHarness({cloudRewrite:async()=>({...result(preview()),suggestion:'secret-api-key'})});leak.fill();leak.confirm();leak.nodes.get('cloud-submit').click();await tick();assert.match(leak.contents(leak.nodes.get('cloud-result')),/다시 요청하면 비용/);
});

test('optional usage is validated and key bound permits exactly 512 printable characters',async()=>{
 const context=preview();assert.deepEqual(validateCloudRewrite({...result(context),usage:{input_tokens:null,output_tokens:42}},context).usage,{input_tokens:null,output_tokens:42});assert.equal(validateCloudRewrite({...result(context),usage:null},context).usage,null);
 const request=createCloudRequest({resources:createResources(),request:async()=>result(context),onState:()=>{}});await request.run(context,'a'.repeat(512),true);
 const h=panelHarness({cloudRewrite:async()=>({...result(preview()),usage:{input_tokens:null,output_tokens:null}})});h.fill();h.confirm();h.nodes.get('cloud-submit').click();await tick();assert.equal(h.contents(h.nodes.get('cloud-result')).includes('제공자 응답 사용량'),false);
});

test('unchanged selection event during submission preserves request and visible failure',async()=>{
  let reject,signal,calls=0;const h=panelHarness({cloudRewrite:(_s,_r,_b,options)=>{calls++;signal=options.signal;return new Promise((_resolve,no)=>{reject=no;});}});
  h.fill();h.confirm();h.nodes.get('cloud-submit').click();h.text.emit('select');
  assert.equal(signal.aborted,false);reject(new Error('network unavailable'));await tick();
  assert.match(h.contents(h.nodes.get('cloud-result')),/다시 요청하면 비용/);assert.equal(calls,1);assert.equal(h.nodes.get('cloud-submit').disabled,true);
});
test('genuine selection change during submission cancels and discards late failure',async()=>{
  let reject,signal;const h=panelHarness({cloudRewrite:(_s,_r,_b,options)=>{signal=options.signal;return new Promise((_resolve,no)=>{reject=no;});}});
  h.fill();h.confirm();h.nodes.get('cloud-submit').click();h.text.selectionStart=2;h.text.emit('select');
  assert.equal(signal.aborted,true);reject(new Error('network unavailable'));await tick();assert.equal(h.nodes.get('cloud-result').children.length,0);
});

test('BillingAI rewrite keeps explicit preview and consent, bare model ID and ephemeral key',async()=>{
  const calls=[];const h=panelHarness({cloudRewrite:async(_s,_r,body,options)=>{calls.push({body,options});return result(cloudPreview({block,source,provider:body.provider,model:body.model,text:block.raw_text,start:0,end:block.raw_text.length}));}});
  const get=id=>h.nodes.get(id);
  assert.ok(get('cloud-provider').options.some(([value])=>value==='billingai'));
  h.change('cloud-provider','billingai');assert.equal(get('cloud-model').value,'');assert.equal(get('cloud-billing-help').hidden,false);assert.equal(calls.length,0);
  h.change('cloud-model','gpt-5-4');h.change('cloud-api-key','billing-key');get('cloud-preview-button').click();get('cloud-submit').click();assert.equal(calls.length,0);
  h.confirm();get('cloud-submit').click();assert.equal(get('cloud-api-key').value,'');await tick();
  assert.equal(calls.length,1);assert.equal(calls[0].body.provider,'billingai');assert.equal(calls[0].body.model,'gpt-5-4');assert.equal(calls[0].body.consent,true);assert.equal(calls[0].options.apiKey,'billing-key');assert.equal(JSON.stringify(calls[0].body).includes('billing-key'),false);
  assert.equal(get('cloud-result').children.length>0,true);assert.equal(get('cloud-submit').disabled,true);
  h.change('cloud-api-key','replacement-key');h.confirm();h.change('cloud-provider','gemini');assert.equal(get('cloud-api-key').value,'');assert.equal(get('cloud-consent').checked,false);assert.equal(get('cloud-billing-help').hidden,true);
});

test('BillingAI rewrite rejects prefixed models and malformed keys then consumes failed request consent',async()=>{
  let calls=0;const h=panelHarness({cloudRewrite:async()=>{calls++;throw new Error('billing-key');}});const get=id=>h.nodes.get(id);
  h.change('cloud-provider','billingai');h.change('cloud-model','openai/gpt-5-4');h.change('cloud-api-key','billing-key');h.confirm();get('cloud-submit').click();assert.equal(calls,0);
  h.change('cloud-model','gpt-5-4');h.change('cloud-api-key','bad key');h.confirm();get('cloud-submit').click();assert.equal(calls,0);
  h.change('cloud-api-key','billing-key');h.confirm();get('cloud-submit').click();await tick();assert.equal(calls,1);assert.equal(get('cloud-api-key').value,'');assert.equal(get('cloud-submit').disabled,true);assert.equal(get('cloud-consent').checked,false);assert.equal(h.contents(h.mounted.panel).includes('billing-key'),false);
  get('cloud-submit').click();assert.equal(calls,1);
});

import {createKeyStatus} from '../../src/submission/static/prepare/ai-settings.mjs';
test('saved cloud key defaults without header and still requires fresh consent; override wins',async()=>{
 const status=createKeyStatus();status.update({available:true,backend:'keychain',providers:['gemini','openai','anthropic','billingai'].map(provider=>({provider,configured:true}))});
 const calls=[];const h=panelHarness({cloudRewrite:async(_s,_r,b,o)=>{calls.push({b,o});return result(preview());}},status);
 h.change('cloud-provider','gemini');h.change('cloud-model','service-model');h.nodes.get('cloud-preview-button').click();h.nodes.get('cloud-submit').click();assert.equal(calls.length,0);
 h.confirm();h.nodes.get('cloud-submit').click();await tick();assert.equal(calls.length,1);assert.equal(calls[0].b.use_saved_key,true);assert.equal(calls[0].o.apiKey,undefined);assert.match(h.contents(h.nodes.get('cloud-result')),/완료/);
 h.change('cloud-api-key','override');h.confirm();h.nodes.get('cloud-submit').click();await tick();assert.equal(calls[1].b.use_saved_key,false);assert.equal(calls[1].o.apiKey,'override');
 h.confirm();status.update({available:false,backend:null,providers:[]});assert.equal(h.nodes.get('cloud-submit').disabled,true);assert.equal(h.nodes.get('cloud-consent').checked,false);h.nodes.get('cloud-preview-button').click();assert.equal(h.nodes.get('cloud-submit').disabled,true);
});
test('saved-key request body explicitly suppresses accidental manual header for every AI route',async()=>{
 const calls=[];const api=createAPI(async(_url,options)=>{calls.push(options);return {ok:true,json:async()=>({success:true,data:{}})};});
 const session={session_id:'s',access_token:'token'},body={use_saved_key:true},options={apiKey:'omit-header'};
 await api.cloudRewrite(session,'report',body,options);await api.aiRequirements(session,body,options);await api.aiCheck(session,body,options);
 for(const call of calls){assert.equal(call.headers['X-AI-API-Key'],undefined);assert.equal(JSON.parse(call.body).use_saved_key,true);assert.equal(JSON.stringify(call).includes('omit-header'),false);}
});
