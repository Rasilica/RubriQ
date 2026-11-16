import test from 'node:test';
import assert from 'node:assert/strict';
import {validateExpression,expressionSelection,textareaRange,createExpressionCheck} from '../../src/submission/static/prepare/expression.mjs';
import {createResources} from '../../src/submission/static/prepare/state.mjs';
import {createAPI} from '../../src/submission/static/prepare/api.mjs';
const block={block_id:'b1',raw_text:'😀 이것은 보여지다.'};
const source='a'.repeat(64);
const range={start:0,end:[...block.raw_text].length};
const context={block,range,source};
const result=()=>({engine:'im-not-ai-local',revision:'2f3d943d08056b612a92e12bfb72ea94dd2acd18',scope:'selected_text',source_sha256:source,block_id:'b1',...range,llm_executed:false,findings:[{pattern_id:'A-8',label:'이중 피동',start:6,end:9,original:'보여지',explanation:'피동 표현을 확인하세요.',suggestion:null}],metrics:[{id:'double_passive',label:'피동 표현',count:1}],warnings:['일부 규칙만 확인했습니다.']});
test('validates source identity and exact codepoint quotation without changing source',()=>{
  const before=JSON.stringify(block);assert.equal(validateExpression(result(),context).findings[0].original,'보여지');assert.equal(JSON.stringify(block),before);
  assert.deepEqual(textareaRange(block.raw_text,{start:6,end:9}),{start:7,end:10});
  assert.deepEqual(expressionSelection(block.raw_text,0,block.raw_text.length),range);
  assert.throws(()=>expressionSelection(block.raw_text,1,2));assert.throws(()=>expressionSelection('x'.repeat(20001),0,20001));
});
test('rejects wrong identity, unsafe offsets, arbitrary engine, excessive and malformed fields',()=>{
  for(const patch of [{source_sha256:'b'.repeat(64)},{block_id:'b2'},{end:2},{scope:'document'},{engine:'AI'},{revision:'unknown'},{llm_executed:true},{findings:null},{metrics:[{id:'x',label:'count',count:-1}]},{warnings:[5]},{findings:Array(101).fill(result().findings[0])}])assert.throws(()=>validateExpression({...result(),...patch},context));
  for(const patch of [{start:-1},{end:99},{start:7},{original:'different'},{label:4},{explanation:'x'.repeat(2001)},{suggestion:5}])assert.throws(()=>validateExpression({...result(),findings:[{...result().findings[0],...patch}]},context));
  assert.throws(()=>textareaRange(block.raw_text,{start:3,end:2}));
  assert.throws(()=>validateExpression(result(),{...context,range:{start:-1,end:4}}));
  assert.equal(validateExpression({...result(),findings:[],metrics:[],warnings:[]},context).findings.length,0);
});
test('real API contract uses token and local header, never URL secrets',async()=>{
  let call;const api=createAPI(async(path,options)=>{call={path,options};return {ok:true,json:async()=>({success:true,data:result()})};});
  await api.expression({session_id:'id',access_token:'secret'},'guide',{block_id:'b1',...range});
  assert.equal(call.path,'/api/document-pairs/id/guide/expression-check');assert.equal(call.options.method,'POST');assert.equal(call.options.headers['X-Local-Client'],'prepare');assert.equal(call.options.headers['X-Session-Token'],'secret');assert.equal(call.options.cache,'no-store');assert.deepEqual(JSON.parse(call.options.body),{block_id:'b1',...range});
});
test('late successful and failed responses are discarded on reset; retries complete',async()=>{
  const resources=createResources();const events=[];let resolve,reject;
  const check=createExpressionCheck({resources,request:()=>new Promise((yes,no)=>{resolve=yes;reject=no;}),onState:state=>events.push(state)});
  const pending=check.run(context);resources.begin('expression');resolve(result());await pending;assert.deepEqual(events.map(x=>x.status),['running']);
  const second=check.run(context);resources.clear();reject(new Error('stale'));await second;assert.deepEqual(events.map(x=>x.status),['running','running']);
  const third=check.run(context);reject(new Error('network'));await third;assert.equal(events.at(-1).status,'error');
  const retry=check.run(context);resolve(result());await retry;assert.equal(events.at(-1).status,'complete');
});
test('invalid result becomes safe error and newer request wins',async()=>{
  const resources=createResources();const events=[];const resolvers=[];
  const check=createExpressionCheck({resources,request:()=>new Promise(resolve=>resolvers.push(resolve)),onState:state=>events.push(state)});
  const first=check.run(context);const second=check.run(context);resolvers[0](result());await first;resolvers[1]({...result(),source_sha256:'wrong'});await second;assert.equal(events.at(-1).status,'error');assert.equal(events.filter(x=>x.status==='complete').length,0);
});
