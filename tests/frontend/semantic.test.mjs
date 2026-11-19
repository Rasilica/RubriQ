import test from 'node:test';
import assert from 'node:assert/strict';
import {semanticPreview,editableItems,validateCitation,validateDraft,validateCheck} from '../../src/submission/static/prepare/newsemantic.mjs';
import {createAPI} from '../../src/submission/static/prepare/api.mjs';
import {diagnosticMessage,validateDiagnostic} from '../../src/submission/static/prepare/ai-diagnostic.mjs';
const hash='a'.repeat(64), reportHash='b'.repeat(64);
const document=(source,text)=>({source:{content_sha256:source},blocks:[{block_id:'b1',raw_text:text}]});
const session={session_id:'s',access_token:'token',guide:{document:document(hash,'요구 😀')},report:{document:document(reportHash,'근거 😀')}};
const item={requirement_id:'r1',title:'제목',classification:'required',condition_description:null,subconditions:[],included:true,exclusion_reason:null,application_status:'applies',application_reason:null};
const citation={block_id:'b1',char_range:{start:0,end:4},quote:'요구 😀',verification:'exact_quote'};
const draft={draft_id:'d',revision:0,guide_sha256:hash,requirements:[{...item,citations:[citation],condition:null}],items:[item],criteria_sha256:null,confirmed:false,provider:'gemini',model:'model',ai_called:true};
const preview=(patch={})=>semanticPreview({session,provider:'gemini',model:'model',stage:'requirements',...patch});
test('semantic preview contains exact Unicode blocks and rejects over limit without slicing',()=>{
 assert.deepEqual(preview().blocks.guide,[{block_id:'b1',raw_text:'요구 😀'}]);
 for(const patch of [{provider:''},{model:''},{model:'bad/model'},{stage:'check'}])assert.throws(()=>preview(patch));
 assert.equal(preview({provider:'ollama',model:'qwen3:8b'}).provider,'ollama');
 for(const [count,pass] of [[20000,true],[20001,true],[60000,true],[60001,false]]){const s={...session,guide:{document:document(hash,'😀'.repeat(count))}};if(pass)assert.equal(preview({session:s}).characters,count);else assert.throws(()=>preview({session:s}));}
 const confirmed={...draft,confirmed:true,criteria_sha256:hash};
 assert.deepEqual(preview({stage:'check',draft:confirmed}).criteria,editableItems(confirmed.items));
 assert.throws(()=>preview({session:{...session,report:{document:document(reportHash,'x'.repeat(300001))}},stage:'check',draft:confirmed}));
});
test('immutable editable projection excludes server metadata; citations bind exact Unicode ranges',()=>{
 assert.deepEqual(editableItems([{...item,edited_fields:['title']}]),[item]);assert.equal(validateCitation(citation,session.guide.document).quote,citation.quote);
 for(const patch of [{quote:'wrong'},{block_id:'bad'},{char_range:{start:0,end:5}},{verification:'unverified'}])assert.throws(()=>validateCitation({...citation,...patch},session.guide.document));
});
test('draft and check responses bind current source, criteria and AI execution',()=>{
 const context=preview();assert.equal(validateDraft(draft,context,session).draft_id,'d');
 for(const patch of [{guide_sha256:reportHash},{ai_called:false},{provider:'openai'}])assert.throws(()=>validateDraft({...draft,...patch},context,session));
 const confirmed={...draft,confirmed:true,criteria_sha256:hash};const check=preview({stage:'check',draft:confirmed});
 const value={provider:'gemini',model:'model',ai_called:true,result:{criteria_sha256:hash,report_source_sha256:reportHash,items:[{requirement_id:'r1',criterion:item,applicability:'applicable',judgment:'evidence_found',reason:'확인',evidence:[{citation:{...citation,quote:'근거 😀'}}],subconditions:[]}]}};
 assert.equal(validateCheck(value,check,session).items[0].judgment,'evidence_found');
 for(const patch of [{criteria_sha256:reportHash},{report_source_sha256:hash},{fake:true}])assert.throws(()=>validateCheck({...value,result:{...value.result,...patch}},check,session));
});
test('semantic API uses local/session/key headers and criteria confirmation never sends an API key',async()=>{
 const calls=[];const api=createAPI(async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>({success:true,data:{}})};});
 const body={provider:'gemini',model:'model',consent:true,guide_sha256:hash};
 await api.aiRequirements(session,body,{apiKey:'secret'});await api.aiCriteria(session,{draft_id:'d',expected_revision:0,items:[item]});await api.aiCheck(session,body,{apiKey:'secret'});
 assert.deepEqual(calls.map(c=>c.path),['/api/document-pairs/s/ai/requirements','/api/document-pairs/s/ai/criteria','/api/document-pairs/s/ai/check']);
 for(const c of calls){assert.equal(c.options.headers['X-Local-Client'],'prepare');assert.equal(c.options.headers['X-Session-Token'],'token');assert.equal(c.options.body.includes('secret'),false);}
 assert.equal(calls[0].options.headers['X-AI-API-Key'],'secret');assert.equal(calls[1].options.headers['X-AI-API-Key'],undefined);
});

