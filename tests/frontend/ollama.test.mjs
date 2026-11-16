import test from 'node:test';
import assert from 'node:assert/strict';
import {ollamaSelection,validateOllamaModels,validateOllamaRewrite,createOllamaRequest} from '../../src/submission/static/prepare/ollama.mjs';
import {createResources} from '../../src/submission/static/prepare/state.mjs';
import {createAPI} from '../../src/submission/static/prepare/api.mjs';
const block={block_id:'b1',raw_text:'😀 이 수치는 42입니다.'};
const source='a'.repeat(64);
const range={start:0,end:[...block.raw_text].length};
const context={block,range,source,model:'local-model:latest'};
const result=()=>({provider:'ollama',model:context.model,source_sha256:source,block_id:'b1',...range,original:block.raw_text,suggestion:'이 수치는 42입니다. 😀',llm_executed:true});
test('selected Unicode range is exact, nonempty and bounded to 4000 characters',()=>{
  assert.deepEqual(ollamaSelection(block.raw_text,0,block.raw_text.length),range);
  for(const offsets of [[1,2],[0,0],[-1,2],[0,100]])assert.throws(()=>ollamaSelection(block.raw_text,...offsets));
  assert.deepEqual(ollamaSelection('😀'.repeat(4000),0,8000),{start:0,end:4000});
  assert.throws(()=>ollamaSelection('x'.repeat(4001),0,4001));
});
test('model discovery accepts only bounded unique local model names',()=>{
  assert.deepEqual(validateOllamaModels({provider:'ollama',models:[{name:'local-model:latest'}]}),[{name:'local-model:latest'}]);
  assert.deepEqual(validateOllamaModels({provider:'ollama',models:[]}),[]);
  for(const value of [null,{}, {provider:'cloud',models:[]},{provider:'ollama',models:null},{provider:'ollama',models:[{name:''}]},{provider:'ollama',models:[{name:'x'.repeat(201)}]},{provider:'ollama',models:[{name:'same'},{name:'same'}]},{provider:'ollama',models:[{name:42}]},{provider:'ollama',models:Array(101).fill({name:'x'})}])assert.throws(()=>validateOllamaModels(value));
});
test('rewrite validates exact original, source, range, model and actual execution',()=>{
  const before=JSON.stringify(block);assert.equal(validateOllamaRewrite(result(),context).suggestion,'이 수치는 42입니다. 😀');assert.equal(JSON.stringify(block),before);
  for(const patch of [{provider:'cloud'},{model:'other'},{source_sha256:'b'.repeat(64)},{block_id:'b2'},{start:1},{end:1},{original:'changed'},{suggestion:''},{suggestion:' '.repeat(2)},{suggestion:42},{suggestion:'x'.repeat(8001)},{llm_executed:false}])assert.throws(()=>validateOllamaRewrite({...result(),...patch},context));
  for(const invalid of [{start:-1,end:4},{start:0,end:99},{start:0,end:0},{start:0.1,end:4}])assert.throws(()=>validateOllamaRewrite(result(),{...context,range:invalid}));
  assert.throws(()=>validateOllamaRewrite(result(),{...context,source:'bad'}));
  assert.throws(()=>validateOllamaRewrite(result(),{...context,model:''}));
  assert.throws(()=>validateOllamaRewrite(result(),{...context,block:{...block,raw_text:'x'.repeat(4001)},range:{start:0,end:4001}}));
});
test('authenticated explicit API calls use local header and JSON body without token in URLs',async()=>{
  const calls=[];const api=createAPI(async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>({success:true,data:result()})};});
  const session={session_id:'id',access_token:'secret'};const signal=new AbortController().signal;
  await api.ollamaModels(session,signal);await api.ollamaRewrite(session,'report',{block_id:'b1',...range,model:context.model},signal);
  assert.equal(calls[0].path,'/api/document-pairs/ollama/models?session_id=id');assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].options.body,undefined);
  assert.equal(calls[1].path,'/api/document-pairs/id/report/ollama-rewrite');assert.equal(calls[1].options.method,'POST');assert.deepEqual(JSON.parse(calls[1].options.body),{block_id:'b1',...range,model:context.model});
  for(const {path,options} of calls){assert.equal(path.includes('secret'),false);assert.equal(options.headers['X-Session-Token'],'secret');assert.equal(options.headers['X-Local-Client'],'prepare');assert.equal(options.credentials,'omit');assert.equal(options.redirect,'error');assert.equal(options.cache,'no-store');assert.equal(options.signal,signal);}
});
test('stale successes and errors never render after block, role or session cancellation',async()=>{
  const resources=createResources();const states=[];let resolve,reject,signal;
  const request=createOllamaRequest({resources,key:'ollama-rewrite',validate:validateOllamaRewrite,request:(_,abort)=>{signal=abort;return new Promise((yes,no)=>{resolve=yes;reject=no;});},onState:state=>states.push(state)});
  const first=request.run(context);resources.begin('ollama-rewrite');assert.equal(signal.aborted,true);resolve(result());await first;
  const second=request.run(context);resources.clear();reject(new Error('stale'));await second;
  assert.deepEqual(states.map(x=>x.status),['running','running']);
  const third=request.run(context);reject(new Error('network'));await third;assert.equal(states.at(-1).status,'error');
  const retry=request.run(context);resolve(result());await retry;assert.equal(states.at(-1).status,'complete');
});
test('newest request wins and malformed response becomes an error',async()=>{
  const resources=createResources();const states=[];const resolvers=[];
  const request=createOllamaRequest({resources,key:'ollama-models',validate:validateOllamaModels,request:()=>new Promise(resolve=>resolvers.push(resolve)),onState:state=>states.push(state)});
  const first=request.run();const second=request.run();resolvers[0]({provider:'ollama',models:[{name:'old'}]});await first;resolvers[1]({provider:'ollama',models:[{name:'new'}]});await second;
  assert.deepEqual(states.filter(x=>x.status==='complete').map(x=>x.result),[[{name:'new'}]]);
  const malformed=request.run();resolvers[2]({provider:'cloud',models:[]});await malformed;assert.equal(states.at(-1).status,'error');
});
