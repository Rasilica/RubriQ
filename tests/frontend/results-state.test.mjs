import test from "node:test";
import assert from "node:assert/strict";
import {resultView,evidenceEntries,resolveEvidence,quoteParts,pageSummary,createLatestRequest,initialSelection,selectPage,selectCitation,selectBlock} from "../../src/submission/static/results/state.mjs";

const cite={block_id:"b1",quote:"😀글",char_range:{start:1,end:3},source_locator:{original_page_number:2,source_sha256:"same"}};
const semantic={requirement_id:"R5",criterion:{title:"분량",classification:"required"},applicability:"applicable",proposed_judgment:"evidence_found",judgment:"deferred",original_requirement:{citations:[cite],subconditions:[],condition:null},evidence:[{citation:cite}],subconditions:[]};
test("effective judgment and attention override proposed semantic success",()=>{
  const view=resultView({semantic,effective_judgment:"explicit_noncompliance",needs_attention:true},"R5");
  assert.equal(view.status,"명시적 미충족");assert.equal(view.attention,true);assert.equal(view.selected,true);
});
test("optional missing and inapplicable null stay non-warning",()=>{
  const optional=resultView({semantic:{...semantic,criterion:{...semantic.criterion,classification:"optional"}},effective_judgment:"evidence_missing",needs_attention:false},null);
  assert.equal(optional.kind,"선택");assert.equal(optional.attention,false);
  assert.equal(resultView({semantic:{...semantic,applicability:"not_applicable"},effective_judgment:null,needs_attention:false},null).status,"적용 대상 아님");
});
test("evidence includes original child and condition plus report child citations",()=>{
  const second={...cite,block_id:"b2"};
  const item={semantic:{...semantic,original_requirement:{citations:[cite],subconditions:[{citations:[second]}],condition:{citations:[cite]}},subconditions:[{subcondition_id:"S1",evidence:[{citation:second}]}]},page_rule:null};
  const entries=evidenceEntries(item);
  assert.equal(entries.filter((entry)=>entry.role==="guide").length,2);
  assert.equal(entries.filter((entry)=>entry.role==="report").length,2);
});
test("source navigation validates hash/range/quote and uses Unicode code points",()=>{
  const document={source:{content_sha256:"same"},pages:[{page_number:1},{page_number:2}],blocks:[{block_id:"b1",raw_text:"앞😀글뒤",source_locator:cite.source_locator}]};
  assert.deepEqual(resolveEvidence({report:document},{role:"report",citation:cite}),{role:"report",page:2,citation:cite});
  assert.deepEqual(quoteParts("앞😀글뒤",cite.char_range),["앞","😀글","뒤"]);
  assert.equal(resolveEvidence({report:document},{role:"report",citation:{...cite,quote:"틀림"}}),null);
  assert.equal(resolveEvidence({report:document},{role:"report",citation:{...cite,source_locator:{...cite.source_locator,source_sha256:"other"}}}),null);
  assert.equal(resolveEvidence({report:document},{role:"report",citation:{...cite,block_id:"missing"}}),null);
});
test("page summary distinguishes verified count from unknown scope and no rule",()=>{
  assert.equal(pageSummary(null),null);
  const rule={status:"compliant",rule:{maximum_pages:2,scope:"all_pdf_pages"},assessment:{assessment:{status:"verified",count:2,included_pages:[1,2]}},scope_subconditions:[{status:"verified"}]};
  assert.deepEqual(pageSummary(rule),{count:2,maximum:2,scopeVerified:true,status:"compliant"});
  assert.deepEqual(pageSummary({...rule,status:"deferred",assessment:{assessment:{status:"deferred",count:null}},scope_subconditions:[{status:"deferred"}]}),{count:null,maximum:2,scopeVerified:false,status:"deferred"});
});
test("newer request wins over old success and old failure",async()=>{
  const gate=createLatestRequest();let finish;
  const first=gate.run(()=>new Promise((resolve)=>{finish=resolve;}));
  assert.deepEqual(await gate.run(async()=>"new"),{status:"ready",data:"new"});finish("old");
  assert.deepEqual(await first,{status:"stale"});
  let reject;const old=gate.run(()=>new Promise((resolve,fail)=>{reject=fail;}));
  await gate.run(async()=>"latest");reject(new Error("old"));assert.deepEqual(await old,{status:"stale"});
  const error=new Error("current");assert.deepEqual(await gate.run(async()=>{throw error;}),{status:"error",error});
});
test("page boundaries, independent document position and case reset preserve source identity",()=>{
  const doc={source:{content_sha256:"same"},pages:[{page_number:1},{page_number:2}],blocks:[{block_id:"b1",raw_text:"앞😀글뒤",source_locator:cite.source_locator}]};
  const documents={guide:doc,report:doc};
  const fresh=initialSelection();
  const selected=selectCitation(fresh,documents,{role:"guide",citation:cite});
  assert.equal(selected.role,"guide");assert.equal(selected.pages.guide,2);assert.equal(selected.pages.report,1);
  const changed=selectPage(selected,documents,{role:"report",page:99});
  assert.equal(changed.pages.report,2);assert.equal(changed.citations.guide,cite);
  assert.equal(selectPage(changed,documents,{role:"guide",page:0}).pages.guide,1);
  assert.equal(selectPage(changed,documents,{role:"guide",page:1}).citations.guide,null);
  assert.deepEqual(initialSelection(),fresh);
  assert.equal(selectCitation(fresh,documents,{role:"guide",citation:{...cite,quote:"wrong"}}),fresh);
});