import {mountSemanticPanel} from '../../src/submission/static/prepare/newsemantic.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness(api={},active=session,keyStatus){
 const nodes=new Map(),events=[];
 function element(tag,className='',text=''){
  const listeners=new Map();const node={tag,className,textContent:text,value:'',checked:false,disabled:false,children:[],attributes:{},
   set id(value){this.nodeId=value;nodes.set(value,this);},get id(){return this.nodeId;},
   append(...children){this.children.push(...children);},replaceChildren(...children){this.children=[...children];},setAttribute(name,value){this.attributes[name]=value;},
   querySelector(tag){return this.children.find(child=>child.tag===tag);},querySelectorAll(tags){return this.children.flatMap(child=>[...(tags.split(',').includes(child.tag)?[child]:[]),...child.querySelectorAll(tags)]);},
   addEventListener(name,fn){listeners.set(name,[...(listeners.get(name)??[]),fn]);},emit(name){for(const fn of listeners.get(name)??[])fn();},click(){if(!this.disabled)this.emit('click');}
  };return node;
 }
 const button=(label,action)=>{const n=element('button','',label);n.addEventListener('click',action);return n;};
 const field=({id,label,value='',options,onChange})=>{const n=element('div');const c=element(options?'select':'input');c.options=options;c.id=id;c.value=value;c.addEventListener(options?'change':'input',()=>onChange(c.value));n.append(element('label','',label),c);return n;};
 const mounted=mountSemanticPanel({ui:{element,button,field},api,keyStatus,session:active,onEvidence:value=>events.push(value),onComplete:value=>events.push(value),onExpired:()=>events.push('expired')});
 const get=id=>nodes.get(id),click=id=>get(id).click();const change=(id,value)=>{const n=get(id);n.value=value;n.emit(n.tag==='select'?'change':'input');};
 const fill=(provider='gemini')=>{change('semantic-provider',provider);change('semantic-model',provider==='ollama'?'qwen3:8b':'model');if(provider!=='ollama')change('semantic-api-key','secret-key');};
 const consent=()=>{get('semantic-consent').checked=true;get('semantic-consent').emit('change');};
 const contents=n=>[n.textContent,...n.children.map(contents)].join(' ');
 return {ui:{element,button,field},nodes,mounted,events,get,click,change,fill,consent,contents};
}
const liveResult=(criteria=[item])=>({provider:'gemini',model:'model',ai_called:true,result:{criteria_sha256:hash,report_source_sha256:reportHash,items:criteria.map(c=>({requirement_id:c.requirement_id,criterion:c,applicability:'applicable',judgment:'evidence_found',reason:'확인',evidence:[{citation:{...citation,quote:'근거 😀'},relation:'AI 해석'}],subconditions:[]}))}});
test('two-stage panel requires fresh preview and consent; confirmation has no AI call; editing disables check',async()=>{
 let calls=0,checkCalls=0,saved;
 const h=harness({aiRequirements:async(_s,b,o)=>{calls++;assert.equal(b.consent,true);assert.equal(o.apiKey,'secret-key');return structuredClone(draft);},aiCriteria:async(_s,b)=>{saved=b;return {...draft,items:b.items,revision:1,confirmed:true,criteria_sha256:hash};},aiCheck:async(_s,b,o)=>{checkCalls++;assert.equal(o.apiKey,'secret-key');assert.equal(b.draft_id,'d');return liveResult(saved.items);}});
 h.click('semantic-requirements-preview');assert.match(h.contents(h.get('semantic-status')),/제공자·모델/);assert.equal(calls,0);
 h.fill();h.click('semantic-requirements-preview');assert.match(h.contents(h.get('semantic-preview')),/요구 😀/);h.click('semantic-submit');assert.equal(calls,0);h.consent();h.click('semantic-submit');assert.equal(h.get('semantic-api-key').value,'');await tick();assert.equal(calls,1);assert.equal(h.get('semantic-check-preview').disabled,true);
 h.change('semantic-item-0-title','검토한 제목');h.click('semantic-confirm');await tick();assert.equal(saved.items[0].title,'검토한 제목');assert.equal(calls,1);assert.equal(h.get('semantic-check-preview').disabled,false);
 h.change('semantic-api-key','secret-key');h.click('semantic-check-preview');assert.match(h.contents(h.get('semantic-preview')),/검토한 제목/);assert.match(h.contents(h.get('semantic-preview')),/근거 😀/);assert.equal(checkCalls,0);h.consent();h.click('semantic-submit');await tick();assert.equal(checkCalls,1);assert.match(h.contents(h.get('semantic-results')),/충족 근거 발견\(AI\)/);assert.match(h.contents(h.get('semantic-results')),/근거 😀/);assert.equal(h.events.at(-1),true);
 const evidence=h.get('semantic-results').querySelectorAll('button')[0];evidence.click();assert.deepEqual(h.events.at(-1),{role:'report',block_id:'b1',start:0,end:4});
 h.change('semantic-item-0-title','다시 수정');assert.equal(h.get('semantic-check-preview').disabled,true);assert.equal(h.get('semantic-results').children.length,0);assert.equal(h.get('semantic-preview').children.length,0);assert.equal(h.events.at(-1),false);
});
test('paid errors consume consent; stale responses and disposal cannot resurrect draft or expose keys',async()=>{
 let calls=0,resolve,signal;const h=harness({aiRequirements:(_s,_b,o)=>{calls++;signal=o.signal;return new Promise(yes=>{resolve=yes;});}});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');h.change('semantic-model','changed');assert.equal(signal.aborted,true);resolve(draft);await tick();assert.equal(h.get('semantic-criteria').children.length,0);
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');h.mounted.dispose();assert.equal(signal.aborted,true);resolve(draft);await tick();assert.equal(h.get('semantic-criteria').children.length,0);assert.equal(h.get('semantic-api-key').value,'');assert.equal(h.get('semantic-submit').disabled,true);assert.equal(calls,2);
 const failure=harness({aiRequirements:async()=>{throw new Error('secret-key');}});failure.fill();failure.click('semantic-requirements-preview');failure.consent();failure.click('semantic-submit');await tick();assert.match(failure.contents(failure.get('semantic-status')),/재요청에는 비용/);assert.equal(failure.contents(failure.mounted.panel).includes('secret-key'),false);assert.equal(failure.get('semantic-submit').disabled,true);
 const expired=harness({aiRequirements:async()=>{throw {status:404};}});expired.fill();expired.click('semantic-requirements-preview');expired.consent();expired.click('semantic-submit');await tick();assert.equal(expired.events.at(-1),'expired');
});
test('Ollama uses explicit local consent without key and discovers installed models only on click',async()=>{
 let discovery=0,called=0;const h=harness({ollamaModels:async()=>{discovery++;return {provider:'ollama',models:[{name:'qwen3:8b'}]};},aiRequirements:async(_s,b,o)=>{called++;assert.equal(o.apiKey,undefined);return {...draft,provider:'ollama',model:b.model};}});
 h.fill('ollama');assert.equal(discovery,0);h.click('semantic-models-button');await tick();assert.match(h.contents(h.get('semantic-models')),/qwen3:8b/);h.click('semantic-requirements-preview');assert.match(h.contents(h.get('semantic-preview')),/이 컴퓨터의 Ollama/);h.click('semantic-submit');assert.equal(called,0);h.consent();h.click('semantic-submit');await tick();assert.equal(called,1);assert.equal(h.get('semantic-confirm').disabled,false);
});
test('editor preserves IDs, supports conditional reasons, inclusion and subconditions and literal quotes',async()=>{
 const conditional={...item,classification:'conditional',condition_description:'조건',application_status:'undetermined',subconditions:[{subcondition_id:'s1',description:'세부 조건'}]};
 const richer={...draft,items:[conditional],requirements:[{...draft.requirements[0],subconditions:[{subcondition_id:'s1',description:'세부 조건',citations:[citation]}],condition:{description:'조건',citations:[citation]}}]};let saved;
 const h=harness({aiRequirements:async()=>richer,aiCriteria:async(_s,b)=>{saved=b;return {...richer,items:b.items,confirmed:true,criteria_sha256:hash,revision:1};}});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();
 h.change('semantic-item-0-condition_description','새 조건');h.change('semantic-item-0-application_status','applies');h.change('semantic-item-0-application_reason','적용 이유');h.change('semantic-item-0-sub-0','새 세부');h.get('semantic-item-0-included').checked=false;h.get('semantic-item-0-included').emit('change');h.change('semantic-item-0-exclusion_reason','제외 이유');h.click('semantic-confirm');await tick();
 assert.deepEqual(saved.items[0],{...conditional,condition_description:'새 조건',application_status:'applies',application_reason:'적용 이유',subconditions:[{subcondition_id:'s1',description:'새 세부'}],included:false,exclusion_reason:'제외 이유'});
 h.get('semantic-criteria').querySelectorAll('button')[0].click();assert.deepEqual(h.events.at(-1),{role:'guide',block_id:'b1',start:0,end:4});
 h.change('semantic-item-0-classification','required');h.click('semantic-confirm');await tick();assert.equal(saved.items[0].condition_description,null);assert.equal(saved.items[0].application_reason,null);
});
test('partial extraction is disclosed and all block count boundaries enforced',()=>{
 const s={...session,guide:{extraction_status:'partial',document:{...session.guide.document,warnings:[{code:'missing',source_locator:{path:'part'}}],typed_errors:[{code:'unread'}]}}};
 const h=harness({},s);h.fill();h.click('semantic-requirements-preview');assert.match(h.contents(h.get('semantic-preview')),/일부만 읽은/);assert.match(h.contents(h.get('semantic-preview')),/확인이 필요한 부분이 있었습니다/);assert.doesNotMatch(h.contents(h.get('semantic-preview')),/missing · part/);
 const blocks=Array.from({length:2001},(_,i)=>({block_id:String(i),raw_text:'x'}));assert.throws(()=>preview({session:{...session,guide:{document:{...session.guide.document,blocks}}}}));
});
import {renderSemanticResults,renderCriteria} from '../../src/submission/static/prepare/semantic-view.mjs';
test('result view renders every judgment, excluded item and partial/subcondition scope without invented scores',()=>{
 const h=harness(),target=h.ui.element('div'),evidence={citation:{...citation,quote:'근거 😀'}};
 const base={requirement_id:'r1',criterion:item,applicability:'applicable',reason:null,evidence:[],subconditions:[]};
 renderSemanticResults({ui:h.ui,target,result:{guide_extraction_status:'partial',items:[...['evidence_found','partially_satisfied','evidence_missing','deferred',null].map(judgment=>({...base,judgment})),{...base,applicability:'not_applicable',judgment:null},{...base,judgment:'deferred',subconditions:[{subcondition_id:'s1',judgment:'deferred',reason:'세부 이유',evidence:[evidence]},{subcondition_id:'s2',judgment:null,reason:'보류',evidence:[]}]}]},onEvidence:value=>h.events.push(value)});
 const text=h.contents(target);for(const label of ['충족 근거 발견(AI)','일부 충족(AI)','근거 미발견','판정 보류','검사 제외','일부만 읽은','세부 이유'])assert.ok(text.includes(label));target.querySelectorAll('button')[0].click();assert.equal(h.events.at(-1).role,'report');
 renderCriteria({ui:h.ui,target,draft:{items:[],requirements:[],confirmed:false},onEvidence:()=>{},onEdit:()=>{}});assert.match(h.contents(target),/추출된 요구사항이 없습니다/);
});
test('screens never show internal requirement, condition or block identifiers',()=>{
 const h=harness(),target=h.ui.element('div');
 const sub={subcondition_id:'page_limit_internal',description:'10쪽 이내',citations:[citation]};
 const criterion={...item,requirement_id:'proposal_format_internal',subconditions:[{subcondition_id:sub.subcondition_id,description:sub.description}]};
 const evidence={citation:{...citation,block_id:'report-6b9a:word/document.xml::/w:p[1]',quote:'근거 😀'}};
 renderSemanticResults({ui:h.ui,target,result:{items:[{requirement_id:criterion.requirement_id,criterion,applicability:'applicable',judgment:'deferred',reason:'이유',evidence:[evidence],subconditions:[{subcondition_id:sub.subcondition_id,judgment:'deferred',reason:'세부 이유',evidence:[evidence]}]}]},onEvidence:()=>{}});
 renderCriteria({ui:h.ui,target:h.ui.element('div'),draft:{items:[criterion],requirements:[{...criterion,citations:[citation],subconditions:[sub],condition:null}],confirmed:false},onEvidence:()=>{},onEdit:()=>{}});
 const text=h.contents(target);
 for(const internal of ['proposal_format_internal','page_limit_internal','report-6b9a','word/document.xml','문자 0'])assert.ok(!text.includes(internal),internal);
 assert.ok(text.includes('세부 조건 1 · 10쪽 이내'));
});
test('result counts split the judgments for the summary tiles',async()=>{
 const {resultCounts}=await import('../../src/submission/static/prepare/semantic-view.mjs');
 const row=(judgment,applicability='applicable')=>({judgment,applicability});
 assert.deepEqual(resultCounts([row('evidence_found'),row('partially_satisfied'),row('evidence_missing'),row('deferred'),row(null,'not_applicable')]),{attention:3,found:1,missing:1,deferred:2,total:4});
});
test('the panel shows only the parts of the current step and reports progress',async()=>{
 const h=harness({aiRequirements:async()=>structuredClone(draft),aiCriteria:async(_s,b)=>({...draft,items:b.items,revision:1,confirmed:true,criteria_sha256:hash})});
 const visible=step=>{h.mounted.show(step);return ['semantic-setup','semantic-extract','semantic-run','semantic-editor-group','semantic-check-group','semantic-results-group'].filter(id=>!h.get(id).hidden);};
 assert.deepEqual(visible(3),['semantic-setup','semantic-extract','semantic-run']);
 assert.deepEqual(visible(4),['semantic-editor-group']);
 assert.deepEqual(visible(5),['semantic-setup','semantic-run','semantic-check-group']);
 assert.deepEqual(visible(6),['semantic-results-group']);
 assert.deepEqual(h.mounted.progress(),{draft:false,confirmed:false,checked:false});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();
 assert.deepEqual(h.mounted.progress(),{draft:true,confirmed:false,checked:false});
 h.click('semantic-confirm');await tick();
 assert.deepEqual(h.mounted.progress(),{draft:true,confirmed:true,checked:false});
});
test('Ollama discovery empty and failed outcomes remain retryable; changed provider invalidates preview',async()=>{
 let attempt=0;const h=harness({ollamaModels:async()=>{if(attempt++===0)throw new Error('private');return {provider:'ollama',models:[]};}});h.fill('ollama');h.click('semantic-models-button');await tick();assert.match(h.contents(h.get('semantic-status')),/요청을 완료하지/);h.click('semantic-models-button');await tick();assert.match(h.contents(h.get('semantic-models')),/설치된 모델이 없습니다/);
 h.click('semantic-requirements-preview');h.consent();h.change('semantic-provider','gemini');assert.equal(h.get('semantic-submit').disabled,true);assert.equal(h.get('semantic-preview').children.length,0);
});
test('preview includes criteria and original requirement text in server-equivalent budget',()=>{
 const confirmed={...draft,confirmed:true,criteria_sha256:hash};const totalText=300000-4-4;
 const active={...session,report:{document:document(reportHash,'x'.repeat(totalText))}};
 assert.equal(preview({session:active,stage:'check',draft:confirmed}).characters,299996);
 assert.throws(()=>preview({session:{...active,report:{document:document(reportHash,'x'.repeat(totalText+1))}},stage:'check',draft:confirmed}));
});

