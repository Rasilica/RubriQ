import test from 'node:test';
import assert from 'node:assert/strict';
import {createResources, initialSelection, selectBlock, selectPage, unicodeRange, verifiedPages, validateSession,mappingMatches,warningText} from '../../src/submission/static/prepare/state.mjs';

test('conversion warnings explain uncertainty in Korean without claiming substitution occurred',()=>{
  assert.equal(warningText('original_layout_unverified'),'원본 레이아웃과 같은지 확인하지 못했습니다. 줄바꿈·표·쪽 나눔이 달라질 수 있습니다.');
  assert.equal(warningText('font_inventory_partial'),'확인한 폰트 목록이 일부에 한정됩니다. 원본의 모든 폰트가 준비되었는지는 미확인입니다.');
  assert.equal(warningText('font_resolution_unverified'),'실제로 사용된 폰트와 대체 여부는 확인하지 못했습니다. 글자 모양과 배치를 확인해주세요.');
  assert.equal(warningText('unknown_future_warning'),'문서 준비 중 추가 확인이 필요한 항목이 있습니다. 원본과 PDF를 함께 확인해주세요.');
});

test('block and PDF positions are independent and role scoped',()=>{
  const original=initialSelection();
  const block=selectBlock(original,'guide','b2');
  const page=selectPage(block,'guide',3,4);
  assert.equal(page.guide.block,'b2'); assert.equal(page.guide.page,3);
  assert.equal(page.report.page,1); assert.equal(original.guide.block,null);
  assert.throws(()=>selectPage(page,'guide',5,4));
});
test('DOM UTF16 selections become Python Unicode offsets',()=>{
  assert.deepEqual(unicodeRange('가😀나다',1,4),{start:1,end:3});
  assert.throws(()=>unicodeRange('😀',1,2));
  assert.throws(()=>unicodeRange('abc',2,1));
});
test('only real exact mappings can navigate valid pages',()=>{
  const mapping={snapshot_origin:'real_pdf',mapping:{mapping_status:'verified_anchor',target_page_numbers:[2]}};
  assert.deepEqual(verifiedPages(mapping,3),[2]);
  assert.deepEqual(verifiedPages({...mapping,snapshot_origin:'synthetic'},3),[]);
  assert.deepEqual(verifiedPages({...mapping,mapping:{mapping_status:'ambiguous',target_page_numbers:[2]}},3),[]);
  assert.deepEqual(verifiedPages(mapping,1),[]);
});
test('request generations and object URL cleanup reject stale results',()=>{
  const revoked=[];const resources=createResources({createObjectURL:()=> 'blob:1',revokeObjectURL:url=>revoked.push(url)});
  const first=resources.begin('image');const second=resources.begin('image');
  assert.equal(first.signal.aborted,true);assert.equal(resources.current(first),false);
  assert.equal(resources.current(second),true);resources.url('image',new Blob());
  resources.clear();assert.deepEqual(revoked,['blob:1']);assert.equal(resources.current(second),false);
});
test('session validator rejects invalid identity, stale sessions and inconsistent role documents',()=>{
  const role={document:null,extraction_status:'failed',rendering_status:'not_started',warnings:[],error_code:'invalid',preview_page_count:null,artifact_kind:null};
  const session={session_id:'abc',access_token:'secret',project_name:'test',expires_at:'2099-01-01T00:00:00Z',guide:{...role,role:'guide'},report:{...role,role:'report'}};
  assert.equal(validateSession(session,0),session);
  assert.throws(()=>validateSession({...session,session_id:'../x'},0));
  assert.throws(()=>validateSession(session,Date.parse('2100-01-01')));
  assert.throws(()=>validateSession({...session,guide:{...session.guide,document:{blocks:[]}}},0));
});
test('mapping requires source version, locator, block, range and exact target artifact binding',()=>{
  const document={source:{source_id:'s1',content_sha256:'hash',document_version_id:'v1'},artifacts:[{artifact_id:'pdf1',artifact_sha256:'pdfhash'}]};
  const block={block_id:'b1',source_locator:{path:'p1'}};const range={start:0,end:2};
  const result={source_id:'s1',source_sha256:'hash',document_version_id:'v1',source_locator:{path:'p1'},target_artifact_sha256:'pdfhash',mapping:{source_block_id:'b1',source_char_range:range,target_artifact_id:'pdf1'}};
  assert.equal(mappingMatches(result,document,block,range),true);
  for(const [key,value] of [['source_id','s2'],['source_sha256','changed'],['document_version_id','v2'],['source_locator',{path:'p2'}],['target_artifact_sha256','wrong']])assert.equal(mappingMatches({...result,[key]:value},document,block,range),false);
  assert.equal(mappingMatches(result,document,block,{start:0,end:1}),false);
  assert.equal(mappingMatches(result,document,{...block,block_id:'b2'},range),false);
});
test('valid document and malformed blocks, warnings, page counts and artifacts',()=>{
  const hash='a'.repeat(64);const block={block_id:'b',raw_text:'가😀',source_locator:{path:'section/1',source_sha256:hash}};
  const role=name=>({role:name,document:{source:{role:name,filename:'보고서.hwp',content_sha256:hash},blocks:[block],coverage:{scope:'hwp_structure'}},extraction_status:'partial',rendering_status:'complete',warnings:[],preview_page_count:1,artifact_kind:'preview_pdf'});
  const session={session_id:'s1',project_name:'p',expires_at:'2099-01-01',guide:role('guide'),report:role('report')};
  assert.equal(validateSession(session,0),session);
  for(const patch of [{warnings:[4]},{preview_page_count:51},{artifact_kind:'fake'},{extraction_status:'unknown'},{document:{...session.guide.document,blocks:[block,block]}},{document:{...session.guide.document,blocks:[{...block,raw_text:null}]}}])assert.throws(()=>validateSession({...session,guide:{...session.guide,...patch}},0));
});

test('preparation errors name the actual cause in Korean',async()=>{
  const {errorText}=await import('../../src/submission/static/prepare/state.mjs');
  assert.equal(errorText('encrypted_document'),'암호가 걸린 문서라 읽을 수 없습니다. 암호를 해제한 뒤 다시 올려주세요.');
  assert.equal(errorText('unsupported_version'),'지원하지 않는 문서 버전입니다. 최신 한글이나 Word에서 다시 저장한 뒤 올려주세요.');
  assert.match(errorText('unsupported_active_content'),/PDF 변환을 하지 않았습니다/);
  assert.equal(errorText('some_future_code'),'이 문서를 준비하는 중 오류가 발생했습니다.');
  assert.equal(errorText('__proto__'),'이 문서를 준비하는 중 오류가 발생했습니다.');
});
