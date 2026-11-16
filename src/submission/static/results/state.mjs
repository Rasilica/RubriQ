export const JUDGMENTS=Object.freeze({evidence_found:"근거 확인",partially_satisfied:"일부 충족",explicit_noncompliance:"명시적 미충족",evidence_missing:"근거 미확인",deferred:"판정 보류"});
export const KINDS=Object.freeze({required:"필수",optional:"선택",conditional:"조건부"});
export const ROLES=Object.freeze({guide:"안내문",report:"보고서"});

const TONES=Object.freeze({evidence_found:"success",partially_satisfied:"progress",explicit_noncompliance:"soon",evidence_missing:"soon",deferred:"attention"});

export function resultView(item,selectedId) {
  const semantic=item.semantic;
  return {id:semantic.requirement_id,title:semantic.criterion.title,kind:KINDS[semantic.criterion.classification],status:semantic.applicability === "not_applicable" ? "적용 대상 아님" : JUDGMENTS[item.effective_judgment] ?? "판정 없음",tone:semantic.applicability === "not_applicable" ? "ended" : TONES[item.effective_judgment] ?? "neutral",attention:item.needs_attention,selected:semantic.requirement_id === selectedId};
}

export function evidenceEntries(item) {
  const original=item.semantic.original_requirement;
  const guide=[...original.citations,...original.subconditions.flatMap((child)=>child.citations),...(original.condition?.citations ?? []),...(item.page_rule?.rule ? [item.page_rule.rule.rule_citation,item.page_rule.rule.scope_citation] : [])];
  const report=[...item.semantic.evidence,...item.semantic.subconditions.flatMap((child)=>child.evidence)].map((evidence)=>evidence.citation);
  return [...guide.map((citation)=>({role:"guide",citation})),...report.map((citation)=>({role:"report",citation}))]
    .filter((entry,index,all)=>all.findIndex((other)=>other.role === entry.role && other.citation.block_id === entry.citation.block_id && other.citation.char_range.start === entry.citation.char_range.start && other.citation.char_range.end === entry.citation.char_range.end) === index);
}

export function quoteParts(text,range) {
  const points=Array.from(text);
  return [points.slice(0,range.start).join(""),points.slice(range.start,range.end).join(""),points.slice(range.end).join("")];
}

export function resolveEvidence(documents,entry) {
  const document=documents[entry.role];
  const citation=entry.citation;
  const block=document.blocks.find((value)=>value.block_id === citation.block_id);
  const page=citation.source_locator.original_page_number;
  if(!block) return null;
  if(document.representation === "source_structure") {
    if(page !== null || block.source_locator.path !== citation.source_locator.path) return null;
  } else if(!document.pages.some((value)=>value.page_number === page)) return null;
  if(citation.source_locator.source_sha256 !== document.source.content_sha256) return null;
  const {start,end}=citation.char_range;
  if(!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > Array.from(block.raw_text).length) return null;
  if(block.source_locator.original_page_number !== page || quoteParts(block.raw_text,citation.char_range)[1] !== citation.quote) return null;
  return {role:entry.role,page,citation};
}

export function pageSummary(pageRule) {
  if(!pageRule) return null;
  const assessment=pageRule.assessment?.assessment;
  return {count:assessment?.status === "verified" ? assessment.count : null,maximum:pageRule.rule?.maximum_pages ?? null,scopeVerified:pageRule.scope_subconditions.length > 0 && pageRule.scope_subconditions.every((scope)=>scope.status === "verified"),status:pageRule.status};
}

export function createLatestRequest() {
  let generation=0;
  return Object.freeze({async run(loader) {
    const request=++generation;
    try {
      const data=await loader();
      return request === generation ? {status:"ready",data} : {status:"stale"};
    } catch(error) {
      return request === generation ? {status:"error",error} : {status:"stale"};
    }
  }});
}

export function initialSelection() {
  return {role:"report",pages:{guide:1,report:1},blocks:{guide:null,report:null},citations:{guide:null,report:null}};
}

export function selectPage(selection,documents,target) {
  if(documents[target.role].representation === "source_structure") return {...selection,role:target.role,pages:{...selection.pages,[target.role]:null}};
  const page=Math.max(1,Math.min(documents[target.role].pages.length,target.page));
  const citation=selection.citations[target.role];
  return {...selection,role:target.role,pages:{...selection.pages,[target.role]:page},citations:{...selection.citations,[target.role]:citation?.source_locator.original_page_number === page ? citation : null}};
}

export function selectCitation(selection,documents,entry) {
  const resolved=resolveEvidence(documents,entry);
  return resolved ? {...selection,role:resolved.role,pages:{...selection.pages,[resolved.role]:resolved.page},blocks:{...selection.blocks,[resolved.role]:resolved.citation.block_id},citations:{...selection.citations,[resolved.role]:resolved.citation}} : selection;
}

export function selectBlock(selection,documents,blockId) {
  const role=selection.role;
  if(!documents[role].blocks.some((block)=>block.block_id === blockId)) return selection;
  return {...selection,blocks:{...selection.blocks,[role]:blockId},citations:{...selection.citations,[role]:selection.citations[role]?.block_id === blockId ? selection.citations[role] : null}};
}

export function blockChildren(document,blockId) {
  if(!document.blocks.some((block)=>block.block_id === blockId)) return [];
  return document.blocks.filter((block)=>block.parent_block_id === blockId);
}

export function statCounts(items) {
  const count=(...judgments)=>items.filter((item)=>judgments.includes(item.effective_judgment)).length;
  return {attention:items.filter((item)=>item.needs_attention).length,found:count("evidence_found"),missing:count("evidence_missing","explicit_noncompliance"),deferred:count("deferred","partially_satisfied"),total:items.length};
}
