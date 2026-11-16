import test from 'node:test';
import assert from 'node:assert/strict';
import {createAPI,ApiError} from '../../src/submission/static/prepare/api.mjs';
const role=name=>({role:name,document:null,extraction_status:'failed',rendering_status:'not_started',warnings:[],error_code:'invalid',preview_page_count:null,artifact_kind:null});
const session={session_id:'test-session',access_token:'secret-token',project_name:'테스트',expires_at:'2099-01-01T00:00:00Z',guide:role('guide'),report:role('report')};
const response=data=>({ok:true,status:200,json:async()=>({success:true,data})});
test('upload uses FormData; authenticated routes never put tokens in URLs',async()=>{
  const calls=[];const client=createAPI(async(url,options)=>{calls.push({url,options});return response(session);});
  const form=new FormData();form.set('project_name','테스트');
  await client.prepare(form);await client.inspect(session);await client.evidence(session,'guide',{block_id:'b1',start:0,end:2});await client.remove(session);
  assert.equal(calls[0].options.body,form);assert.deepEqual(calls[0].options.headers,{});
  for(const call of calls.slice(1)){assert.equal(call.options.headers['X-Session-Token'],'secret-token');assert.equal(call.url.includes('secret-token'),false);assert.equal(call.options.credentials,'omit');assert.equal(call.options.cache,'no-store');assert.equal(call.options.redirect,'error');}
  assert.equal(calls[2].options.body,JSON.stringify({block_id:'b1',start:0,end:2}));assert.equal(calls[3].options.method,'DELETE');
});
test('asset responses require expected content type and bounded nonempty body',async()=>{
  for(const type of ['text/html','application/json']){
    const client=createAPI(async()=>({ok:true,headers:new Headers({'content-type':type})}));
    await assert.rejects(client.image(session,'guide',1),ApiError);
  }
  for(const size of [0,8*1024*1024+1]){
    const client=createAPI(async()=>({ok:true,headers:new Headers({'content-type':'image/png'}),blob:async()=>new Blob([new Uint8Array(size)])}));
    await assert.rejects(client.image(session,'report',1),ApiError);
  }
  const calls=[];const client=createAPI(async(url)=>{calls.push(url);const type=url.endsWith('.png')?'image/png':'application/pdf';return {ok:true,headers:new Headers({'content-type':type}),blob:async()=>new Blob(['data'],{type})};});
  assert.equal((await client.image(session,'guide',2)).type,'image/png');assert.equal((await client.pdf(session,'report')).type,'application/pdf');
  assert.deepEqual(calls,['/api/document-pairs/test-session/guide/pages/2.png','/api/document-pairs/test-session/report/pdf']);
});
test('failed, malformed, expired and tokenless responses cannot become live sessions',async()=>{
  for(const status of [404,409,422,429]){
    const client=createAPI(async()=>({ok:false,status,json:async()=>({success:false,error:{code:'unavailable',message:'private path'}})}));
    await assert.rejects(client.inspect(session),error=>error instanceof ApiError&&error.status===status&&!error.message.includes('private'));
  }
  await assert.rejects(createAPI(async()=>({ok:true,status:200,json:async()=>{throw new Error('bad JSON');}})).inspect(session),ApiError);
  await assert.rejects(createAPI(async()=>response({...session,access_token:undefined})).prepare(new FormData()),ApiError);
  await assert.rejects(createAPI(async()=>response({...session,expires_at:'2001-01-01'})).prepare(new FormData()));
  await assert.rejects(createAPI(async()=>({ok:false,status:500,json:async()=>null})).inspect(session),ApiError);
});

test('AI error diagnostics retain only validated bounded metadata and never server text',async()=>{
 const diagnostic={id:'a'.repeat(32),stage:'provider_response',reason:'output_truncated'};
 const call=async(value)=>{
  const api=createAPI(async()=>({ok:false,status:502,json:async()=>({success:false,error:{code:'cloud_invalid_response',message:'PRIVATE',diagnostic:value}})}));
  try{await api.aiCheck(session,{},{});}catch(error){return error;}
 };
 assert.deepEqual((await call(diagnostic)).diagnostic,diagnostic);
 for(const bad of [null,[],{}, {...diagnostic,id:null}, {...diagnostic,id:'PRIVATE'}, {...diagnostic,id:'A'.repeat(32)}, {...diagnostic,stage:'PRIVATE'}, {...diagnostic,stage:[]}, {...diagnostic,reason:['output_truncated']}, {...diagnostic,reason:'PRIVATE'}, {...diagnostic,raw:'PRIVATE'}]){
  const error=await call(bad);assert.equal(error.diagnostic,undefined);assert.equal(JSON.stringify(error).includes('PRIVATE'),false);
 }
 const error=await call(diagnostic);assert.equal(error.status,502);assert.equal(error.code,'cloud_invalid_response');assert.equal(error.message.includes('PRIVATE'),false);
});
