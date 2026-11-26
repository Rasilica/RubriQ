import {mountKeySettings} from './ai-settings.mjs';
import {element,button,field} from '/review-assets/primitives.mjs';
import {createAPI} from './api.mjs';
import {mountSemanticPanel} from './newsemantic.mjs';
import {mountCloudPanel} from './newcloud.mjs';
import {mountLibrary} from './library.mjs';
import {environmentText} from './library-api.mjs';
import {createExpressionCheck,expressionSelection,textareaRange} from './expression.mjs';
import {createOllamaRequest,ollamaSelection,validateOllamaModels,validateOllamaRewrite} from './ollama.mjs';
import {ROLES,STATUS,KINDS,createResources,initialSelection,selectBlock,selectPage,unicodeRange,mappingMatches,warningText,errorText as preparationErrorText,reveal} from './state.mjs';
import {renderMappingResult} from './mapping.mjs';
const LOW_OCR_CONFIDENCE=0.5;
import {STEPS,reachableStep,clampStep,stepHelp,pageTitle} from './wizard.mjs';
import {locationLabel,omittedSummary} from './location.mjs';
import {resultCounts} from './semantic-view.mjs';
import {statTile} from '/brand-assets/stats.mjs';
import {createPillTabs,createToaster,mountDropzone,skeleton,bloom} from '/brand-assets/lucian.mjs';

const api=createAPI();const resources=createResources();
const settings=mountKeySettings({ui:{element,button,field}});const keyStatus=settings.status;
const demo=document.body.dataset.demo==='true';
if(!demo)document.querySelector('#ai-settings-container').append(settings.panel);
const form=document.querySelector('#prepare-form');
const workspace=document.querySelector('#prepared-workspace');
const structure=document.querySelector('#structure-pane');const viewer=document.querySelector('#pdf-pane');
const message=document.querySelector('#prepare-message');const bar=document.querySelector('#session-bar');
let session=null;let role='guide';let selection=initialSelection();let expiryTimer;
let preparing=false;let cloudPanel;let semanticPanel;let step=1;let reached=1;let returnStep=null;
const DELETED='임시 문서를 삭제했습니다.';
const toaster=createToaster();
const roleTabs=createPillTabs({label:'확인할 문서',options:Object.entries(ROLES),value:role,onSelect:value=>{role=value;render();roleTabs.focus();}});
const fileHint='PDF · DOCX · HWP · HWPX · 10 MiB 이하';
mountDropzone(document.querySelector('#guide-file'),{title:'안내문',hint:fileHint});
mountDropzone(document.querySelector('#report-file'),{title:'보고서',hint:fileHint});
const semanticContainer=document.querySelector('#semantic-container');
function semanticStatus(complete,live=false,items=[]){
  if(live)toaster.push('AI 의미 검사를 마쳤습니다','결과는 원문과 직접 비교해주세요.');
  const tiles=document.querySelector('#result-stats');if(!complete){tiles.replaceChildren();return;}
  const counts=resultCounts(items);
  tiles.replaceChildren(statTile('critical','확인 필요',counts.attention,'근거가 확인되지 않아 직접 볼 항목'),statTile('default','근거 확인',counts.found,'보고서에서 근거를 찾은 항목'),statTile('default','근거 미확인',counts.missing,'근거를 찾지 못한 항목'),statTile('attention','판정 보류',counts.deferred,'일부 충족이거나 더 확인할 항목'));
}
const stepTargets=[...document.querySelectorAll('[data-steps]')];
function progress(){return {prepared:!!session,...(semanticPanel?.progress()??{})};}
function setStep(target,{focus=true}={}){
  step=clampStep(target,progress());
  for(const node of stepTargets)node.hidden=!node.dataset.steps.split(' ').map(Number).includes(step);
  document.querySelector('.prepare-layout').dataset.step=String(step);semanticPanel?.show(step);renderSteps();
  if(focus){document.querySelector('#step-heading').focus({preventScroll:true});document.querySelector('.step-nav').scrollIntoView({block:'start'});}
}
function renderSteps(){
  const furthest=reachableStep(progress());
  document.querySelector('#step-list').replaceChildren(...STEPS.map(item=>{
    const state=item.id===step?'current':item.id<furthest||(item.id===furthest&&item.id<step)?'done':item.id<=furthest?'open':'locked';
    const control=element('button',`step-item ${state}`);control.type='button';control.disabled=item.id>furthest;
    control.append(element('span','step-number',String(item.id)),element('span','step-label',item.label));
    if(item.id===step)control.setAttribute('aria-current','step');
    control.addEventListener('click',()=>{returnStep=null;setStep(item.id);});
    const row=element('li','');row.append(control);return row;
  }));
  const current=STEPS[step-1];
  document.querySelector('#step-heading').replaceChildren(element('p','eyebrow',`${step}단계 / ${STEPS.length}단계`),element('h2','',current.label),element('p','muted',stepHelp(step,demo)));document.title=pageTitle(step);
  const footer=document.querySelector('#step-footer');footer.replaceChildren();if(!session)return;
  if(returnStep){footer.append(button(`${STEPS[returnStep-1].label}(으)로 돌아가기`,()=>{const back=returnStep;returnStep=null;setStep(back);}));return;}
  if(step>1)footer.append(button(`이전: ${STEPS[step-2].label}`,()=>setStep(step-1)));
  if(step<STEPS.length){
    const next=button(`다음: ${STEPS[step].label}`,()=>setStep(step+1));next.classList.add('primary');next.disabled=step+1>furthest;
    footer.append(next);if(next.disabled)footer.append(element('p','muted step-blocked','이 단계를 마치면 다음으로 넘어갈 수 있습니다.'));
  }
}
// When a stage finishes while its step is open, move on to the step it unlocked.
function progressChanged(){
  const furthest=reachableStep(progress());
  if(furthest>reached&&step===reached&&!returnStep){reached=furthest;setStep(furthest);return;}
  reached=furthest;if(step>furthest)setStep(furthest,{focus:false});else renderSteps();
}
function clearSemantic(){semanticPanel?.dispose();semanticPanel=undefined;semanticContainer.replaceChildren();semanticStatus(false);}
function semanticEvidence(evidence){
  const block=session?.[evidence.role]?.document?.blocks.find(item=>item.block_id===evidence.block_id);if(!block)return;
  if(step!==2)returnStep=step;role=evidence.role;selection=selectBlock(selection,role,block.block_id);setStep(2,{focus:false});render();
  const text=document.querySelector('#source-text');const range=textareaRange(block.raw_text,evidence);text.focus();text.setSelectionRange(range.start,range.end);text.scrollIntoView({block:'nearest'});
  if(session[role].artifact_kind)void mapQuote(block,{start:evidence.start,end:evidence.end});
}

