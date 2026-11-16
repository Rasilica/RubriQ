import test from 'node:test';
import assert from 'node:assert/strict';
import {createLibraryAPI,validateLibrary,libraryError,environmentText} from '../../src/submission/static/prepare/library-api.mjs';
const item={saved_id:'saved-1',project_name:'보관',saved_at:'2026-10-10T00:00:00Z'};
const listing={items:[item],total:1,page:1,page_size:20};
const response=data=>({ok:true,status:200,json:async()=>({success:true,data})});
test('library transport uses local header and memory token only for explicit save',async()=>{
  const calls=[];const api=createLibraryAPI(async(url,options)=>{calls.push({url,options});return response(url.includes('?')?listing:url.endsWith('/save')?{...item,already_saved:true}:{deleted:true});});
  assert.deepEqual(await api.list(1),listing);
  assert.equal((await api.save({session_id:'s1',access_token:'secret'})).already_saved,true);
  await api.remove('saved-1');
  assert.equal(calls[0].url,'/api/document-library?page=1');
  assert.equal(calls[1].options.headers['X-Session-Token'],'secret');
  assert.equal(calls[2].options.method,'DELETE');
  for(const call of calls){assert.equal(call.options.headers['X-Local-Client'],'prepare');assert.equal(call.options.cache,'no-store');assert.equal(call.options.credentials,'omit');assert.equal(call.url.includes('secret'),false);}
  assert.equal(calls[0].options.headers['X-Session-Token'],undefined);
});
test('library list validates identifiers, pagination and dates before rendering',()=>{
  assert.deepEqual(validateLibrary({...listing,items:[],total:0}),{...listing,items:[],total:0});
  for(const bad of [null,{...listing,page:0},{...listing,page_size:10},{...listing,total:-1},{...listing,items:[{...item,saved_id:'../secret'}]},{...listing,items:[{...item,saved_at:'bad'}]},{...listing,items:[{...item,project_name:null}]}])assert.throws(()=>validateLibrary(bad));
});
test('errors use safe specific copy and malformed JSON fails',async()=>{
  for(const code of ['library_not_found','library_corrupt','library_limit','library_unavailable','library_forbidden']){
    const api=createLibraryAPI(async()=>({ok:false,status:422,json:async()=>({success:false,error:{code,message:'secret path'}})}));
    await assert.rejects(api.list(1),error=>error.code===code&&!libraryError(error).includes('secret'));
  }
  assert.match(libraryError({status:429}),/잠시/);assert.match(libraryError({}),/연결/);
  await assert.rejects(createLibraryAPI(async()=>({ok:true,status:200,json:async()=>{throw Error();}})).list(1));
});
test('open rejects tokenless or expired sessions and unsafe environment metadata',async()=>{
  const role=name=>({role:name,document:null,extraction_status:'failed',rendering_status:'not_started',warnings:[],preview_page_count:null,artifact_kind:null});
  const session={session_id:'s1',access_token:'new-secret',project_name:'보관',expires_at:'2099-01-01',guide:role('guide'),report:role('report'),saved_id:'saved-1',saved_at:item.saved_at,saved_environment:['Java 17'],current_environment:['Java 18']};
  assert.deepEqual(await createLibraryAPI(async()=>response(session)).open('saved-1'),session);
  for(const bad of [{...session,access_token:null},{...session,expires_at:'2000-01-01'},{...session,saved_environment:'bad'}])await assert.rejects(createLibraryAPI(async()=>response(bad)).open('saved-1'));
  assert.match(environmentText(session),/달라/);assert.match(environmentText({}),/미기록/);
  assert.match(environmentText({...session,current_environment:session.saved_environment}),/같/);
});
test('save/delete reject incomplete success envelopes and server failures remain bounded',async()=>{
  const session={session_id:'session',access_token:'token'};
  for(const value of [null,{...item},{...item,already_saved:'yes'}])await assert.rejects(createLibraryAPI(async()=>response(value)).save(session));
  for(const value of [null,{deleted:false}])await assert.rejects(createLibraryAPI(async()=>response(value)).remove('saved-1'));
  await assert.rejects(createLibraryAPI(async()=>({ok:false,status:500,json:async()=>null})).list(1),error=>error.code==='request_failed');
});
test('save receipts reject contradictory archive/check claims',async()=>{
 const session={session_id:'session',access_token:'token'};
 for(const flags of [{has_semantic_archive:false,has_check:true},{has_semantic_archive:'yes',has_check:false},{has_semantic_archive:true,has_check:null}])await assert.rejects(createLibraryAPI(async()=>response({...item,already_saved:false,...flags})).save(session));
 for(const flags of [{has_semantic_archive:false,has_check:false},{has_semantic_archive:true,has_check:false},{has_semantic_archive:true,has_check:true}])assert.deepEqual(await createLibraryAPI(async()=>response({...item,already_saved:false,...flags})).save(session),{...item,already_saved:false,...flags});
});
test('opening rejects archive records that do not bind to available documents',async()=>{
 const role=name=>({role:name,document:null,extraction_status:'failed',rendering_status:'not_started',warnings:[],preview_page_count:null,artifact_kind:null});
 const value={session_id:'s1',access_token:'token',project_name:'archive',expires_at:'2099-01-01',guide:role('guide'),report:role('report'),...item,saved_environment:[],current_environment:[],semantic_archive:{draft:{confirmed:true},check:null}};
 await assert.rejects(createLibraryAPI(async()=>response(value)).open(item.saved_id));
});