test('BillingAI extract-confirm-check uses separate consent, bare model and keys only for AI requests',async()=>{
 const calls=[];const billingDraft={...draft,provider:'billingai',model:'claude-sonnet-4-6'};
 const h=harness({aiRequirements:async(_s,b,o)=>{calls.push({stage:'requirements',b,o});return billingDraft;},aiCriteria:async(_s,b,...options)=>{calls.push({stage:'confirm',b,options});return {...billingDraft,items:b.items,revision:1,confirmed:true,criteria_sha256:hash};},aiCheck:async(_s,b,o)=>{calls.push({stage:'check',b,o});return {...liveResult(),provider:'billingai',model:b.model};}});
 assert.ok(h.get('semantic-provider').options.some(([value])=>value==='billingai'));
 h.change('semantic-provider','billingai');assert.equal(h.get('semantic-model').value,'');assert.equal(h.get('semantic-billing-help').hidden,false);assert.equal(calls.length,0);
 h.change('semantic-model','claude-sonnet-4-6');h.change('semantic-api-key','billing-key');h.click('semantic-requirements-preview');h.click('semantic-submit');assert.equal(calls.length,0);h.consent();h.click('semantic-submit');assert.equal(h.get('semantic-api-key').value,'');await tick();
 assert.equal(h.get('semantic-check-preview').disabled,true);h.click('semantic-confirm');await tick();assert.equal(calls[1].options.length,1);assert.ok(calls[1].options[0] instanceof AbortSignal);assert.equal(calls[1].options[0].apiKey,undefined);assert.equal(h.get('semantic-check-preview').disabled,false);
 h.change('semantic-api-key','billing-key');h.click('semantic-check-preview');h.click('semantic-submit');assert.equal(calls.length,2);h.consent();h.click('semantic-submit');await tick();
 assert.deepEqual(calls.map(c=>c.stage),['requirements','confirm','check']);for(const call of [calls[0],calls[2]]){assert.equal(call.b.provider,'billingai');assert.equal(call.b.model,'claude-sonnet-4-6');assert.equal(call.b.consent,true);assert.equal(call.o.apiKey,'billing-key');assert.equal(JSON.stringify(call.b).includes('billing-key'),false);}
 assert.equal(h.events.at(-1),true);assert.equal(h.get('semantic-api-key').value,'');assert.equal(h.get('semantic-submit').disabled,true);
 h.change('semantic-api-key','billing-key');h.click('semantic-check-preview');h.consent();h.change('semantic-provider','gemini');assert.equal(h.get('semantic-api-key').value,'');assert.equal(h.get('semantic-consent').checked,false);assert.equal(h.get('semantic-submit').disabled,true);assert.equal(h.get('semantic-billing-help').hidden,true);
});

