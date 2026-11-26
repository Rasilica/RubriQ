import {PROVIDERS,editableItems} from './newsemantic.mjs';
const LABELS={evidence_found:'충족 근거 발견(AI)',partially_satisfied:'일부 충족(AI)',evidence_missing:'근거 미발견',deferred:'판정 보류'};
// Same tones as results/state.mjs; kept local because Node tests import these modules by file path.
const TONES={evidence_found:'success',partially_satisfied:'progress',evidence_missing:'soon',deferred:'attention'};
const chip=(element,judgment,excluded=false)=>element('span',`badge ${excluded?'ended':TONES[judgment]??'attention'}`,excluded?'검사 제외':LABELS[judgment]??'판정 보류');
function citationView({ui,citation,role,onEvidence}){
  const {element,button}=ui;const view=element('div','stack semantic-citation');
  if(citation.from_ocr)view.append(element('span','badge attention','글자 인식(오류 가능)'));
  view.append(element('blockquote','expression-quote',citation.quote),button(role==='guide'?'원문 보기':'보고서 근거 보기',()=>onEvidence({role,block_id:citation.block_id,...citation.char_range})));
  return view;
}
function criteriaList(element,title,entries){
  const detail=element('details','stack');const list=element('ol','stack criteria-list');
  for(const entry of entries){const row=element('li','',entry.excluded?`${entry.title} (검사 제외)`:entry.title);if(entry.parts.length){const parts=element('ul','');for(const part of entry.parts)parts.append(element('li','',part));row.append(parts);}list.append(row);}
  detail.append(element('summary','',title),list);return detail;
}
// Counts for the result summary tiles; excluded (not applicable) items are not counted.
export function resultCounts(items){
  const applicable=items.filter(item=>item.applicability!=='not_applicable');
  const count=(...judgments)=>applicable.filter(item=>judgments.includes(item.judgment)).length;
  return {attention:applicable.filter(item=>item.judgment!=='evidence_found').length,found:count('evidence_found'),missing:count('evidence_missing'),deferred:count('deferred','partially_satisfied',null),total:applicable.length};
}
export function renderTransmission({ui,target,context,session,demo=false}){
  const {element}=ui;target.replaceChildren(element('h3','','실행 전 범위 확인'),element('p','',`${PROVIDERS[context.provider]} · ${context.model} · 총 ${context.characters.toLocaleString('ko-KR')}자`),element('p','muted',demo?'아래는 검사에 사용하는 원문입니다. 체험 모드에서는 어디에도 전송하지 않습니다.':'아래의 읽은 원문과 시스템 지침을 사용합니다. 파일·이미지 자체는 보내지 않습니다. AI 판단은 누락되거나 틀릴 수 있습니다.'));
  if(context.characters>(context.stage==='check'?60000:20000))target.append(element('p','notice','문서가 길어 여러 번 나눠 전송합니다. 호출마다 비용이 발생합니다.'));
  if(context.criteria){target.append(criteriaList(element,'확정한 검사 기준 · 전체',context.criteria.map(c=>({title:c.title,parts:c.subconditions.map(sub=>sub.description),excluded:!c.included}))),criteriaList(element,'안내문에서 추출한 원래 요구사항 · 전체',context.original_requirements.map(r=>({title:r.title,parts:r.subconditions.map(sub=>sub.description)}))));}
  for(const [role,blocks] of Object.entries(context.blocks)){
    const section=element('details','stack');section.open=true;section.append(element('summary','',`${role==='guide'?'안내문':'보고서'} · 전송할 전체 텍스트`));
    if(session[role].extraction_status==='partial')section.append(element('p','notice','일부만 읽은 문서입니다. 누락된 내용은 검사할 수 없습니다.'));
    const doc=session[role].document;
    if((doc.warnings?.length??0)+(doc.typed_errors?.length??0))section.append(element('p','muted','읽는 중 확인이 필요한 부분이 있었습니다. 2단계 "읽은 내용 확인"에서 자세히 볼 수 있습니다.'));
    for(const block of blocks)section.append(element('blockquote','expression-quote',block.raw_text));target.append(section);
  }
}
export function renderCriteria({ui,target,draft,onEvidence,onEdit,readOnly=false}){
  const {element,field}=ui;let items=editableItems(draft.items);target.replaceChildren(element('h3','','요구사항 검토'),element('p','muted',readOnly?'저장 당시 확정한 요구사항 · 읽기 전용':draft.confirmed?'확정한 요구사항 · 수정하면 다시 확정해야 합니다.':'AI 초안 · 안내문 원문을 보고 제목·분류·포함 여부·조건 적용을 확인해주세요.'));
  if(!items.length)target.append(element('p','notice','추출된 요구사항이 없습니다. 안내문의 읽은 내용과 모델을 확인해주세요.'));
  for(const [index,item] of items.entries()){
    const article=element('article','expression-finding stack');article.setAttribute('aria-label',`요구사항 ${index+1}`);const prefix=`${readOnly?'saved-semantic':'semantic'}-item-${index}`;
    const change=patch=>{items=items.map((current,i)=>i===index?{...current,...patch}:current);onEdit(items);};
    const edit=(name,label,extra={})=>field({id:`${prefix}-${name}`,label,value:item[name]??'',onChange:value=>change({[name]:value||null}),...extra});
    const original=draft.requirements.find(r=>r.requirement_id===item.requirement_id);article.append(element('h4','',`요구사항 ${index+1}`),edit('title','요구사항 제목'),edit('classification','분류',{options:[['required','필수'],['optional','선택'],['conditional','조건부']],onChange:value=>{change({classification:value,...(value==='conditional'?{}:{condition_description:null,application_status:'applies',application_reason:null})});renderCriteria({ui,target,draft:{...draft,items,confirmed:false},onEvidence,onEdit});}}));
    const label=element('label','cluster');const included=element('input');included.type='checkbox';included.id=`${prefix}-included`;included.checked=item.included;label.htmlFor=included.id;label.append(included,element('span','','검사 기준에 포함'));included.addEventListener('change',()=>change({included:included.checked}));article.append(label,edit('exclusion_reason','제외 사유 · 제외할 때 필수'));
    const conditions=element('div','stack');conditions.hidden=item.classification!=='conditional';conditions.append(edit('condition_description','조건 설명 · 조건부 항목에 필수'),edit('application_status','조건 적용 여부',{options:[['undetermined','미결정 · 확인 필요'],['applies','적용'],['does_not_apply','적용하지 않음']]}),edit('application_reason','조건 적용 사유 · 조건부 항목에 필수'));article.append(conditions);
    for(const [subindex,sub] of item.subconditions.entries())article.append(field({id:`${prefix}-sub-${subindex}`,label:`세부 조건 ${subindex+1}`,value:sub.description,onChange:value=>{const current=items[index];change({subconditions:current.subconditions.map((s,i)=>i===subindex?{...s,description:value}:s)});}}));
    const source=element('details','stack');source.append(element('summary','','AI 초안의 안내문 원문 근거'));
    for(const part of [original,...original.subconditions,...(original.condition?[original.condition]:[])])for(const citation of part.citations)source.append(citationView({ui,citation,role:'guide',onEvidence}));article.append(source);target.append(article);
  }
  if(readOnly)for(const control of target.querySelectorAll('input,select,textarea'))control.disabled=true;
}
export function renderSemanticResults({ui,target,result,onEvidence}){
  const {element}=ui;target.replaceChildren(element('h3','','보고서 AI 검사 결과'),element('p','notice','인용 문구의 원문 일치를 확인했습니다. 근거의 의미·충족 여부는 AI 판단이므로 직접 검토해주세요. 점수·합격 판정이 아닙니다.'));
  if(result.guide_extraction_status==='partial'||result.report_extraction_status==='partial')target.append(element('p','notice','일부만 읽은 문서가 있어 검사 범위가 제한됩니다. 누락된 내용은 판정할 수 없습니다.'));
  for(const item of result.items){
    const article=element('article','expression-finding stack');const status=element('p','');status.append(chip(element,item.judgment,item.applicability==='not_applicable'));article.append(element('h4','',item.criterion.title),status,element('p','',item.reason??'확정한 기준에 따라 제외했습니다.'));
    for(const finding of [item,...item.subconditions]){
      if(finding!==item){const at=item.criterion.subconditions.findIndex(sub=>sub.subcondition_id===finding.subcondition_id);const heading=element('h4','cluster',at<0?'세부 조건':`세부 조건 ${at+1} · ${item.criterion.subconditions[at].description}`);heading.append(chip(element,finding.judgment));article.append(heading,element('p','',finding.reason));}
      for(const evidence of finding.evidence){article.append(citationView({ui,citation:evidence.citation,role:'report',onEvidence}));if(evidence.relation)article.append(element('p','muted',`AI 근거 해석: ${evidence.relation}`));}
    }target.append(article);
  }
}

export function renderSemanticArchive({ui,target,archive,onEvidence}){
  const {element}=ui;
  target.replaceChildren(element('h3','','저장한 검사 기록'),element('p','notice','저장 당시의 기록을 그대로 열었습니다. 다시 열기에는 새 AI 호출이나 비용이 발생하지 않습니다.'));
  // Results first; the saved criteria are reference material, so they start folded.
  if(archive.check){const results=element('div','stack');renderSemanticResults({ui,target:results,result:archive.check.result,onEvidence});target.append(results,element('p','muted',`${PROVIDERS[archive.check.provider]} · ${archive.check.model} · 저장된 AI 검사 결과 · 재실행 없음`));}
  else target.append(element('p','notice','저장된 AI 검사 결과가 없습니다. 확정한 요구사항만 보관한 기록입니다.'));
  const criteria=element('details','stack');criteria.open=!archive.check;criteria.append(element('summary','','저장 당시 확정한 요구사항 보기'));
  const list=element('div','stack');renderCriteria({ui,target:list,draft:archive.draft,onEvidence,readOnly:true});
  criteria.append(list,element('p','muted',`${PROVIDERS[archive.draft.provider]} · ${archive.draft.model} · 저장된 확정 기준`));target.append(criteria);
}
