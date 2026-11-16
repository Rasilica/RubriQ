import {credentialChoice,keyStatusText} from './ai-settings.mjs';
import {unicodeRange} from './state.mjs';

const PROVIDERS={gemini:'Gemini',openai:'OpenAI (GPT)',anthropic:'Anthropic (Claude)',billingai:'빌링AI'};
const bounded=(value,max)=>typeof value==='string'&&value.trim().length>0&&[...value].length<=max;
const validModel=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/u.test(value);
const validKey=value=>typeof value==='string'&&/^[\x21-\x7e]{1,512}$/u.test(value);
function requireValue(condition){if(!condition)throw new Error('invalid_cloud_request');}

export function cloudPreview({block,source,provider,model,text,start,end}){
  requireValue(Object.hasOwn(PROVIDERS,provider)&&validModel(model)&&/^[a-f0-9]{64}$/u.test(source)&&text===block.raw_text);
  const range=unicodeRange(text,start,end);requireValue(range.end-range.start<=4000);
  return Object.freeze({block:Object.freeze({...block}),source,provider,model,range:Object.freeze(range),original:[...text].slice(range.start,range.end).join('')});
}
export function validateCloudRewrite(value,context){
  const {block,source,provider,model,range,original}=context;
  requireValue(value?.provider===provider&&value.model===model&&value.llm_executed===true);
  requireValue(value.source_sha256===source&&value.block_id===block.block_id&&value.start===range.start&&value.end===range.end);
  requireValue(value.original===original&&bounded(value.suggestion,8000));
  requireValue(Array.isArray(value.warnings)&&value.warnings.length<=20&&value.warnings.every(item=>bounded(item,1000)));
  const usage=value.usage;
  if(usage!==undefined&&usage!==null){
    requireValue(typeof usage==='object'&&!Array.isArray(usage));
    for(const count of [usage.input_tokens,usage.output_tokens])requireValue(count===null||(Number.isSafeInteger(count)&&count>=0));
  }
  return {provider,model,original,suggestion:value.suggestion,usage:usage?{input_tokens:usage.input_tokens,output_tokens:usage.output_tokens}:null};
}
export function createCloudRequest({resources,request,onState}){
  const consumed=new WeakSet();
  return {run(context,apiKey,consent){
    requireValue(consent===true&&(context.useSavedKey===true?!apiKey:validKey(apiKey))&&!consumed.has(context));consumed.add(context);
    const operation=resources.begin('cloud-rewrite');onState({status:'running'});
    return (async()=>{
      try{
        const value=await request(context,apiKey,operation.signal);
        if(!resources.current(operation))return;
        const result=validateCloudRewrite(value,context);
        requireValue(!apiKey||!result.suggestion.includes(apiKey));
        onState({status:'complete',result});
      }catch{if(resources.current(operation))onState({status:'error'});}
      finally{apiKey='';}
    })();
  }};
}