test('BillingAI semantic invalid models and keys cannot call AI; key failure clears credentials and consent',async()=>{
 let calls=0;const h=harness({aiRequirements:async()=>{calls++;throw new Error('billing-key');}});
 h.change('semantic-provider','billingai');h.change('semantic-model','anthropic/claude-sonnet-4-6');h.change('semantic-api-key','billing-key');h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');assert.equal(calls,0);
 h.change('semantic-model','gemini-2-5-flash');h.change('semantic-api-key','bad key');h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');assert.equal(calls,0);
 h.change('semantic-api-key','billing-key');h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();assert.equal(calls,1);assert.equal(h.get('semantic-api-key').value,'');assert.equal(h.get('semantic-consent').checked,false);assert.equal(h.get('semantic-submit').disabled,true);assert.equal(h.contents(h.mounted.panel).includes('billing-key'),false);h.click('semantic-submit');assert.equal(calls,1);
});

import {createKeyStatus} from '../../src/submission/static/prepare/ai-settings.mjs';
test('saved semantic key supports both stages without losing confirmed criteria on settings updates',async()=>{
 const status=createKeyStatus();const settings={available:true,backend:'keychain',providers:['gemini','openai','anthropic','billingai'].map(provider=>({provider,configured:true}))};status.update(settings);
 const calls=[];const h=harness({aiRequirements:async(_s,b,o)=>{calls.push({b,o});return draft;},aiCriteria:async(_s,b)=>({...draft,items:b.items,revision:1,confirmed:true,criteria_sha256:hash}),aiCheck:async(_s,b,o)=>{calls.push({b,o});return liveResult();}},session,status);
 h.change('semantic-provider','gemini');h.change('semantic-model','model');h.click('semantic-requirements-preview');h.click('semantic-submit');assert.equal(calls.length,0);h.consent();h.click('semantic-submit');await tick();h.click('semantic-confirm');await tick();
 h.click('semantic-check-preview');h.consent();status.update(settings);assert.equal(h.get('semantic-consent').checked,false);assert.equal(h.get('semantic-check-preview').disabled,false);assert.ok(h.get('semantic-criteria').children.length);
 h.click('semantic-check-preview');h.consent();h.click('semantic-submit');await tick();assert.equal(calls.length,2);for(const c of calls){assert.equal(c.b.use_saved_key,true);assert.equal(c.o.apiKey,undefined);}assert.equal(h.events.at(-1),true);
});

