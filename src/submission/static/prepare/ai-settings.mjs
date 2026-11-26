const PROVIDERS={gemini:'Gemini',openai:'OpenAI (GPT)',anthropic:'Anthropic (Claude)',billingai:'빌링AI'};
const validKey=value=>typeof value==='string'&&/^[\x21-\x7e]{1,512}$/u.test(value);
const unavailable=()=>({available:false,backend:null,providers:[]});
export function createSettingsAPI(fetcher=fetch){
  async function request(provider,method='GET',apiKey){
    const response=await fetcher(`/api/ai-settings${provider?`/${provider}`:''}`,{method,headers:{'X-Local-Client':'prepare',...(apiKey?{'Content-Type':'application/json'}:{})},body:apiKey?JSON.stringify({api_key:apiKey}):undefined,cache:'no-store',credentials:'omit',redirect:'error'});
    const value=await response.json();if(!response.ok||value?.success!==true)throw new Error('settings_unavailable');return value.data;
  }
  const check=provider=>{if(!Object.hasOwn(PROVIDERS,provider))throw new Error('invalid_provider');};
  return {status:()=>request(),save(provider,key){check(provider);if(!validKey(key))throw new Error('invalid_key');return request(provider,'PUT',key);},remove(provider){check(provider);return request(provider,'DELETE');}};
}
export function createKeyStatus(){
  let value=unavailable();const listeners=new Set();
  return {snapshot:()=>structuredClone(value),configured:provider=>value.available&&value.providers.some(item=>item.provider===provider&&item.configured),subscribe(callback){listeners.add(callback);return ()=>listeners.delete(callback);},update(next){
    value=unavailable();
    const valid=typeof next?.available==='boolean'&&Array.isArray(next.providers)&&(next.available===false||(typeof next.backend==='string'&&next.providers.length===4&&new Set(next.providers.map(p=>p.provider)).size===4&&next.providers.every(p=>Object.hasOwn(PROVIDERS,p.provider)&&typeof p.configured==='boolean')));
    if(valid&&next.available)value={available:true,backend:next.backend,providers:next.providers.map(({provider,configured})=>({provider,configured}))};
    for(const callback of listeners)callback();if(!valid)throw new Error('invalid_settings_status');
  }};
}
export function credentialChoice(provider,key,status){
  if(provider==='ollama'||provider==='demo')return {useSavedKey:false,apiKey:undefined};
  if(key){if(!validKey(key))throw new Error('invalid_key');return {useSavedKey:false,apiKey:key};}
  if(status?.configured(provider))return {useSavedKey:true,apiKey:undefined};throw new Error('key_required');
}
export function keyStatusText(provider,status){
  if(provider==='ollama')return 'Ollama는 API 키 없이 로컬에서 실행합니다.';
  if(provider==='demo')return '체험 모드는 API 키가 필요 없습니다.';
  if(!Object.hasOwn(PROVIDERS,provider))return '제공자를 선택하면 저장된 키 상태가 표시됩니다.';
  return status?.configured(provider)?'저장된 키를 기본으로 사용합니다. 이번 요청에 다른 키를 쓰려면 아래에 입력하세요.':'저장된 키가 없거나 보안 저장소를 사용할 수 없습니다. 설정에서 저장하거나 이번 요청의 키를 입력하세요.';
}
export function mountKeySettings({ui,api=createSettingsAPI(),status=createKeyStatus()}){
  const {element,button,field}=ui;let busy=false,disposed=false,generation=0;
  const panel=element('details','panel stack');panel.id='ai-settings';
  const heading=element('summary','','AI API 키 설정');const message=element('p','notice');message.id='ai-settings-status';message.setAttribute('role','status');
  const fields=[];
  const refresh=button('저장 상태 새로고침',()=>void load());refresh.id='ai-settings-refresh';
  panel.append(heading,element('p','muted','키는 이 컴퓨터의 운영체제 보안 저장소에 보관합니다. 브라우저나 문서에는 저장하지 않습니다. 저장소를 사용할 수 없으면 저장하지 않습니다. 외부 AI 실행 전에는 매번 전송 범위와 비용에 동의해야 합니다.'),message,refresh);
  for(const [provider,label] of Object.entries(PROVIDERS)){
    const row=element('section','stack expression-panel');const title=element('h3','',label);const state=element('p','muted');state.id=`settings-${provider}-status`;
    const wrapper=field({id:`settings-${provider}-key`,label:`${label} API 키`,onChange:()=>{}});const input=wrapper.querySelector('input');input.type='password';input.autocomplete='off';input.maxLength=512;input.spellcheck=false;
    const save=button('키 저장·교체',()=>void mutate(provider,input,'save'));save.id=`settings-${provider}-save`;
    const remove=button('저장된 키 삭제',()=>void mutate(provider,input,'remove'));remove.id=`settings-${provider}-delete`;
    const actions=element('div','cluster');actions.append(save,remove);row.append(title,state,wrapper,actions);panel.append(row);fields.push({provider,input,state,save,remove});
  }
  function controls(){const current=status.snapshot();refresh.disabled=busy||disposed;for(const f of fields){f.state.textContent=current.available?(status.configured(f.provider)?'저장됨 · 키 값은 표시하지 않습니다.':'저장된 키 없음'):'보안 저장소 사용 불가';f.input.disabled=f.save.disabled=busy||disposed||!current.available;f.remove.disabled=busy||disposed||!status.configured(f.provider);}panel.setAttribute('aria-busy',String(busy));}
  const off=status.subscribe(controls);
  async function load(){if(busy||disposed)return;busy=true;const current=++generation;controls();message.textContent='보안 저장소 상태를 확인 중입니다.';
    try{const value=await api.status();if(disposed||generation!==current)return;status.update(value);message.textContent=value.available?'이 컴퓨터의 저장 상태입니다.':'운영체제 보안 저장소를 사용할 수 없습니다. 키를 저장하지 않습니다.';}
    catch{if(!disposed&&generation===current){status.update(unavailable());message.textContent='보안 저장소 상태를 확인할 수 없습니다. 키를 저장하지 않습니다.';}}
    finally{if(generation===current){busy=false;controls();}}
  }
  async function mutate(provider,input,action){if(busy||disposed)return;let key=input.value;input.value='';busy=true;const current=++generation;controls();
    try{await (action==='save'?api.save(provider,key):api.remove(provider));key='';if(disposed||generation!==current)return;const value=await api.status();if(disposed||generation!==current)return;status.update(value);message.textContent=value.available?(action==='save'?'키를 보안 저장소에 저장했습니다.':'저장된 키를 삭제했습니다.'):'보안 저장소를 사용할 수 없습니다. 상태를 다시 확인해주세요.';}
    catch{if(!disposed&&generation===current){status.update(unavailable());message.textContent='키 설정을 완료하지 못했습니다. 입력값과 보안 저장소를 확인한 뒤 상태를 새로고침해주세요.';}}
    finally{key='';if(generation===current){busy=false;controls();}}
  }
  controls();void load();return {panel,status,clearInputs(){for(const f of fields)f.input.value='';},dispose(){disposed=true;generation++;off();for(const f of fields)f.input.value='';controls();}};
}