test("structure citation resolves exact Unicode source without inventing a page",()=>{
  const citation={...cite,source_locator:{...cite.source_locator,path:"word/document.xml/p[1]",original_page_number:null}};
  const doc={representation:"source_structure",source:{content_sha256:"same"},pages:[],blocks:[{block_id:"b1",raw_text:"앞😀글뒤",source_locator:citation.source_locator}]};
  assert.deepEqual(resolveEvidence({report:doc},{role:"report",citation}),{role:"report",page:null,citation});
  assert.equal(resolveEvidence({report:doc},{role:"report",citation:{...citation,source_locator:{...citation.source_locator,path:"wrong"}}}),null);
  const selected=selectCitation(initialSelection(),{report:doc},{role:"report",citation});
  assert.equal(selected.pages.report,null);assert.equal(selected.blocks.report,"b1");
  const switched=selectPage(selected,{report:doc},{role:"report",page:1});
  assert.equal(switched.pages.report,null);assert.equal(switched.citations.report,citation);
});

test("block navigation retains exact citation only on its block and preserves PDF position",()=>{
  const doc={representation:"source_structure",blocks:[{block_id:"b1"},{block_id:"b2"}],pages:[]};
  const citation={...cite,source_locator:{...cite.source_locator,original_page_number:null}};
  const selected={...initialSelection(),pages:{guide:2,report:null},blocks:{guide:null,report:"b1"},citations:{guide:cite,report:citation}};
  const same=selectBlock(selected,{report:doc},"b1");
  assert.equal(same.citations.report,citation);
  const next=selectBlock(selected,{report:doc},"b2");
  assert.equal(next.blocks.report,"b2");assert.equal(next.citations.report,null);
  assert.equal(next.pages.guide,2);assert.equal(next.citations.guide,cite);
  assert.equal(selected.blocks.report,"b1");
  assert.equal(selectBlock(selected,{report:doc},"missing"),selected);
});
test("structure citation rejects negative, noninteger, overflow, hash and text mismatch",()=>{
  const citation={...cite,source_locator:{...cite.source_locator,path:"part/p",original_page_number:null}};
  const doc={representation:"source_structure",source:{content_sha256:"same"},pages:[],blocks:[{block_id:"b1",raw_text:"앞😀글뒤",source_locator:citation.source_locator}]};
  for(const range of [{start:-1,end:2},{start:1.5,end:3},{start:3,end:3},{start:1,end:9}]) assert.equal(resolveEvidence({report:doc},{role:"report",citation:{...citation,char_range:range}}),null);
  assert.equal(resolveEvidence({report:doc},{role:"report",citation:{...citation,quote:"wrong"}}),null);
  assert.equal(resolveEvidence({report:doc},{role:"report",citation:{...citation,source_locator:{...citation.source_locator,source_sha256:"other"}}}),null);
  assert.equal(resolveEvidence({report:doc},{role:"report",citation:{...citation,source_locator:{...citation.source_locator,original_page_number:1}}}),null);
});