test('saved confirmed criteria and check reopen read-only without calling AI and navigate both sources',()=>{
 const confirmed={...draft,confirmed:true,criteria_sha256:hash};let calls=0;
 const h=harness({aiRequirements:()=>{calls++;},aiCheck:()=>{calls++;},aiCriteria:()=>{calls++;}},{...session,semantic_archive:{draft:confirmed,check:liveResult()}});
 const archived=h.get('semantic-archive');assert.ok(archived.children.length);assert.equal(calls,0);
 assert.equal(h.events.at(-1),true);assert.equal(h.get('semantic-confirm').disabled,true);assert.equal(h.get('semantic-check-preview').disabled,true);
 assert.equal(h.get('saved-semantic-item-0-title').disabled,true);
 const buttons=archived.querySelectorAll('button');buttons[0].click();assert.deepEqual(h.events.at(-1),{role:'report',block_id:'b1',start:0,end:4},'saved results are shown before the folded criteria');buttons.at(-1).click();assert.deepEqual(h.events.at(-1),{role:'guide',block_id:'b1',start:0,end:4});
 assert.equal(h.get('semantic-consent').checked,false);assert.equal(h.get('semantic-submit').disabled,true);
});
test('document-only and criteria-only archives never report an AI check',()=>{
 const plain=harness();assert.equal(plain.get('semantic-archive').children.length,0);
 const h=harness({},{...session,semantic_archive:{draft:{...draft,confirmed:true,criteria_sha256:hash},check:null}});
 assert.ok(h.get('saved-semantic-item-0-title'));assert.notEqual(h.events.at(-1),true);assert.equal(h.mounted.saveState().allowed,true);
});
test('archive validation rejects stale criteria, document hashes, false AI flags and altered source citations',()=>{
 const confirmed={...draft,confirmed:true,criteria_sha256:hash};const archive={draft:confirmed,check:liveResult()};
 const patches=[{draft:{...confirmed,confirmed:false}},{draft:{...confirmed,guide_sha256:reportHash}},{check:{...liveResult(),ai_called:false}},{check:{...liveResult(),result:{...liveResult().result,criteria_sha256:reportHash}}},{check:{...liveResult(),result:{...liveResult().result,report_source_sha256:hash}}},{check:liveResult([{...item,title:'stale criterion'}])},{draft:{...confirmed,requirements:[{...draft.requirements[0],citations:[{...citation,quote:'altered'}]}]}}];
 for(const patch of patches)assert.throws(()=>harness({},{...session,semantic_archive:{...archive,...patch}}));
});
test('unsent criteria edits and running AI block save; unchanged confirmation preserves a valid result',async()=>{
 const h=harness({aiRequirements:async()=>draft,aiCriteria:async(_s,b)=>({...draft,items:b.items,revision:1,confirmed:true,criteria_sha256:hash}),aiCheck:async()=>liveResult()});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');assert.equal(h.mounted.saveState().allowed,false);await tick();
 h.change('semantic-item-0-title','unsent');assert.equal(h.mounted.saveState().allowed,false);h.click('semantic-confirm');await tick();assert.equal(h.mounted.saveState().allowed,true);
 h.change('semantic-item-0-title',item.title);h.click('semantic-confirm');await tick();h.change('semantic-api-key','secret-key');h.click('semantic-check-preview');h.consent();h.click('semantic-submit');await tick();assert.equal(h.events.at(-1),true);
 const resultText=h.contents(h.get('semantic-results'));h.click('semantic-confirm');await tick();assert.equal(h.contents(h.get('semantic-results')),resultText);assert.equal(h.events.at(-1),true);assert.equal(h.mounted.saveState().allowed,true);
});
test('fresh extraction replaces historical results only after a valid response',async()=>{
 const h=harness({aiRequirements:async()=>draft},{...session,semantic_archive:{draft:{...draft,confirmed:true,criteria_sha256:hash},check:liveResult()}});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');assert.ok(h.get('semantic-archive').children.length);await tick();
 assert.equal(h.get('semantic-archive').children.length,0);assert.equal(h.events.at(-1),false);assert.ok(h.get('semantic-item-0-title'));
});
test('failed re-confirmation cannot leave an old check presented as current',async()=>{
 let confirmations=0;
 const h=harness({aiRequirements:async()=>draft,aiCriteria:async()=>{if(confirmations++)throw new Error('connection lost');return {...draft,revision:1,confirmed:true,criteria_sha256:hash};},aiCheck:async()=>liveResult()});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();h.click('semantic-confirm');await tick();h.change('semantic-api-key','secret-key');h.click('semantic-check-preview');h.consent();h.click('semantic-submit');await tick();assert.equal(h.events.at(-1),true);
 h.change('semantic-item-0-title','edited after check');h.click('semantic-confirm');await tick();assert.equal(h.get('semantic-results').children.length,0);assert.equal(h.events.at(-1),false);assert.equal(h.mounted.saveState().allowed,false);
});


