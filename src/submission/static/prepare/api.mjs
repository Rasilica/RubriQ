import {validateSession} from './state.mjs';
import {validateDiagnostic} from './ai-diagnostic.mjs';
export class ApiError extends Error {
  constructor(code,status=0,diagnostic){super(code);this.code=code;this.status=status;this.diagnostic=validateDiagnostic(diagnostic);}
}
export function createAPI(fetcher=fetch){
  async function request(path,{token,signal,method='GET',body,binary,local=false,apiKey}={}){
    const headers=token?{'X-Session-Token':token}:{};
    if(local)headers['X-Local-Client']='prepare';
    if(apiKey&&body?.use_saved_key!==true)headers['X-AI-API-Key']=apiKey;
    if(body&&!(body instanceof FormData))headers['Content-Type']='application/json';
    const response=await fetcher(`/api/document-pairs${path}`,{method,headers,body:body instanceof FormData?body:body?JSON.stringify(body):undefined,signal,cache:'no-store',credentials:'omit',redirect:'error'});
    if(binary&&response.ok){
      const type=response.headers.get('content-type')?.split(';')[0];
      if(type!==binary)throw new ApiError('invalid_asset');
      const blob=await response.blob();
      if(!blob.size||blob.size>(binary==='image/png'?8:10)*1024*1024)throw new ApiError('invalid_asset');
      return blob;
    }
    let value;try{value=await response.json();}catch{throw new ApiError('invalid_response',response.status);}
    if(!response.ok||value?.success!==true)throw new ApiError(value?.error?.code??'request_failed',response.status,value?.error?.diagnostic);
    return value.data;
  }
  function base(session){return `/${encodeURIComponent(session.session_id)}`;}
  const options=(session,signal)=>({token:session.access_token,signal});
  return {
    async prepare(form,signal){const data=validateSession(await request('',{method:'POST',body:form,signal}));if(typeof data.access_token!=='string'||!data.access_token)throw new ApiError('invalid_token');return data;},
    async inspect(session,signal){return validateSession(await request(base(session),options(session,signal)));},
    remove(session,signal){return request(base(session),{...options(session,signal),method:'DELETE'});},
    image(session,role,page,signal){return request(`${base(session)}/${role}/pages/${page}.png`,{...options(session,signal),binary:'image/png'});},
    pdf(session,role,signal){return request(`${base(session)}/${role}/pdf`,{...options(session,signal),binary:'application/pdf'});},
    evidence(session,role,range,signal){return request(`${base(session)}/${role}/evidence`,{...options(session,signal),method:'POST',body:range});},
    aiRequirements(session,body,{apiKey,signal}={}){return request(`${base(session)}/ai/requirements`,{...options(session,signal),method:'POST',body,local:true,apiKey});},
    aiCriteria(session,body,signal){return request(`${base(session)}/ai/criteria`,{...options(session,signal),method:'POST',body,local:true});},
    aiCurrentCriteria(session,draftId,signal){return request(`${base(session)}/ai/criteria?draft_id=${encodeURIComponent(draftId)}`,{...options(session,signal),local:true});},
    aiCheck(session,body,{apiKey,signal}={}){return request(`${base(session)}/ai/check`,{...options(session,signal),method:'POST',body,local:true,apiKey});},
    cloudRewrite(session,role,range,{apiKey,signal}){return request(`${base(session)}/${role}/cloud-rewrite`,{...options(session,signal),method:'POST',body:range,local:true,apiKey});},
    ollamaModels(session,signal){return request(`/ollama/models?session_id=${encodeURIComponent(session.session_id)}`,{...options(session,signal),local:true});},
    ollamaRewrite(session,role,range,signal){return request(`${base(session)}/${role}/ollama-rewrite`,{...options(session,signal),method:'POST',body:range,local:true});},
    expression(session,role,range,signal){return request(`${base(session)}/${role}/expression-check`,{...options(session,signal),method:'POST',body:range,local:true});},
  };
}
