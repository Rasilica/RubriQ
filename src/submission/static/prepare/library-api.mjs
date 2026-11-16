import {ApiError} from './api.mjs';
import {validateSession} from './state.mjs';
import {validateSemanticArchive} from './newsemantic.mjs';
const validItem=item=>item&&typeof item.saved_id==='string'&&/^[A-Za-z0-9_-]+$/u.test(item.saved_id)&&typeof item.project_name==='string'&&typeof item.saved_at==='string'&&Number.isFinite(Date.parse(item.saved_at));
export function validateLibrary(value){
  if(!value||!Array.isArray(value.items)||value.items.length>20||!value.items.every(validItem)||!Number.isInteger(value.total)||value.total<0||!Number.isInteger(value.page)||value.page<1||value.page_size!==20)throw new ApiError('invalid_response');
  return value;
}
export function environmentText(session){
  const saved=session.saved_environment,current=session.current_environment;
  const status=!saved?.length||!current?.length?'저장 당시 또는 현재 환경은 미기록입니다.':JSON.stringify(saved)===JSON.stringify(current)?'저장 당시와 현재 도구 구성이 같습니다.':'저장 당시와 현재 도구 구성이 달라졌습니다.';
  return `${status} 저장된 결과를 그대로 열었으며 다시 읽거나 변환하지 않았습니다.`;
}
export function libraryError(error){
  const messages={library_not_found:'저장본을 찾을 수 없습니다. 목록을 새로고침해주세요.',library_corrupt:'저장본의 무결성을 확인하지 못했습니다. 다른 저장본을 열거나 원본을 다시 준비해주세요.',library_limit:'보관 한도에 도달했습니다. 불필요한 저장본을 삭제한 뒤 다시 시도해주세요.',library_unavailable:'문서 보관소에 접근하지 못했습니다. 잠시 후 다시 시도해주세요.',library_forbidden:'보관 요청을 확인하지 못했습니다. 이 로컬 화면을 새로고침해주세요.'};
  return messages[error?.code]??(error?.status===429?'요청이 많습니다. 잠시 후 다시 시도해주세요.':'요청을 완료하지 못했습니다. 연결을 확인하고 다시 시도해주세요.');
}
export function createLibraryAPI(fetcher=fetch){
  async function request(path,{method='GET',token,signal}={}){
    const headers={'X-Local-Client':'prepare',...(token?{'X-Session-Token':token}:{})};
    const response=await fetcher(path,{method,headers,signal,cache:'no-store',credentials:'omit',redirect:'error'});
    let value;try{value=await response.json();}catch{throw new ApiError('invalid_response',response.status);}
    if(!response.ok||value?.success!==true)throw new ApiError(value?.error?.code??'request_failed',response.status);
    return value.data;
  }
  return {
    async list(page,signal){return validateLibrary(await request(`/api/document-library?page=${page}`,{signal}));},
    async save(session,signal){const value=await request(`/api/document-pairs/${encodeURIComponent(session.session_id)}/save`,{method:'POST',token:session.access_token,signal});if(!validItem(value)||typeof value.already_saved!=='boolean'||(('has_semantic_archive' in value||'has_check' in value)&&(![value.has_semantic_archive,value.has_check].every(flag=>typeof flag==='boolean')||(value.has_check&&!value.has_semantic_archive))))throw new ApiError('invalid_response');return value;},
    async open(id,signal){
      const value=validateSession(await request(`/api/document-library/${encodeURIComponent(id)}/open`,{method:'POST',signal}));
      if(typeof value.access_token!=='string'||!value.access_token||!validItem(value)||![value.saved_environment,value.current_environment].every(items=>Array.isArray(items)&&items.every(item=>typeof item==='string')))throw new ApiError('invalid_response');
      validateSemanticArchive(value.semantic_archive,value);return value;
    },
    async remove(id,signal){const value=await request(`/api/document-library/${encodeURIComponent(id)}`,{method:'DELETE',signal});if(value?.deleted!==true)throw new ApiError('invalid_response');return value;},
  };
}