for(const edited of [false,true])test(`committed confirmation with lost response blocks save until identical free retry adopts current revision (${edited?'edited':'unedited'} criteria)`,async()=>{
 const requests=[];let serverDraft=structuredClone(draft),loseResponse=true,paidCalls=0;
 const api=createAPI(async(path,options)=>{
  const body=JSON.parse(options.body);
  if(path.endsWith('/requirements')){paidCalls++;return {ok:true,json:async()=>({success:true,data:structuredClone(draft)})};}
  assert.ok(path.endsWith('/criteria'));assert.equal(options.headers['X-AI-API-Key'],undefined);requests.push(body);
  if(!serverDraft.confirmed||JSON.stringify(body.items)!==JSON.stringify(serverDraft.items)){
   assert.equal(body.expected_revision,serverDraft.revision);
   serverDraft={...serverDraft,items:body.items,revision:serverDraft.revision+1,confirmed:true,criteria_sha256:hash};
  }
  if(loseResponse){loseResponse=false;throw new TypeError('connection lost after commit');}
  return {ok:true,json:async()=>({success:true,data:structuredClone(serverDraft)})};
 });
 const h=harness(api);h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();
 if(edited)h.change('semantic-item-0-title','reviewed before confirming');
 h.click('semantic-confirm');await tick();
 assert.equal(serverDraft.revision,1);assert.equal(h.mounted.saveState().allowed,false);assert.equal(h.get('semantic-check-preview').disabled,true);assert.equal(h.get('semantic-confirm').disabled,false);
 assert.match(h.contents(h.get('semantic-status')),/무료/);assert.doesNotMatch(h.contents(h.get('semantic-status')),/재요청에는 비용/);
 h.click('semantic-confirm');await tick();
 assert.deepEqual(requests.map(r=>r.expected_revision),[0,0]);assert.deepEqual(requests[1].items,requests[0].items);assert.equal(serverDraft.revision,1);assert.equal(paidCalls,1);
 assert.equal(h.mounted.saveState().allowed,true);assert.equal(h.get('semantic-check-preview').disabled,false);assert.equal(h.get('semantic-confirm').disabled,true);
 h.click('semantic-confirm');await tick();assert.equal(requests.length,2);
 h.change('semantic-item-0-title','new revision');h.click('semantic-confirm');await tick();assert.equal(requests[2].expected_revision,1);assert.equal(h.mounted.saveState().allowed,true);
});

test('key settings update leaves cost-free confirmation running and accepts its response',async()=>{
 const status=createKeyStatus();let finish,signal;
 const h=harness({aiRequirements:async()=>draft,aiCriteria:(_s,b,s)=>{signal=s;return new Promise(resolve=>{finish=()=>resolve({...draft,items:b.items,revision:1,confirmed:true,criteria_sha256:hash});});}},session,status);
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();h.click('semantic-confirm');
 status.update({available:true,backend:'keychain',providers:['gemini','openai','anthropic','billingai'].map(provider=>({provider,configured:true}))});
 assert.equal(signal.aborted,false);assert.equal(h.get('semantic-confirm').disabled,true);assert.equal(h.mounted.saveState().allowed,false);
 finish();await tick();assert.equal(h.mounted.saveState().allowed,true);assert.equal(h.get('semantic-check-preview').disabled,false);
});

test('confirmation conflict keeps local edits unsaved and distinguishes different server criteria',async()=>{
 const h=harness({aiRequirements:async()=>draft,aiCriteria:async()=>{throw {status:409};}});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();h.change('semantic-item-0-title','local changes');h.click('semantic-confirm');await tick();
 assert.equal(h.mounted.saveState().allowed,false);assert.equal(h.get('semantic-item-0-title').value,'local changes');assert.equal(h.get('semantic-confirm').disabled,false);
 assert.match(h.contents(h.get('semantic-status')),/서버.*다른/);assert.doesNotMatch(h.contents(h.get('semantic-status')),/재요청에는 비용/);
});

async function extract(h){h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();}

test('current criteria GET carries session and local headers without an API key or request body',async()=>{
 let observed;const controller=new AbortController();const api=createAPI(async(path,options)=>{observed={path,options};return {ok:true,json:async()=>({success:true,data:draft})};});
 assert.equal(await api.aiCurrentCriteria(session,'draft /?',controller.signal),draft);
 assert.equal(observed.path,'/api/document-pairs/s/ai/criteria?draft_id=draft%20%2F%3F');
 assert.equal(observed.options.method,'GET');assert.equal(observed.options.body,undefined);assert.equal(observed.options.headers['X-Session-Token'],'token');assert.equal(observed.options.headers['X-Local-Client'],'prepare');assert.equal(observed.options.headers['X-AI-API-Key'],undefined);assert.equal(observed.options.signal,controller.signal);assert.equal(observed.options.cache,'no-store');
});

test('version limit explains actual changed confirmations and leaves extraction an explicit paid choice',async()=>{
 let aiCalls=0,syncCalls=0;const h=harness({aiRequirements:async()=>{aiCalls++;return draft;},aiCurrentCriteria:async()=>{syncCalls++;},aiCriteria:async()=>{throw {status:409,code:'version_limit'};}});
 await extract(h);h.change('semantic-item-0-title','keep this edit');h.click('semantic-confirm');await tick();
 const text=h.contents(h.get('semantic-status'));assert.match(text,/20/);assert.match(text,/새.*추출/);assert.match(text,/비용/);assert.doesNotMatch(text,/다른 확정 상태와 충돌/);
 assert.equal(aiCalls,1);assert.equal(syncCalls,0);assert.equal(h.get('semantic-item-0-title').value,'keep this edit');assert.equal(h.mounted.saveState().allowed,false);assert.equal(h.get('semantic-requirements-preview').disabled,false);assert.equal(h.get('semantic-submit').disabled,true);
});

for(const code of ['application_undetermined','application_reason_required','invalid_condition','exclusion_reason_required','empty_criteria','immutable_identity','invalid_request'])for(const edited of [false,true])test(`known noncommitting ${code} restores only the previous save state (${edited?'edited':'unedited'})`,async()=>{
 let attempt=0;const h=harness({aiRequirements:async()=>draft,aiCriteria:async(_s,body)=>{if(attempt++===0)throw {status:422,code};return {...draft,items:body.items,revision:1,confirmed:true,criteria_sha256:hash};}});
 await extract(h);if(edited)h.change('semantic-item-0-title','local change');h.click('semantic-confirm');await tick();
 assert.equal(h.mounted.saveState().allowed,!edited);assert.equal(h.get('semantic-check-preview').disabled,true);assert.match(h.contents(h.get('semantic-status')),/확정되지 않았습니다/);assert.equal(h.get('semantic-item-0-title').value,edited?'local change':item.title);if(edited)assert.doesNotMatch(h.contents(h.get('semantic-status')),/문서만 보관할 수 있습니다/);else assert.match(h.contents(h.get('semantic-status')),/문서만 보관할 수 있습니다/);
 h.click('semantic-confirm');await tick();assert.equal(h.mounted.saveState().allowed,true);assert.equal(h.get('semantic-check-preview').disabled,false);
});

for(const error of [{status:503},{status:422,code:'unknown_error'},new TypeError('network')])test(`uncertain first confirmation failure remains blocked (${error.code??error.status??'network'})`,async()=>{
 const h=harness({aiRequirements:async()=>draft,aiCriteria:async()=>{throw error;}});await extract(h);h.click('semantic-confirm');await tick();assert.equal(h.mounted.saveState().allowed,false);assert.equal(h.get('semantic-check-preview').disabled,true);
});