const library=mountLibrary({getSession:()=>session,canOpen:()=>!session&&!preparing,acceptSession:activateSession,setOpening:busy,getSaveState:()=>semanticPanel?.saveState(),notify:(title,detail)=>toaster.push(title,detail)});
function notice(text,error=false){const node=element('p',`notice${error?' error':''}`,text);node.setAttribute('role',error?'alert':'status');return node;}
function errorText(error){
  if(error?.status===404)return '세션이 만료되었거나 접근할 수 없습니다. 문서를 다시 준비해주세요.';
  if(error?.status===429)return '요청이 많습니다. 잠시 후 다시 시도해주세요.';
  if(error?.status===409)return '문서가 처리 중이거나 요청한 PDF를 준비하지 못했습니다. 잠시 후 다시 시도해주세요.';
  return '요청을 완료하지 못했습니다. 파일과 연결을 확인한 뒤 다시 시도해주세요.';
}
// The page-level message sits above the form, so move there when it reports a problem.
function alertMessage(text){const node=notice(text,true);node.tabIndex=-1;message.replaceChildren(node);reveal(node);}
function showError(error,target=message){if(target===message)alertMessage(errorText(error));else target.replaceChildren(notice(errorText(error),true));if(error?.status===404)clearSession('세션이 만료되었습니다. 문서를 다시 준비해주세요.');}
function busy(value){preparing=value;for(const control of form.elements)control.disabled=value;document.querySelector('#prepare-submit').textContent=value?'문서 준비 중…':'문서 준비하기';document.querySelector('#prepare-status').textContent=value?'구조 읽기와 PDF 준비 중입니다. 최대 3분이 걸릴 수 있습니다.':'';
  if(session)return;
  if(value){structure.replaceChildren(skeleton());viewer.replaceChildren(skeleton([48,32]));}
  else{structure.replaceChildren();viewer.replaceChildren();}
}
function clearSession(text=DELETED){
  clearSemantic();
  cloudPanel?.dispose();cloudPanel=undefined;clearTimeout(expiryTimer);resources.clear();library.sessionChanged();session=null;selection=initialSelection();returnStep=null;reached=1;structure.replaceChildren();viewer.replaceChildren();bar.replaceChildren();bar.hidden=true;busy(false);
  setStep(1,{focus:false});
  if(text===DELETED){message.replaceChildren();toaster.push(text,'원본과 미리보기를 이 컴퓨터에서 지웠습니다.');}else message.replaceChildren(notice(text));
}
function activateSession(prepared){
  clearSemantic();
  cloudPanel?.dispose();cloudPanel=undefined;resources.clear();library.sessionChanged();session=prepared;selection=initialSelection();role=prepared.guide.document?'guide':'report';scheduleExpiry();returnStep=null;bar.hidden=false;
  const save=button('문서 보관하기',()=>library.save(save));save.id='save-document';save.setAttribute('aria-describedby','save-status');
  const saveStatus=element('div','save-status');saveStatus.id='save-status';saveStatus.setAttribute('aria-live','polite');
  bar.replaceChildren(element('strong','',session.project_name),element('span','muted',`만료 ${new Date(session.expires_at).toLocaleTimeString('ko-KR')}`),save,button('임시 문서 삭제',removeSession),saveStatus);
  message.replaceChildren(...(prepared.saved_id?[notice('보관한 문서를 열었습니다. 저장한 요구사항과 AI 검사 기록이 있으면 해당 단계에서 볼 수 있고, 다시 열기에는 새 AI 호출이 없습니다.')]:[]));
  if(prepared.saved_id){const details=element('details','stack');details.append(element('summary','','저장 당시와 현재 환경'),element('p','',environmentText(prepared)));message.append(details);}
  semanticPanel=mountSemanticPanel({ui:{element,button,field},api,keyStatus,demo,session,onEvidence:semanticEvidence,onComplete:semanticStatus,onSaveState:state=>{save.disabled=!state.allowed;if(!state.allowed)saveStatus.replaceChildren(notice(state.reason));else if(saveStatus.dataset.blocked==='true')saveStatus.replaceChildren();saveStatus.dataset.blocked=String(!state.allowed);},onProgress:()=>progressChanged(),onExpired:()=>clearSession('세션이 만료되었습니다. 문서를 다시 준비해주세요.')});semanticContainer.replaceChildren(semanticPanel.panel);
  render();bloom(structure);bloom(viewer);toaster.push(prepared.saved_id?'보관한 문서를 열었습니다':'문서를 준비했습니다',prepared.project_name);
  reached=reachableStep(progress());setStep(prepared.saved_id?reached:2);
}
function scheduleExpiry(){clearTimeout(expiryTimer);expiryTimer=setTimeout(()=>clearSession('세션이 만료되었습니다. 문서를 다시 준비해주세요.'),Math.max(0,Date.parse(session.expires_at)-Date.now()));}
async function removeSession(){
  if(!session)return;clearSemantic();cloudPanel?.dispose();cloudPanel=undefined;const active=session;const request=resources.begin('delete');
  try{await api.remove(active,request.signal);if(resources.current(request))clearSession();}
  catch(error){if(resources.current(request)){showError(error);if(session)renderStructure();}}
}
form.addEventListener('submit',async event=>{
  event.preventDefault();if(!form.reportValidity())return;
  if(session){alertMessage('새 문서를 준비하려면 먼저 현재 임시 문서를 삭제해주세요.');return;}
  const files=['guide-file','report-file'].map(id=>document.getElementById(id).files[0]);
  if(files.some(file=>!file)){alertMessage('안내문과 보고서 파일을 모두 선택해주세요.');return;}
  if(files.some(file=>file.size>10*1024*1024)){alertMessage('각 파일은 10 MiB 이하여야 합니다.');return;}
  const payload=new FormData(form);resources.clear();const request=resources.begin('prepare');busy(true);message.replaceChildren();
  try{
    const prepared=await api.prepare(payload,request.signal);if(!resources.current(request))return;
    activateSession(prepared);busy(false);
  }catch(error){if(resources.current(request))showError(error);}
  finally{if(resources.current(request))busy(false);}
});
function render(){
  resources.begin('evidence');resources.begin('pdf');resources.release('pdf');
  renderStructure();renderPDF();
}
function renderStructure(){
  cloudPanel?.dispose();cloudPanel=undefined;resources.begin('cloud-rewrite');
  resources.begin('expression');resources.begin('ollama-models');resources.begin('ollama-rewrite');
  const entry=session[role];const doc=entry.document;
  structure.replaceChildren(element('h2','','원본 구조'),roleTabs.element);roleTabs.select(role);
  const unread=omittedSummary(doc?.coverage?.omitted_locators);
  structure.append(element('p','',`${ROLES[role]} · 읽기 ${STATUS[entry.extraction_status]}${entry.extraction_status==='partial'&&unread?` (${unread}는 읽지 않음)`:''} · PDF 미리보기 ${STATUS[entry.rendering_status]}`));
  if(entry.error_code)structure.append(notice(`${preparationErrorText(entry.error_code)} 읽은 내용이 있다면 아래에 표시됩니다.`,true));
  if(!doc){structure.append(notice('읽을 수 있는 내용이 없습니다. 위에서 다른 문서를 선택하세요.'));return;}
  structure.append(element('p','',doc.source.filename));
  // One plain sentence instead of separate layout/font/page warnings that say the same thing.
  if(doc.source.detected_format!=='pdf'||entry.warnings.length)structure.append(notice(doc.source.detected_format==='pdf'?entry.warnings.map(warningText).join(' '):'미리보기 PDF는 원본과 줄바꿈·쪽 나눔·글꼴이 다를 수 있어, "10쪽 이내" 같은 쪽수 조건은 판정하지 않습니다.'));
  const ocrNotice=entry.warnings.filter(code=>code.startsWith('ocr_')).map(warningText).join(' ');
  if(ocrNotice&&doc.source.detected_format!=='pdf')structure.append(notice(ocrNotice));
  const blocks=doc.blocks;let index=blocks.findIndex(block=>block.block_id===selection[role].block);if(index<0)index=0;
  const block=blocks[index];
  if(block){
    selection=selectBlock(selection,role,block.block_id);
    const change=id=>{selection=selectBlock(selection,role,id);resources.begin('evidence');renderStructure();document.querySelector('#block-select')?.focus();};
    const previous=button('이전 조각',()=>change(blocks[index-1].block_id));previous.disabled=index===0;
    const next=button('다음 조각',()=>change(blocks[index+1].block_id));next.disabled=index===blocks.length-1;
    const toolbar=element('div','cluster');toolbar.append(previous,next);
    const count=blocks.length.toLocaleString('ko-KR');
    structure.append(field({id:'block-select',label:'읽은 조각',value:block.block_id,options:blocks.map((item,i)=>[item.block_id,`${i+1} / ${count} · ${locationLabel(item.source_locator.path)} (${KINDS[item.kind]??'내용'})`]),onChange:change}),toolbar);
    const originalPage=block.source_locator.original_page_number;
    if(originalPage)structure.append(element('p','muted',`원본 ${originalPage}쪽`));
    const label=element('label','','읽은 원문 · 문구를 선택하면 PDF에서 찾을 수 있습니다');label.htmlFor='source-text';
    const text=element('textarea','control source-text');text.id='source-text';text.readOnly=true;text.value=block.raw_text;
    structure.append(label,text);
    if(block.kind==='ocr_line')structure.append(notice(`글자 인식(오류 가능) · 이미지에서 기계가 읽은 글자입니다${block.ocr?.confidence<LOW_OCR_CONFIDENCE?' · 신뢰도 낮음':''}. 원본과 비교해 확인하세요.`,block.ocr?.confidence<LOW_OCR_CONFIDENCE));
    else if(block.kind==='figure')structure.append(notice('원문에서 그림이 있는 위치입니다. 그림 내용은 읽지 못했고, 캡션이 있으면 다음 조각에 문단으로 나옵니다.'));
    else if(!block.raw_text)structure.append(notice('이 조각은 표 칸처럼 다른 내용을 묶는 자리라 글자가 없습니다. 다음 조각에서 내용을 확인하세요.'));
    const actions=element('div','cluster');
    const selected=button('선택한 문구 PDF에서 찾기',()=>{
      try{const range=unicodeRange(text.value,text.selectionStart,text.selectionEnd);void mapQuote(block,range);}
      catch{document.querySelector('#mapping-result').replaceChildren(notice('먼저 원문에서 문구를 선택해주세요. 키보드 Shift와 방향키로도 선택할 수 있습니다.',true));}
    });
    const whole=button('이 조각 전체 PDF에서 찾기',()=>mapQuote(block,{start:0,end:[...block.raw_text].length}));
    selected.disabled=!block.raw_text||!entry.artifact_kind;whole.disabled=selected.disabled;
    actions.append(selected,whole);const result=element('div','stack');result.id='mapping-result';result.setAttribute('aria-live','polite');structure.append(actions,result);
    cloudPanel=mountCloudPanel({ui:{element,button,field},api,keyStatus,resources,session,role,doc,block,text});
    const tools=element('details','stack extra-tools');tools.append(element('summary','','추가 도구 (선택) · 한국어 표현 점검과 윤문 제안'),expressionPanel(doc,block,text),...(demo?[]:[ollamaPanel(doc,block,text),cloudPanel.panel]));
    structure.append(tools);
  }else structure.append(notice('읽은 글자가 없습니다. PDF 미리보기와 아래의 읽은 범위를 확인하세요.'));
  structure.append(coverage(doc));
}
function expressionPanel(doc,block,text){
  const panel=element('section','expression-panel stack');panel.setAttribute('aria-labelledby','expression-heading');
  const heading=element('h3','','한국어 표현 점검');heading.id='expression-heading';
  const scope=element('p','muted','일부 규칙 로컬 점검 · AI 모델 사용 없음');
  const help=element('p','expression-help','현재 블록의 선택한 문구 또는 전체를 점검합니다. 외부 전송 없이 표현 후보만 찾으며 원문은 바꾸지 않습니다. 한 번에 최대 20,000자입니다.');
  const source=element('a','expression-source','im-not-ai 로컬 규칙 출처');source.href='https://github.com/epoko77-ai/im-not-ai/tree/2f3d943d08056b612a92e12bfb72ea94dd2acd18';source.target='_blank';source.rel='noopener noreferrer';
  const actions=element('div','cluster');const output=element('div','stack expression-result');output.id='expression-result';output.setAttribute('aria-live','polite');
  const active=session;const activeRole=role;let lastRange;
  const selected=button('선택한 문구 표현 점검',()=>run(false));const whole=button('블록 전체 표현 점검',()=>run(true));
  const controls=running=>{selected.disabled=running||!block.raw_text;whole.disabled=running||!block.raw_text||[...block.raw_text].length>20000;output.setAttribute('aria-busy',String(running));};
  const check=createExpressionCheck({resources,request:(context,signal)=>api.expression(active,activeRole,{block_id:block.block_id,...context.range},signal),onState:state=>{
    controls(state.status==='running');
    if(state.status==='running'){output.replaceChildren(notice('선택 범위의 표현을 로컬에서 점검 중입니다.'));return;}
    if(state.status==='error'){
      if(state.error?.status===404){showError(state.error,output);return;}
      output.replaceChildren(notice('표현 점검을 완료하지 못했습니다. 연결과 선택 범위를 확인한 뒤 다시 시도해주세요.',true),button('표현 점검 다시 시도',()=>submit(lastRange)));return;
    }
    renderExpressionResult(output,state.result,text);
  }});
  function submit(range){lastRange=range;return check.run({block,range,source:doc.source.content_sha256});}
  function run(wholeBlock){
    try{void submit(expressionSelection(text.value,wholeBlock?0:text.selectionStart,wholeBlock?text.value.length:text.selectionEnd));}
    catch{output.replaceChildren(notice('원문에서 20,000자 이내의 문구를 선택해주세요. Shift와 방향키로도 선택할 수 있습니다.',true));}
  }
  controls(false);actions.append(selected,whole);panel.append(heading,scope,help,source,actions,output);
  if(active[activeRole].extraction_status==='partial')panel.append(notice('문서를 일부만 읽었습니다. 현재 읽은 블록만 점검하며 누락 영역은 포함하지 않습니다.'));
  return panel;
}
function ollamaPanel(doc,block,text){
  const panel=element('section','expression-panel stack');panel.setAttribute('aria-labelledby','ollama-heading');
  const heading=element('h3','','로컬 AI 윤문 제안');heading.id='ollama-heading';
  const help=element('p','expression-help','이 컴퓨터의 Ollama와 설치된 로컬 모델만 사용합니다. 원문에서 최대 4,000자를 선택해 요청하세요. 원문은 자동으로 바뀌지 않습니다. 사실·수치가 보존된다는 보장은 없으므로 직접 검토해주세요. 이 윤문 기능은 AI 의미 검사를 수행하지 않습니다.');
  const active=session;const activeRole=role;let model='';let modelBusy=false;let rewriteBusy=false;let lastContext;
  const modelStatus=element('div','stack');modelStatus.id='ollama-model-status';modelStatus.setAttribute('aria-live','polite');
  const output=element('div','stack expression-result');output.id='ollama-result';output.setAttribute('aria-live','polite');
  const modelField=field({id:'ollama-model',label:'설치된 로컬 모델',options:[['','먼저 모델을 확인해주세요']],onChange:value=>{model=value;resources.begin('ollama-rewrite');lastContext=undefined;output.replaceChildren();controls();}});
  const select=modelField.querySelector('select');
  const discover=button('Ollama 모델 확인',()=>loadModels());
  const rewrite=button('선택 문구 윤문 제안',()=>{
    try{void submit({block,range:ollamaSelection(text.value,text.selectionStart,text.selectionEnd),source:doc.source.content_sha256,model});}
    catch{output.replaceChildren(notice('원문에서 4,000자 이내의 문구를 선택해주세요. Shift와 방향키로도 선택할 수 있습니다.',true));}
  });
  function controls(){
    discover.disabled=modelBusy||rewriteBusy;discover.textContent=modelBusy?'Ollama 모델 확인 중…':'Ollama 모델 확인';
    select.disabled=modelBusy||rewriteBusy||select.options.length<2;
    rewrite.disabled=modelBusy||rewriteBusy||!model||!block.raw_text;rewrite.textContent=rewriteBusy?'로컬 AI 윤문 중…':'선택 문구 윤문 제안';
    modelStatus.setAttribute('aria-busy',String(modelBusy));output.setAttribute('aria-busy',String(rewriteBusy));
  }
  function failed(state,target,retry,label){
    if(state.error?.code==='session_not_found'){showError(state.error,target);return;}
    target.replaceChildren(notice('로컬 Ollama 요청을 완료하지 못했습니다. Ollama 실행 상태와 설치된 로컬 모델을 확인한 뒤 다시 시도해주세요. 원문은 그대로입니다.',true),button(label,retry));
  }
  const models=createOllamaRequest({resources,key:'ollama-models',request:(_,signal)=>api.ollamaModels(active,signal),validate:validateOllamaModels,onState:state=>{
    modelBusy=state.status==='running';
    if(modelBusy)modelStatus.replaceChildren(notice('설치된 로컬 Ollama 모델을 확인 중입니다.'));
    else if(state.status==='error')failed(state,modelStatus,loadModels,'모델 확인 다시 시도');
    else{
      select.replaceChildren(...[['','사용할 모델을 선택해주세요'],...state.result.map(item=>[item.name,item.name])].map(([value,label])=>{const option=element('option','',label);option.value=value;return option;}));
      modelStatus.replaceChildren(notice(state.result.length?'설치된 모델을 선택한 뒤 원문에서 문구를 선택해주세요.':'사용할 수 있는 로컬 모델이 없습니다. 설치된 모델을 준비한 뒤 다시 확인해주세요.'));
    }
    controls();
  }});
  const check=createOllamaRequest({resources,key:'ollama-rewrite',request:(context,signal)=>api.ollamaRewrite(active,activeRole,{block_id:block.block_id,...context.range,model:context.model},signal),validate:validateOllamaRewrite,onState:state=>{
    rewriteBusy=state.status==='running';controls();
    if(rewriteBusy){output.replaceChildren(notice('선택 문구를 로컬 Ollama에서 윤문 중입니다. 모델에 따라 시간이 걸릴 수 있습니다.'));return;}
    if(state.status==='error'){failed(state,output,()=>submit(lastContext),'윤문 제안 다시 시도');return;}
    const result=state.result;
    const original=element('article','expression-finding stack');original.append(element('h4','','선택한 원문'),element('blockquote','expression-quote',result.original));
    const suggestion=element('article','expression-finding stack');suggestion.append(element('h4','','AI 윤문 제안 · 검토 필요'),element('blockquote','expression-quote',result.suggestion));
    output.replaceChildren(notice(`로컬 Ollama · ${result.model} · 윤문 실행 완료. 이 윤문 기능은 AI 의미 검사를 수행하지 않습니다.`),original,suggestion,element('p','expression-help','사실·수치·의미가 달라졌는지 원문과 비교해주세요. 이 제안은 원문에 적용되지 않았습니다.'));
  }});
  function submit(context){lastContext=context;return check.run(context);}
  function loadModels(){resources.begin('ollama-rewrite');model='';lastContext=undefined;output.replaceChildren();select.replaceChildren(element('option','','먼저 모델을 확인해주세요'));return models.run();}
  controls();panel.append(heading,help,discover,modelStatus,modelField,rewrite,output);return panel;
}
function renderExpressionResult(target,result,text){
  target.replaceChildren(notice(result.findings.length?`선택 범위 ${result.end-result.start}자에서 확인할 표현 후보 ${result.findings.length}개를 찾았습니다. 문맥을 보고 판단해주세요.`:'선택 범위에서 해당 규칙의 표현 후보를 찾지 못했습니다. 자연스러움이나 정확성을 보장하지는 않습니다.'));
  for(const finding of result.findings){
    const item=element('article','expression-finding stack');
    const quote=element('blockquote','expression-quote',finding.original);
    item.append(element('h4','',finding.label),quote,element('p','',finding.explanation));
    if(finding.suggestion)item.append(element('p','muted',`검토 힌트: ${finding.suggestion}`));
    item.append(button('원문에서 선택',()=>{const range=textareaRange(text.value,finding);text.focus();text.setSelectionRange(range.start,range.end);text.scrollIntoView({block:'nearest'});}));target.append(item);
  }
  const details=element('details','expression-details');details.append(element('summary','','점검 범위와 규칙별 집계'));
  for(const metric of result.metrics)details.append(element('p','',`${metric.label}: ${metric.count}`));
  for(const warning of result.warnings)details.append(element('p','muted',warning));
  details.append(element('p','muted','규칙으로만 점검하며 AI 모델은 사용하지 않습니다.'));target.append(details);
}
function coverage(doc){
  const details=element('details','stack');details.append(element('summary','','읽은 범위 자세히'));
  const c=doc.coverage;
  details.append(element('p','',`읽은 조각 ${doc.blocks.length.toLocaleString('ko-KR')}개 · 모든 내용을 읽었다고 보장하지는 않습니다.`));
  if(c.processed_pages)details.append(element('p','',`읽은 쪽: ${c.processed_pages.join(', ')}`));
  if(c.unreadable_pages?.length)details.append(element('p','',`읽지 못한 쪽: ${c.unreadable_pages.join(', ')}`));
  const unread=omittedSummary(c.omitted_locators);
  if(unread)details.append(element('p','',`읽지 않은 내용: ${unread}. 그림 속 글자나 수식은 검사에 쓰이지 않습니다.`));
  if((doc.warnings?.length??0)+(doc.typed_errors?.length??0))details.append(element('p','','읽는 중 구조를 정확히 해석하지 못한 부분이 있었습니다. 원문과 PDF를 함께 확인해주세요.'));
  return details;
}
async function mapQuote(block,range){
  const target=document.querySelector('#mapping-result');const active=session;const activeRole=role;const request=resources.begin('evidence');target.replaceChildren(notice('실제 PDF의 문구와 대조 중입니다.'));
  try{
    const result=await api.evidence(active,activeRole,{block_id:block.block_id,...range},request.signal);if(!resources.current(request))return;
    const matches=mappingMatches(result,active[activeRole].document,block,range);
    renderMappingResult({target,result,matches,total:active[activeRole].preview_page_count,ui:{notice,button},onPage:page=>{selection=selectPage(selection,activeRole,page,active[activeRole].preview_page_count);renderPDF();document.querySelector('#pdf-heading').focus();document.querySelector('#pdf-heading').scrollIntoView({block:'start'});}});
  }catch(error){if(resources.current(request))showError(error,target);}
}
function renderPDF(){
  const entry=session[role];resources.begin('image');resources.release('image');resources.begin('pdf');resources.release('pdf');
  const heading=element('h2','',entry.artifact_kind==='original_pdf'?'원본 PDF':'변환 미리보기');heading.id='pdf-heading';heading.tabIndex=-1;viewer.replaceChildren(heading);
  if(!entry.artifact_kind||!entry.preview_page_count){viewer.append(notice('확인할 PDF를 준비하지 못했습니다. 원본 구조는 별도로 확인할 수 있습니다.'));return;}
  const total=entry.preview_page_count;const page=selection[role].page;
  viewer.append(element('p','muted',entry.artifact_kind==='original_pdf'?`${total}쪽 · 업로드한 원본 PDF`:`확인용 PDF ${total}쪽 · 원본 쪽수와 다를 수 있음`));
  const change=value=>{selection=selectPage(selection,role,Number(value),total);renderPDF();document.querySelector('#pdf-page')?.focus();};
  const previous=button('이전 쪽',()=>change(page-1));previous.disabled=page===1;
  const next=button('다음 쪽',()=>change(page+1));next.disabled=page===total;
  const toolbar=element('div','cluster');toolbar.append(previous,next,button('PDF 파일 준비',loadPDF));
  viewer.append(field({id:'pdf-page',label:'PDF 페이지',value:String(page),options:Array.from({length:total},(_,i)=>[String(i+1),`${i+1} / ${total}쪽`]),onChange:change}),toolbar);
  const download=element('div','stack');download.id='pdf-download';const frame=element('div','image-frame stack');frame.id='page-image';viewer.append(download,frame);void loadImage();
}
async function loadImage(){
  const frame=document.querySelector('#page-image');const active=session;const activeRole=role;const page=selection[role].page;const request=resources.begin('image');resources.release('image');frame.replaceChildren(notice('PDF 페이지 이미지를 불러오는 중입니다.'));
  try{
    const blob=await api.image(active,activeRole,page,request.signal);if(!resources.current(request))return;
    const image=element('img','page-image');image.alt=`${ROLES[activeRole]} ${active[activeRole].artifact_kind==='original_pdf'?'원본 PDF':'변환 미리보기'} ${page}쪽`;image.src=resources.url('image',blob);
    image.addEventListener('error',()=>{if(resources.current(request)){resources.release('image');frame.replaceChildren(notice('페이지 이미지를 표시하지 못했습니다.',true),button('이미지 다시 불러오기',loadImage));}});frame.replaceChildren(image);
  }catch(error){if(resources.current(request)){showError(error,frame);if(session)frame.append(button('이미지 다시 불러오기',loadImage));}}
}
async function loadPDF(){
  const target=document.querySelector('#pdf-download');const active=session;const activeRole=role;const request=resources.begin('pdf');target.replaceChildren(notice('PDF 파일을 준비하는 중입니다.'));
  try{
    const blob=await api.pdf(active,activeRole,request.signal);if(!resources.current(request))return;
    const link=element('a','button','PDF 파일 열기');link.href=resources.url('pdf',blob);link.target='_blank';link.rel='noopener';target.replaceChildren(link);
  }catch(error){if(resources.current(request))showError(error,target);}
}
window.addEventListener('pagehide',()=>{settings.clearInputs();library.dispose();clearSession('접근 정보가 정리되었습니다. 문서를 다시 준비해주세요.');});
window.addEventListener('pageshow',event=>{if(event.persisted)library.restore();});
setStep(1,{focus:false});