test("PDF to structure round trip retains block and exact quote independently",()=>{
  const citation={...cite,source_locator:{...cite.source_locator,path:"part/p",original_page_number:null}};
  const report={representation:"source_structure",source:{content_sha256:"same"},pages:[],blocks:[{block_id:"b1",raw_text:"앞😀글뒤",source_locator:citation.source_locator}]};
  const guide={pages:[{page_number:1},{page_number:2}]};
  const docs={guide,report};
  const structural=selectCitation(initialSelection(),docs,{role:"report",citation});
  const pdf=selectPage(structural,docs,{role:"guide",page:2});
  const returned=selectPage(pdf,docs,{role:"report",page:null});
  assert.equal(returned.pages.guide,2);assert.equal(returned.pages.report,null);
  assert.equal(returned.blocks.report,"b1");assert.equal(returned.citations.report,citation);
  assert.deepEqual(quoteParts(report.blocks[0].raw_text,returned.citations.report.char_range),["앞","😀글","뒤"]);
});

test("container navigation returns only direct existing children in document order",async()=>{
  const {blockChildren}=await import("../../src/submission/static/results/state.mjs");
  const blocks=[{block_id:"parent"},{block_id:"first",parent_block_id:"parent"},{block_id:"nested",parent_block_id:"first"},{block_id:"second",parent_block_id:"parent"}];
  assert.deepEqual(blockChildren({blocks},"parent").map((block)=>block.block_id),["first","second"]);
  assert.deepEqual(blockChildren({blocks},"missing"),[]);
});
test("synthetic scenario action uses bound source citation and rejects foreign source",()=>{
  const citation={...cite,source_locator:{...cite.source_locator,path:"part/p",original_page_number:null}};
  const report={representation:"source_structure",source:{content_sha256:"same"},pages:[],blocks:[{block_id:"b1",raw_text:"앞😀글뒤",source_locator:citation.source_locator}]};
  const scenario={citation,result:{mapping:{mapping_status:"ambiguous"}}};
  const initial=initialSelection();
  const selected=selectCitation(initial,{report},{role:"report",citation:scenario.citation});
  assert.equal(selected.citations.report,citation);assert.equal(selected.blocks.report,"b1");
  assert.equal(selectCitation(initial,{report},{role:"report",citation:{...scenario.citation,source_locator:{...citation.source_locator,source_sha256:"foreign"}}}),initial);
});
test("stat counts group effective judgments and attention",async()=>{
  const {statCounts}=await import("../../src/submission/static/results/state.mjs");
  const item=(effective_judgment,needs_attention)=>({semantic,effective_judgment,needs_attention});
  const counts=statCounts([item("evidence_found",false),item("evidence_missing",true),item("explicit_noncompliance",true),item("deferred",true),item("partially_satisfied",true)]);
  assert.deepEqual(counts,{attention:4,found:1,missing:2,deferred:2,total:5});
});
test("status tone follows the effective judgment and applicability",()=>{
  const tone=(effective_judgment,applicability="applicable")=>resultView({semantic:{...semantic,applicability},effective_judgment,needs_attention:false},null).tone;
  assert.equal(tone("evidence_found"),"success");assert.equal(tone("evidence_missing"),"soon");
  assert.equal(tone("deferred"),"attention");assert.equal(tone("partially_satisfied"),"progress");
  assert.equal(tone(null,"not_applicable"),"ended");
});