test('a later known validation error does not clear uncertainty from a lost confirmation',async()=>{
 let attempt=0;const h=harness({aiRequirements:async()=>draft,aiCriteria:async()=>{throw attempt++===0?{status:503}:{status:422,code:'application_undetermined'};}});
 await extract(h);h.click('semantic-confirm');await tick();h.click('semantic-confirm');await tick();assert.equal(h.mounted.saveState().allowed,false);
});

test('editing after a lost committed response synchronizes revision and preserves edits until explicit free retry',async()=>{
 let paidCalls=0,readCalls=0,server={...draft};const requests=[];
 const h=harness({aiRequirements:async()=>{paidCalls++;return draft;},aiCriteria:async(_s,body)=>{
  requests.push(body);if(body.expected_revision!==server.revision)throw {status:409,code:'stale_revision'};
  server={...server,items:body.items,revision:server.revision+1,confirmed:true,criteria_sha256:hash};if(requests.length===1)throw {status:503};return server;
 },aiCurrentCriteria:async(active,id,signal)=>{readCalls++;assert.equal(active,session);assert.equal(id,draft.draft_id);assert.ok(signal instanceof AbortSignal);return server;}});
 await extract(h);h.click('semantic-confirm');await tick();assert.equal(server.revision,1);
 h.change('semantic-item-0-title','preserved further edit');h.click('semantic-confirm');await tick();
 assert.equal(readCalls,1);assert.equal(requests.length,2);assert.equal(paidCalls,1);assert.equal(h.get('semantic-item-0-title').value,'preserved further edit');assert.equal(h.mounted.saveState().allowed,false);assert.equal(h.get('semantic-check-preview').disabled,true);assert.match(h.contents(h.get('semantic-status')),/서버.*확인/);assert.match(h.contents(h.get('semantic-status')),/다시/);assert.match(h.contents(h.get('semantic-status')),/무료/);
 h.click('semantic-confirm');await tick();assert.deepEqual(requests.map(r=>r.expected_revision),[0,0,1]);assert.equal(server.items[0].title,'preserved further edit');assert.equal(server.revision,2);assert.equal(paidCalls,1);assert.equal(h.mounted.saveState().allowed,true);assert.equal(h.get('semantic-check-preview').disabled,false);
});

for(const patch of [{draft_id:'other'},{guide_sha256:reportHash},{revision:0},{revision:-1},{confirmed:false,criteria_sha256:null},{provider:'openai'},{items:[{...item,requirement_id:'other'}],requirements:[{...draft.requirements[0],requirement_id:'other'}]}])test(`invalid current criteria response cannot advance local revision: ${JSON.stringify(patch)}`,async()=>{
 const requests=[];let reads=0;const h=harness({aiRequirements:async()=>draft,aiCriteria:async(_s,body)=>{requests.push(body);throw {status:409,code:'stale_revision'};},aiCurrentCriteria:async()=>{reads++;return {...draft,revision:1,confirmed:true,criteria_sha256:hash,...patch};}});
 await extract(h);h.change('semantic-item-0-title','preserved');h.click('semantic-confirm');await tick();assert.equal(reads,1);assert.equal(h.mounted.saveState().allowed,false);assert.equal(h.get('semantic-item-0-title').value,'preserved');assert.match(h.contents(h.get('semantic-status')),/확인하지 못/);
 h.click('semantic-confirm');await tick();assert.deepEqual(requests.map(r=>r.expected_revision),[0,0]);
});

for(const action of ['dispose','invalidate'])test(`pending current criteria response cannot revive ${action}d state`,async()=>{
 let finish,signal;const requests=[];const h=harness({aiRequirements:async()=>draft,aiCriteria:async(_s,body)=>{requests.push(body);throw {status:409,code:'stale_revision'};},aiCurrentCriteria:(_s,_id,s)=>{signal=s;return new Promise(resolve=>{finish=resolve;});}});
 await extract(h);h.change('semantic-item-0-title','preserved');h.click('semantic-confirm');await tick();assert.ok(signal instanceof AbortSignal);
 if(action==='dispose')h.mounted.dispose();else h.change('semantic-model','other-model');assert.equal(signal.aborted,true);
 finish({...draft,revision:3,confirmed:true,criteria_sha256:hash});await tick();assert.equal(h.mounted.saveState().allowed,false);assert.equal(h.get('semantic-check-preview').disabled,true);
 if(action==='dispose'){assert.equal(h.get('semantic-status').children.length,0);assert.equal(h.get('semantic-criteria').children.length,0);}else{h.click('semantic-confirm');await tick();assert.deepEqual(requests.map(r=>r.expected_revision),[0,0]);}
});

for(const status of [503,404])test(`current criteria lookup failure ${status} keeps local edits and handles expiry`,async()=>{
 const h=harness({aiRequirements:async()=>draft,aiCriteria:async()=>{throw {status:409,code:'stale_revision'};},aiCurrentCriteria:async()=>{throw {status};}});await extract(h);h.change('semantic-item-0-title','preserved');h.click('semantic-confirm');await tick();assert.equal(h.mounted.saveState().allowed,false);assert.equal(h.get('semantic-item-0-title').value,'preserved');if(status===404)assert.equal(h.events.at(-1),'expired');else assert.match(h.contents(h.get('semantic-status')),/확인하지 못/);
});