export function mountCloudPanel({ui,api,resources,session,role,doc,block,text,keyStatus}){
  const {element,button,field}=ui;
  const notice=(message,error=false)=>{const node=element('p',`notice${error?' error':''}`,message);node.setAttribute('role',error?'alert':'status');return node;};
  const panel=element('section','expression-panel stack');panel.setAttribute('aria-labelledby','cloud-heading');
  const heading=element('h3','','클라우드 AI 윤문 제안');heading.id='cloud-heading';
  let context;let inFlightContext;let running=false;
  const output=element('div','stack expression-result');output.id='cloud-result';output.setAttribute('aria-live','polite');
  const review=element('div','stack');review.id='cloud-preview';
  const providerField=field({id:'cloud-provider',label:'외부 AI 제공자',options:[['','제공자를 선택해주세요'],...Object.entries(PROVIDERS)],onChange:()=>{invalidate(true);billingHelp.hidden=provider.value!=='billingai';}});
  const provider=providerField.querySelector('select');
  const billingHelp=element('p','expression-help','빌링AI에서 발급한 API 키와 접두어 없는 모델 ID(예: gpt-5-4, claude-sonnet-4-6, gemini-2-5-flash)를 입력하세요. 빌링AI와 선택한 모델의 실제 제공자에게 문구가 전송되며 크레딧이 차감될 수 있습니다. 직접 입력한 키는 요청 직후 비웁니다. ');billingHelp.id='cloud-billing-help';billingHelp.hidden=true;
  const billingDocs=element('a','','빌링AI 모델·요금 문서');billingDocs.href='https://billing-ai.doublezero.kr/docs/text';billingDocs.target='_blank';billingDocs.rel='noopener noreferrer';billingHelp.append(billingDocs);
  const modelField=field({id:'cloud-model',label:'모델 ID',help:'제공자의 공식 콘솔·문서에서 사용 가능한 서비스 모델 ID를 확인해 직접 입력해주세요. 모델 목록은 자동으로 조회하지 않습니다.',onChange:()=>invalidate()});
  const model=modelField.querySelector('input');model.maxLength=200;model.placeholder='서비스 모델 ID';model.autocomplete='off';model.spellcheck=false;
  const keyField=field({id:'cloud-api-key',label:'이번 요청의 API 키 · 저장된 키 대신 사용 (선택)',onChange:()=>invalidate()});
  const key=keyField.querySelector('input');key.type='password';key.autocomplete='off';key.maxLength=512;key.spellcheck=false;
  const savedStatus=element('p','muted');savedStatus.id='cloud-key-status';
  const consentLabel=element('label','cluster');const consent=element('input');consent.type='checkbox';consent.id='cloud-consent';consentLabel.htmlFor=consent.id;
  const consentText=element('span');consentLabel.append(consent,consentText);
  consent.addEventListener('change',controls);
  const preview=button('전송할 선택 문구 미리보기',()=>{
    invalidate();
    try{
      const credentials=credentialChoice(provider.value,key.value,keyStatus);
      context={...cloudPreview({block,source:doc.source.content_sha256,provider:provider.value,model:model.value.trim(),text:text.value,start:text.selectionStart,end:text.selectionEnd}),useSavedKey:credentials.useSavedKey};
      consentText.textContent=context.provider==='billingai'?'선택한 문구와 윤문 시스템 지침이 빌링AI 및 선택한 모델의 실제 제공자에게 전송되며, 크레딧이 차감될 수 있습니다. 이에 동의합니다.':'선택한 문구와 윤문 시스템 지침이 선택한 외부 제공자에게 전송되며, 비용이 발생할 수 있습니다. 이에 동의합니다.';
      review.replaceChildren(element('h4','','전송 전 확인'),element('p','',`${PROVIDERS[context.provider]} · ${context.model} · 선택 문구 ${context.range.end-context.range.start}자`),element('blockquote','expression-quote',context.original),consentLabel);controls();
    }catch{output.replaceChildren(notice('제공자·모델 ID와 사용할 키를 확인하고 원문에서 4,000자 이내의 문구를 선택해주세요. 설정에 저장된 키 또는 이번 요청에 직접 입력한 키를 사용할 수 있습니다. 모델 ID는 영문·숫자로 시작하며 영문·숫자·점·밑줄·하이픈만 200자까지, 직접 입력하는 API 키는 공백 없는 ASCII 문자로 512자까지 입력할 수 있습니다.',true));}
  });
  preview.id='cloud-preview-button';
  const send=button('확인한 문구 전송·윤문 요청',()=>{
    if(running||!context||!consent.checked)return;
    const confirmed=context;let apiKey=key.value;key.value='';context=undefined;inFlightContext=confirmed;consent.checked=false;
    try{void request.run(confirmed,apiKey,true);}
    catch{inFlightContext=undefined;output.replaceChildren(notice('API 키와 미리보기를 다시 확인해주세요. 다시 요청하면 비용이 발생할 수 있습니다.',true));controls();}
    finally{apiKey='';}
  });send.id='cloud-submit';
  const request=createCloudRequest({resources,request:(confirmed,apiKey,signal)=>api.cloudRewrite(session,role,{block_id:confirmed.block.block_id,...confirmed.range,provider:confirmed.provider,model:confirmed.model,consent:true,use_saved_key:confirmed.useSavedKey===true,source_sha256:confirmed.source},{...(confirmed.useSavedKey?{}:{apiKey}),signal}),onState:state=>{
    running=state.status==='running';if(!running)inFlightContext=undefined;controls();
    if(running){output.replaceChildren(notice('선택한 외부 AI에 윤문을 요청 중입니다. 추가 요청은 자동으로 실행되지 않습니다.'));return;}
    if(state.status==='error'){output.replaceChildren(notice('클라우드 윤문을 완료하지 못했습니다. 키·모델·연결을 확인하고 문구를 다시 미리본 뒤 동의해주세요. 이전 요청이 처리되었을 수 있어 다시 요청하면 비용이 발생할 수 있습니다.',true));return;}
    const original=element('article','expression-finding stack');original.append(element('h4','','전송한 원문'),element('blockquote','expression-quote',state.result.original));
    const suggestion=element('article','expression-finding stack');suggestion.append(element('h4','','클라우드 AI 윤문 제안 · 검토 필요'),element('blockquote','expression-quote',state.result.suggestion));
    const usage=state.result.usage;const counts=usage?[usage.input_tokens===null?'':`입력 ${usage.input_tokens}토큰`,usage.output_tokens===null?'':`출력 ${usage.output_tokens}토큰`].filter(Boolean).join(' · '):'';
    output.replaceChildren(notice(`${PROVIDERS[state.result.provider]} · ${state.result.model} · 윤문 실행 완료. 이 윤문 기능은 AI 의미 검사를 수행하지 않습니다.`),original,suggestion,element('p','expression-help','사실·수치·의미가 달라졌는지 직접 비교해주세요. 원문에는 적용되지 않았습니다.'));
    if(counts)output.append(element('p','muted',`제공자 응답 사용량: ${counts}`));
  }});
  function controls(){savedStatus.textContent=keyStatusText(provider.value,keyStatus);preview.disabled=running||!block.raw_text;send.disabled=running||!context||!consent.checked;consent.disabled=running||!context;output.setAttribute('aria-busy',String(running));}
  function invalidate(clearKey=false){resources.begin('cloud-rewrite');context=undefined;inFlightContext=undefined;running=false;consent.checked=false;if(clearKey)key.value='';review.replaceChildren();output.replaceChildren();controls();}
  const selectionChanged=()=>{
    const selectedContext=context??inFlightContext;if(!selectedContext)return;
    try{const range=unicodeRange(text.value,text.selectionStart,text.selectionEnd);if(text.value===selectedContext.block.raw_text&&range.start===selectedContext.range.start&&range.end===selectedContext.range.end)return;}catch{}
    invalidate();
  };
  text.addEventListener('select',selectionChanged);text.addEventListener('input',selectionChanged);
  const unsubscribe=keyStatus?.subscribe(()=>invalidate(true));
  controls();panel.append(heading,element('p','expression-help','외부 클라우드 서비스에 선택 문구와 시스템 지침을 전송합니다. 최대 4,000자이며 문서 전체는 전송하지 않습니다. 설정에 저장한 키를 사용할 수 있으며 직접 입력한 키는 요청 직후 비웁니다. 이 윤문 기능은 AI 의미 검사를 수행하지 않습니다.'),providerField,billingHelp,modelField,savedStatus,keyField,preview,review,send,output);
  return {panel,dispose(){unsubscribe?.();invalidate(true);for(const control of [provider,model,key,preview,send,consent])control.disabled=true;text.removeEventListener('select',selectionChanged);text.removeEventListener('input',selectionChanged);}};
}
