import {credentialChoice,keyStatusText} from './ai-settings.mjs';
import {diagnosticMessage} from './ai-diagnostic.mjs';
import {renderCriteria,renderSemanticResults,renderTransmission,renderSemanticArchive} from './semantic-view.mjs';
import {validateOllamaModels} from './ollama.mjs';
import {reveal} from './state.mjs';
export const PROVIDERS={gemini:'Gemini',openai:'OpenAI (GPT)',anthropic:'Anthropic (Claude)',billingai:'빌링AI',ollama:'Ollama · 로컬',demo:'체험 모드 · 저장된 예시'};
const keyless=provider=>provider==='ollama'||provider==='demo';
const DEMO_MODEL='offline-example';
const ERROR_NOTICES={ai_demo_sample_only:'체험 모드는 동봉한 샘플 문서만 검사합니다. samples/pdf 폴더의 guide.pdf와 normal.pdf · missing.pdf · paraphrased.pdf 중 하나를 올려주세요.',ai_demo_mode_mismatch:'현재 실행 모드에서 사용할 수 없는 AI 선택입니다. 실행 창을 닫고 알맞은 모드로 다시 시작해주세요.'};
const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/u.test(value);
const keyValid=value=>typeof value==='string'&&/^[\x21-\x7e]{1,512}$/u.test(value);
// 서버는 20,000자(추출 최대 3회)·60,000자(검사 최대 5회) 단위로 나눠 보내므로 화면은 호출 상한 총합만 확인한다.
const MAX_REQUIREMENT_CHARACTERS=60000,MAX_CHECK_CHARACTERS=300000,MAX_BLOCKS=2000;
const need=value=>{if(!value)throw new Error('invalid_semantic_context');};
const confirmationRejected=error=>error?.status===422&&['application_undetermined','application_reason_required','invalid_condition','exclusion_reason_required','empty_criteria','immutable_identity','invalid_request'].includes(error.code);
export function editableItems(items){return items.map(({requirement_id,title,classification,condition_description,subconditions,included,exclusion_reason,application_status,application_reason})=>({requirement_id,title,classification,condition_description,subconditions:subconditions.map(({subcondition_id,description})=>({subcondition_id,description})),included,exclusion_reason,application_status,application_reason}));}
export function semanticPreview({session,provider,model,stage,draft}){
  need(Object.hasOwn(PROVIDERS,provider)&&typeof model==='string'&&(provider==='ollama'?/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/u:/^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/u).test(model));
  need(stage==='requirements'||stage==='check');const roles=stage==='check'?['guide','report']:['guide'];
  const blocks={};let characters=0,count=0;
  for(const role of roles){const doc=session[role]?.document;need(doc&&hash(doc.source.content_sha256));blocks[role]=doc.blocks.map(({block_id,raw_text})=>({block_id,raw_text}));count+=blocks[role].length;characters+=blocks[role].reduce((sum,b)=>sum+[...b.raw_text].length,0);}
  need(characters>0&&characters<=(stage==='check'?MAX_CHECK_CHARACTERS:MAX_REQUIREMENT_CHARACTERS)&&count<=MAX_BLOCKS);
  if(stage==='check'){
    need(draft?.confirmed===true&&hash(draft.criteria_sha256)&&draft.guide_sha256===session.guide.document.source.content_sha256);
    const size=text=>[...(text??'')].length;
    const criteriaSize=draft.items.reduce((sum,item)=>sum+size(item.title)+size(item.condition_description)+size(item.exclusion_reason)+size(item.application_reason)+item.subconditions.reduce((n,sub)=>n+size(sub.description),0),0);
    const originalSize=draft.requirements.reduce((sum,item)=>sum+size(item.title)+size(item.condition?.description)+item.subconditions.reduce((n,sub)=>n+size(sub.description),0),0);
    need(characters+criteriaSize+originalSize<=MAX_CHECK_CHARACTERS);
  }
  return {stage,provider,model,blocks,characters,count,guide_sha256:session.guide.document.source.content_sha256,...(stage==='check'?{draft_id:draft.draft_id,criteria_sha256:draft.criteria_sha256,report_sha256:session.report.document.source.content_sha256,criteria:editableItems(draft.items),original_requirements:draft.requirements}:{})};
}
export function validateCitation(citation,doc){
  const b=doc.blocks.find(block=>block.block_id===citation?.block_id),r=citation?.char_range;
  need(b&&citation.verification==='exact_quote'&&Number.isSafeInteger(r?.start)&&Number.isSafeInteger(r?.end)&&r.start>=0&&r.end>r.start&&r.end<=[...b.raw_text].length&&[...b.raw_text].slice(r.start,r.end).join('')===citation.quote);return citation;
}
export function validateDraft(value,context,session){
  need(value?.ai_called===true&&value.guide_sha256===context.guide_sha256&&value.provider===context.provider&&value.model===context.model);
  need(typeof value.draft_id==='string'&&value.draft_id&&Number.isSafeInteger(value.revision)&&value.revision>=0&&Array.isArray(value.items)&&value.items.length<=100&&Array.isArray(value.requirements)&&value.items.length===value.requirements.length);
  need(typeof value.confirmed==='boolean'&&(value.confirmed?hash(value.criteria_sha256):value.criteria_sha256===null));
  const ids=new Set();for(const item of value.items){need(typeof item.title==='string'&&['required','optional','conditional'].includes(item.classification)&&Array.isArray(item.subconditions));need(!ids.has(item.requirement_id));ids.add(item.requirement_id);}
  for(const req of value.requirements){need(ids.has(req.requirement_id)&&Array.isArray(req.citations));for(const cited of [req,...req.subconditions, ...(req.condition?[req.condition]:[])])for(const c of cited.citations)validateCitation(c,session.guide.document);}
  return value;
}
export function validateCheck(value,context,session){
  need(value?.ai_called===true&&value.provider===context.provider&&value.model===context.model);const result=value.result;
  need(result&&result.fake!==true&&result.ai_called!==false&&result.criteria_sha256===context.criteria_sha256&&result.report_source_sha256===context.report_sha256&&Array.isArray(result.items)&&result.items.length===context.criteria.length);
  const ids=new Set();for(const item of result.items){need(context.criteria.some(c=>c.requirement_id===item.requirement_id)&&!ids.has(item.requirement_id));ids.add(item.requirement_id);
    for(const finding of [item,...item.subconditions]){need(['evidence_found','partially_satisfied','evidence_missing','deferred',null].includes(finding.judgment));for(const e of finding.evidence)validateCitation(e.citation,session.report.document);}
  }return result;
}
export function validateSemanticArchive(archive,session){
  if(archive==null)return null;
  const stored=archive.draft;need(stored?.confirmed===true&&Object.hasOwn(PROVIDERS,stored.provider)&&typeof stored.model==='string'&&stored.model);
  validateDraft(stored,{guide_sha256:session.guide.document.source.content_sha256,provider:stored.provider,model:stored.model},session);
  if(archive.check!==null){
    const check=archive.check;need(check&&Object.hasOwn(PROVIDERS,check.provider)&&typeof check.model==='string'&&check.model);
    const result=validateCheck(check,{provider:check.provider,model:check.model,criteria_sha256:stored.criteria_sha256,report_sha256:session.report.document.source.content_sha256,criteria:stored.items},session);
    for(const item of result.items){const criterion=stored.items.find(c=>c.requirement_id===item.requirement_id);need(JSON.stringify(editableItems([item.criterion]))===JSON.stringify(editableItems([criterion])));}
  }
  return archive;
}
export function mountSemanticPanel({ui,api,session,onEvidence,onComplete,onExpired,keyStatus,onSaveState,onProgress,demo=false}){
  const {element,button,field}=ui;let draft,preview,dirty=false,running=false,confirming=false,disposed=false,epoch=0,controller;const abort=()=>{epoch++;controller?.abort();running=false;confirming=false;};
  const panel=element('section','panel stack semantic-panel');panel.id='semantic-panel';panel.setAttribute('aria-labelledby','semantic-heading');
  const heading=element('h2','',demo?'요구사항 검사 · 체험':'AI 요구사항 검사');heading.id='semantic-heading';
  const status=element('div','stack');status.id='semantic-status';status.setAttribute('aria-live','polite');
  const transmission=element('div','stack');transmission.id='semantic-preview';
  const archived=element('div','stack');archived.id='semantic-archive';
  const editor=element('div','stack');editor.id='semantic-criteria';const results=element('div','stack');results.id='semantic-results';
  const say=(text,error=false)=>{const n=element('p',`notice${error?' error':''}`,text);n.setAttribute('role',error?'alert':'status');status.replaceChildren(n);if(error){n.setAttribute('tabindex','-1');reveal(n);}};
  const providerField=field({id:'semantic-provider',label:'AI 제공자',options:[['','제공자 선택'],...Object.entries(PROVIDERS).filter(([id])=>(id==='demo')===demo)],onChange:()=>{key.value='';invalidate();keyField.hidden=keyless(provider.value);billingHelp.hidden=provider.value!=='billingai';discover.hidden=provider.value!=='ollama';models.replaceChildren();}});const provider=providerField.querySelector('select');
  const billingHelp=element('p','muted','빌링AI에서 발급한 API 키와 접두어 없는 모델 ID(예: gpt-5-4, claude-sonnet-4-6, gemini-2-5-flash)를 입력하세요. 빌링AI와 선택한 모델의 실제 제공자에게 표시한 범위가 전송되며 크레딧이 차감될 수 있습니다. 직접 입력한 키는 요청 직후 비웁니다. ');billingHelp.id='semantic-billing-help';billingHelp.hidden=true;
  const billingDocs=element('a','','빌링AI 모델·요금 문서');billingDocs.href='https://billing-ai.doublezero.kr/docs/text';billingDocs.target='_blank';billingDocs.rel='noopener noreferrer';billingHelp.append(billingDocs);
  const modelField=field({id:'semantic-model',label:'모델 ID',help:'클라우드는 공식 서비스 모델 ID, Ollama는 이 컴퓨터에 설치된 정확한 모델 ID(예: qwen3:8b)를 직접 입력하세요.',onChange:()=>invalidate()});const model=modelField.querySelector('input');model.maxLength=200;model.autocomplete='off';model.spellcheck=false;
  const keyField=field({id:'semantic-api-key',label:'이번 요청의 API 키 · 저장된 키 대신 사용 (선택)',onChange:()=>invalidate()});const key=keyField.querySelector('input');key.type='password';key.maxLength=512;key.autocomplete='off';key.spellcheck=false;
  const savedStatus=element('p','muted');savedStatus.id='semantic-key-status';
  const models=element('div','stack');models.id='semantic-models';
  const discover=button('설치된 Ollama 모델 확인',async()=>{
    if(running||disposed)return;abort();const current=epoch;controller=new AbortController();running=true;controls();
    try{const list=validateOllamaModels(await api.ollamaModels(session,controller.signal));if(disposed||epoch!==current)return;models.replaceChildren(element('p','muted',list.length?list.map(m=>m.name).join(' · '):'설치된 모델이 없습니다.'));}
    catch(error){if(!disposed&&epoch===current)failure(error);}
    finally{if(epoch===current){running=false;controls();}}
  });discover.id='semantic-models-button';discover.hidden=true;
  const consentLabel=element('label','cluster');const consent=element('input');consent.id='semantic-consent';consent.type='checkbox';consentLabel.htmlFor=consent.id;const consentText=element('span');consentLabel.append(consent,consentText);consent.addEventListener('change',controls);
  const first=button(demo?'안내문에서 사용할 내용 미리보기':'안내문에서 AI로 보낼 내용 미리보기',()=>makePreview('requirements'));first.id='semantic-requirements-preview';
  const resume=button('저장한 기준으로 새 검사 준비',()=>resumeCriteria());resume.id='semantic-resume';resume.hidden=true;
  const confirm=button('수정한 요구사항 확인·확정',()=>confirmCriteria());confirm.id='semantic-confirm';
  const second=button(demo?'보고서 검사에 사용할 내용 미리보기':'보고서 검사에 보낼 내용 미리보기',()=>makePreview('check'));second.id='semantic-check-preview';
  const submit=button(demo?'저장된 예시 결과 보기':'동의한 범위로 AI 실행',()=>run());submit.id='semantic-submit';
  function controls(){
    savedStatus.textContent=keyStatusText(provider.value,keyStatus);
    for(const control of [provider,model,key,discover,first,resume,confirm,second,submit,consent])control.disabled=disposed||running;
    resume.disabled=disposed||running||!!draft;savedNote.hidden=!!draft||!archive;
    confirm.disabled=disposed||running||!draft||(draft.confirmed&&!dirty);second.disabled=disposed||running||!draft?.confirmed;submit.disabled=disposed||running||!preview||!consent.checked;consent.disabled=disposed||running||!preview;
    for(const control of editor.querySelectorAll('input,select,textarea'))control.disabled=disposed||running;
    panel.setAttribute('aria-busy',String(running));onSaveState?.(saveState());onProgress?.(progress());
  }
  function progress(){
    const saved=!draft&&!!archive;
    return {draft:!!draft||saved,confirmed:(!!draft?.confirmed&&!dirty)||saved,checked:results.children.length>0||(saved&&archive.check!==null)};
  }
  function saveState(){return {allowed:!disposed&&!running&&!dirty,reason:dirty?'수정한 요구사항을 먼저 확인·확정한 뒤 보관해주세요.':running?'AI 작업이 끝난 뒤 보관해주세요.':''};}
  function invalidate(){abort();preview=undefined;consent.checked=false;transmission.replaceChildren();controls();}
  function makePreview(stage){
    invalidate();try{const credentials=credentialChoice(provider.value,key.value,keyStatus);preview={...semanticPreview({session,provider:provider.value,model:model.value.trim(),stage,draft}),useSavedKey:credentials.useSavedKey};
      consentText.textContent=provider.value==='demo'?'실제 AI를 호출하지 않고, 미리 저장한 예시 결과를 보여주는 것을 확인합니다.':provider.value==='ollama'?'표시한 범위와 시스템 지침을 이 컴퓨터의 Ollama에서 실행하는 것을 확인합니다.':provider.value==='billingai'?'표시한 범위와 시스템 지침을 빌링AI 및 선택한 모델의 실제 제공자에게 전송하며, 크레딧이 차감될 수 있습니다. 이에 동의합니다.':'표시한 범위와 시스템 지침을 선택한 외부 제공자에게 전송하며, 비용이 발생할 수 있습니다. 이에 동의합니다.';
      renderTransmission({ui,target:transmission,context:preview,session,demo});transmission.append(consentLabel);say('범위를 확인한 뒤 실행에 동의해주세요.');controls();reveal(consent);
    }catch{say('제공자·모델 ID·API 키와 문서를 확인해주세요. 키는 공백 없는 ASCII 문자 512자까지입니다. 안내문이 20,000자를 넘으면 요구사항 추출을 최대 3회, 검사 입력(안내문·보고서·검사 기준 합계)이 60,000자를 넘으면 검사를 최대 5회로 나눠 보냅니다. 한 문단이나 셀이 한도보다 길면 보낼 수 없고 문서를 잘라 보내지 않습니다.',true);}
  }
  function failure(error,confirmation=false){
    if(error?.status===404){onExpired();return;}
    if(confirmation){
      if(error?.status===409&&error.code==='version_limit')say('내용을 바꿔 확정한 요구사항 버전이 20개 한도에 도달했습니다. 입력한 수정은 유지됩니다. 계속하려면 안내문 전송 범위를 미리보고 동의하여 새 요구사항을 추출해주세요. 새 추출은 AI를 호출하며 클라우드 비용이 발생할 수 있습니다.',true);
      else if(confirmationRejected(error))say('요구사항이 확정되지 않았습니다. 조건 적용 여부와 사유 등 입력을 확인한 뒤 다시 확정해주세요. AI를 호출하지 않는 무료 재시도입니다. '+(dirty?'입력한 수정은 확정 후 보관할 수 있습니다.':'수정하지 않은 초안은 확정 기준 없이 문서만 보관할 수 있습니다.'),true);
      else say(error?.status===409?'서버의 다른 확정 상태와 충돌했습니다. 입력한 수정은 유지됩니다. 다른 창의 작업 상태를 확인해주세요. 확정은 AI를 호출하지 않으며 무료입니다.':'요구사항 확정 응답을 확인하지 못했습니다. 연결 상태와 요구사항의 조건 적용 여부·사유를 살펴본 뒤 같은 항목으로 수정한 요구사항 확인·확정을 다시 눌러주세요. AI를 호출하지 않는 무료 재시도입니다.',true);
      return;
    }
    if(Object.hasOwn(ERROR_NOTICES,error?.code)){say(ERROR_NOTICES[error.code],true);return;}
    const detail=diagnosticMessage(error?.diagnostic);
    say(`요청을 완료하지 못했습니다. ${detail||'상세 원인은 확인되지 않았습니다.'} 범위를 다시 미리보고 동의해야 재시도할 수 있습니다. 이전 요청이 처리되었을 수 있어 클라우드 재요청에는 비용이 발생할 수 있습니다.`,true);
  }
  function showEditor(){renderCriteria({ui,target:editor,draft,onEvidence,onEdit:items=>{dirty=true;draft={...draft,items,confirmed:false,criteria_sha256:null};results.replaceChildren();onComplete(false);invalidate();say('요구사항을 수정했습니다. 다시 확정한 뒤 검사해주세요.');}});}
  async function resumeCriteria(){
    if(running||disposed||draft||!archive)return;invalidate();const current=epoch;controller=new AbortController();running=true;controls();
    try{
      const value=await api.aiCurrentCriteria(session,archive.draft.draft_id,controller.signal);if(disposed||epoch!==current)return;
      const checked=validateDraft(value,archive.draft,session);need(checked.confirmed&&checked.draft_id===archive.draft.draft_id&&checked.criteria_sha256===archive.draft.criteria_sha256);
      draft=checked;dirty=false;provider.value=checked.provider;model.value=checked.model;key.value='';keyField.hidden=keyless(provider.value);billingHelp.hidden=provider.value!=='billingai';discover.hidden=provider.value!=='ollama';applyDemo();models.replaceChildren();results.replaceChildren();onComplete(false);showEditor();
      say('저장한 기준을 새 검사의 기준으로 준비했습니다. 이 준비는 AI를 호출하지 않는 무료 처리입니다. 이전 저장 결과는 아래에 별도로 유지됩니다. 보고서 검사 범위를 미리보고 동의한 뒤 실행해주세요.');
    }catch(error){if(!disposed&&epoch===current){if(error?.status===404)onExpired();else say('저장한 기준을 새 검사에 사용할 수 있는지 확인하지 못했습니다. 저장 결과는 유지됩니다. 연결과 저장 자료를 확인한 뒤 다시 준비해주세요. 이 준비는 AI를 호출하지 않는 무료 처리입니다.',true);}}
    finally{if(epoch===current){running=false;controls();}}
  }
  async function confirmCriteria(){
    if(running||!draft||disposed||(draft.confirmed&&!dirty))return;const previouslyDirty=dirty;dirty=true;results.replaceChildren();onComplete(false);invalidate();const current=epoch;controller=new AbortController();running=true;confirming=true;controls();
    try{const value=await api.aiCriteria(session,{draft_id:draft.draft_id,expected_revision:draft.revision,items:editableItems(draft.items)},controller.signal);if(disposed||epoch!==current)return;
      const checked=validateDraft(value,{...draft},session);need(checked.draft_id===draft.draft_id&&checked.revision>=draft.revision&&checked.confirmed);draft=checked;dirty=false;results.replaceChildren();onComplete(false);showEditor();say('요구사항을 확정했습니다. AI 호출 없이 저장한 임시 기준입니다. 이제 보고서 검사 범위를 확인하세요.');
    }catch(error){if(!disposed&&epoch===current){
      if(error?.status===409&&error.code==='stale_revision')await syncCriteriaRevision(current);
      else{if(confirmationRejected(error))dirty=previouslyDirty;failure(error,true);}
    }}finally{if(epoch===current){running=false;confirming=false;controls();}}
  }
  async function syncCriteriaRevision(current){
    try{
      const value=await api.aiCurrentCriteria(session,draft.draft_id,controller.signal);if(disposed||epoch!==current)return;
      const checked=validateDraft(value,draft,session);need(checked.draft_id===draft.draft_id&&checked.revision>draft.revision&&checked.confirmed);
      need(JSON.stringify(checked.items.map(item=>item.requirement_id))===JSON.stringify(draft.items.map(item=>item.requirement_id)));
      draft={...draft,revision:checked.revision,confirmed:false,criteria_sha256:null};
      say('서버의 최신 확정 버전을 확인했습니다. 입력한 수정은 그대로 유지됩니다. 수정한 요구사항 확인·확정을 다시 눌러 현재 입력을 확정해주세요. AI를 호출하지 않는 무료 재시도입니다.');
    }catch(error){if(!disposed&&epoch===current){if(error?.status===404)onExpired();else say('서버의 최신 확정 상태를 확인하지 못했습니다. 입력한 수정은 유지됩니다. 연결을 확인한 뒤 수정한 요구사항 확인·확정을 다시 눌러주세요. 확인과 확정은 AI를 호출하지 않으며 무료입니다.',true);}}
  }
  async function run(){
    if(running||disposed||!preview||!consent.checked)return;const context=preview;let apiKey=key.value;key.value='';invalidate();const current=epoch;controller=new AbortController();
    try{need(keyless(context.provider)||(context.useSavedKey?!apiKey:keyValid(apiKey)));running=true;controls();say(context.stage==='requirements'?'안내문에서 요구사항을 추출 중입니다.':'확정한 요구사항과 보고서를 검사 중입니다.');
      const body={provider:context.provider,model:context.model,consent:true,use_saved_key:context.useSavedKey===true,guide_sha256:context.guide_sha256};const options={signal:controller.signal,...(keyless(context.provider)||context.useSavedKey?{}:{apiKey})};
      const value=context.stage==='requirements'?await api.aiRequirements(session,body,options):await api.aiCheck(session,{...body,draft_id:context.draft_id,criteria_sha256:context.criteria_sha256,report_sha256:context.report_sha256},options);
      if(disposed||epoch!==current)return;need(!apiKey||!JSON.stringify(value).includes(apiKey));
      if(context.stage==='requirements'){draft=validateDraft(value,context,session);dirty=false;archived.replaceChildren();results.replaceChildren();onComplete(false);showEditor();say('요구사항 초안입니다. 원문·분류·조건을 직접 검토하고 확정해주세요. 보고서 의미 검사는 아직 실행하지 않았습니다.');}
      else{const result=validateCheck(value,context,session);renderSemanticResults({ui,target:results,result,onEvidence});results.append(element('p','muted',`${PROVIDERS[context.provider]} · ${context.model} · 임시 검사 결과`));onComplete(true,true,result.items);say(demo?'체험 모드 결과입니다. 실제 AI가 검사하지 않았으며 미리 저장한 예시를 보여줍니다.':`${PROVIDERS[context.provider]} · ${context.model} · AI 의미 검사 완료. 원문 인용의 일치만 검증하며 AI 판단의 정확성이나 요구사항 전체 충족을 보장하지 않습니다.`);}
    }catch(error){if(!disposed&&epoch===current)failure(error);}finally{apiKey='';if(epoch===current){running=false;controls();}}
  }
  const unsubscribe=keyStatus?.subscribe(()=>{key.value='';if(confirming){controls();return;}invalidate();});
  // Each group belongs to the wizard steps it is shown in (3 뽑기 · 4 확정 · 5 검사 · 6 결과).
  const savedNote=element('p','notice','저장한 요구사항은 6단계 결과·보관에서 볼 수 있습니다. 같은 기준으로 다시 검사하려면 5단계에서 "저장한 기준으로 새 검사 준비"를 누르세요.');savedNote.id='semantic-saved-note';
  const group=(id,steps,...children)=>{const node=element('div','stack');node.id=id;node.append(...children);return {node,steps};};
  const groups=[
    group('semantic-setup',[3,5],element('p','muted',demo?'체험 모드는 저장된 예시 결과를 사용합니다. 외부로 전송하지 않으며 비용이 없습니다.':'클라우드 AI는 표시한 문구를 외부로 전송하며 비용이 발생할 수 있습니다. Ollama는 이 컴퓨터에서 실행합니다.'),providerField,billingHelp,modelField,savedStatus,keyField,discover,models),
    group('semantic-extract',[3],first),
    group('semantic-check-group',[5],resume,second),
    group('semantic-run',[3,5],transmission,submit),
    group('semantic-editor-group',[4],savedNote,editor,confirm),
    group('semantic-archive-group',[],archived),
    group('semantic-results-group',[6],results),
  ];
  panel.append(heading,status,...groups.map(g=>g.node));
  function show(step){for(const g of groups)g.node.hidden=!g.steps.includes(step);}
  const archive=validateSemanticArchive(session.semantic_archive,session);
  if(archive){renderSemanticArchive({ui,target:archived,archive,onEvidence});resume.hidden=false;groups.find(g=>g.node.id==='semantic-archive-group').steps.push(archive.check?6:4);onComplete(archive.check!==null,false,archive.check?.result.items);}
  function applyDemo(){
    if(!demo)return;provider.value='demo';model.value=DEMO_MODEL;
    for(const node of [providerField,modelField,keyField,savedStatus])node.hidden=true;
  }
  applyDemo();controls();
  return {panel,saveState,progress,show,dispose(){unsubscribe?.();disposed=true;key.value='';draft=undefined;invalidate();archived.replaceChildren();editor.replaceChildren();results.replaceChildren();models.replaceChildren();status.replaceChildren();}};
}