const diagnosticCases=[
 ['transport','upstream_http','제공자'],['transport','tls_failed','인증서'],['transport','timeout','시간'],['transport','transport_failed','연결'],
 ['provider_response','provider_envelope_invalid','응답 형식'],['provider_response','output_truncated','출력 한도'],['provider_response','response_refused','거절'],['provider_response','tool_call','도구 호출'],
 ['output_validation','empty_output','빈 응답'],['output_validation','response_too_large','크기'],['output_validation','unsafe_output','안전'],
 ['json_decode','malformed_json','JSON'],['report_validation','report_contract_invalid','검사 계약'],['report_validation','citation_invalid','원문 인용'],['requirement_validation','requirement_contract_invalid','요구사항 추출'],['requirement_validation','citation_invalid','원문 인용'],['result_build','result_invalid','결과 구성']
];
for(const [stage,reason,label] of diagnosticCases)test(`diagnostic ${reason} has safe specific Korean guidance`,async()=>{
 const diagnostic={id:'a'.repeat(32),stage,reason};assert.deepEqual(validateDiagnostic(diagnostic),diagnostic);assert.ok(diagnosticMessage(diagnostic).includes(label));
 const h=harness({aiRequirements:async()=>{throw {status:502,code:'cloud_invalid_response',diagnostic,message:'PRIVATE'};}});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();
 const text=h.contents(h.get('semantic-status'));assert.ok(text.includes(label));assert.ok(text.includes(diagnostic.id));assert.equal(text.includes('PRIVATE'),false);assert.match(text,/비용/);assert.equal(h.get('semantic-consent').checked,false);assert.equal(h.get('semantic-submit').disabled,true);assert.equal(h.get('semantic-results').children.length,0);
});
test('unknown and malformed diagnostics use generic guidance and stale failure cannot overwrite current status',async()=>{
 for(const diagnostic of [null,{}, {id:'a'.repeat(32),stage:'transport',reason:'PRIVATE'}, {id:'PRIVATE',stage:'json_decode',reason:'malformed_json'}]){
  assert.equal(validateDiagnostic(diagnostic),undefined);assert.equal(diagnosticMessage(diagnostic),'');
  const h=harness({aiRequirements:async()=>{throw {status:502,diagnostic};}});h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();assert.match(h.contents(h.get('semantic-status')),/요청을 완료하지/);assert.equal(h.contents(h.mounted.panel).includes('PRIVATE'),false);
 }
 let reject;const h=harness({aiRequirements:()=>new Promise((_resolve,no)=>{reject=no;})});h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');h.change('semantic-model','changed');const before=h.contents(h.get('semantic-status'));reject({status:502,diagnostic:{id:'a'.repeat(32),stage:'provider_response',reason:'output_truncated'}});await tick();assert.equal(h.contents(h.get('semantic-status')),before);
});

test('diagnosed report failure preserves confirmed criteria and requires explicit renewed consent',async()=>{
 let checks=0;
 const h=harness({aiRequirements:async()=>draft,aiCriteria:async(_s,b)=>({...draft,items:b.items,revision:1,confirmed:true,criteria_sha256:hash}),aiCheck:async()=>{checks++;throw {status:422,code:'ai_invalid_citation',diagnostic:{id:'a'.repeat(32),stage:'report_validation',reason:'citation_invalid'}};}});
 h.fill();h.click('semantic-requirements-preview');h.consent();h.click('semantic-submit');await tick();h.change('semantic-item-0-title','확정한 사용자 제목');h.click('semantic-confirm');await tick();
 h.change('semantic-api-key','secret-key');h.click('semantic-check-preview');h.consent();h.click('semantic-submit');await tick();
 assert.equal(checks,1);assert.equal(h.get('semantic-item-0-title').value,'확정한 사용자 제목');assert.equal(h.get('semantic-confirm').disabled,true);assert.equal(h.get('semantic-check-preview').disabled,false);assert.equal(h.mounted.saveState().allowed,true);assert.equal(h.get('semantic-results').children.length,0);assert.match(h.contents(h.get('semantic-status')),/원문 인용/);
 h.click('semantic-submit');assert.equal(checks,1);h.change('semantic-api-key','secret-key');h.click('semantic-check-preview');h.click('semantic-submit');assert.equal(checks,1);h.consent();h.click('semantic-submit');await tick();assert.equal(checks,2);
});

test('explicit saved-criteria preparation uses one free GET then preview and renewed consent before checking',async()=>{
 const confirmed={...draft,revision:1,confirmed:true,criteria_sha256:hash};let gets=0,checks=0;
 const h=harness({aiCurrentCriteria:async(_s,id)=>{gets++;assert.equal(id,'d');return confirmed;},aiCheck:async()=>{checks++;return liveResult();}},{...session,semantic_archive:{draft:confirmed,check:liveResult()}});
 assert.equal(gets,0);assert.equal(h.get('semantic-check-preview').disabled,true);h.click('semantic-resume');await tick();
 assert.equal(gets,1);assert.equal(checks,0);assert.equal(h.get('semantic-provider').value,'gemini');assert.equal(h.get('semantic-model').value,'model');assert.equal(h.get('semantic-item-0-title').value,item.title);assert.ok(h.get('semantic-archive').children.length);assert.equal(h.get('semantic-check-preview').disabled,false);assert.match(h.contents(h.get('semantic-status')),/AI를 호출하지/);
 h.change('semantic-api-key','secret-key');h.click('semantic-check-preview');h.click('semantic-submit');assert.equal(checks,0);h.consent();h.click('semantic-submit');await tick();assert.equal(checks,1);
});
for(const value of [null,{...draft,confirmed:false},{...draft,confirmed:true,criteria_sha256:reportHash},{...draft,confirmed:true,criteria_sha256:hash,draft_id:'other'}])test(`saved-criteria invalid adoption stays blocked ${JSON.stringify(value)}`,async()=>{
 const confirmed={...draft,confirmed:true,criteria_sha256:hash};const h=harness({aiCurrentCriteria:async()=>value},{...session,semantic_archive:{draft:confirmed,check:null}});h.click('semantic-resume');await tick();assert.equal(h.get('semantic-check-preview').disabled,true);assert.equal(h.get('semantic-consent').checked,false);assert.ok(h.get('semantic-archive').children.length);
});
for(const action of ['dispose','invalidate'])test(`saved-criteria pending GET cannot revive ${action}`,async()=>{
 const confirmed={...draft,confirmed:true,criteria_sha256:hash};let resolve;const h=harness({aiCurrentCriteria:()=>new Promise(yes=>{resolve=yes;})},{...session,semantic_archive:{draft:confirmed,check:null}});h.click('semantic-resume');if(action==='dispose')h.mounted.dispose();else h.change('semantic-model','changed');resolve(confirmed);await tick();assert.equal(h.get('semantic-check-preview').disabled,true);assert.equal(h.get('semantic-criteria').children.length,0);
});
for(const status of [404,503])test(`saved-criteria free GET failure ${status} preserves archive`,async()=>{
 const confirmed={...draft,confirmed:true,criteria_sha256:hash};const h=harness({aiCurrentCriteria:async()=>{throw {status};}},{...session,semantic_archive:{draft:confirmed,check:null}});h.click('semantic-resume');await tick();assert.equal(h.get('semantic-check-preview').disabled,true);assert.ok(h.get('semantic-archive').children.length);if(status===404)assert.ok(h.events.includes('expired'));else assert.match(h.contents(h.get('semantic-status')),/저장한 기준/);
});
