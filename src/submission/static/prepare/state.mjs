export const ROLES={guide:'안내문',report:'보고서'};
export const STATUS={complete:'완료',partial:'부분 읽기',failed:'실패',unsupported:'지원 범위 밖',not_started:'미실행'};
export const KINDS={extraction_block:'추출문',paragraph:'문단',table_cell:'표 셀',footnote:'각주',header:'머리말',footer:'꼬리말'};
const WARNINGS={
  original_layout_unverified:'원본 레이아웃과 같은지 확인하지 못했습니다. 줄바꿈·표·쪽 나눔이 달라질 수 있습니다.',
  font_inventory_partial:'확인한 폰트 목록이 일부에 한정됩니다. 원본의 모든 폰트가 준비되었는지는 미확인입니다.',
  font_resolution_unverified:'실제로 사용된 폰트와 대체 여부는 확인하지 못했습니다. 글자 모양과 배치를 확인해주세요.',
};
const ERRORS={
  empty_file:'빈 파일입니다. 내용이 있는 문서를 올려주세요.',
  file_too_large:'파일이 10 MiB를 넘어 열지 않았습니다.',
  unsupported_format:'PDF·DOCX·HWP·HWPX 문서가 아니거나 지원하지 않는 형식입니다.',
  extension_mismatch:'파일 확장자와 실제 문서 형식이 다릅니다. 올바른 확장자로 저장해주세요.',
  mime_mismatch:'파일 종류 정보와 실제 문서 형식이 다릅니다.',
  corrupt_document:'파일이 손상되었거나 문서 구조가 올바르지 않습니다. 작성 프로그램에서 다시 저장해주세요.',
  encrypted_document:'암호가 걸린 문서라 읽을 수 없습니다. 암호를 해제한 뒤 다시 올려주세요.',
  protected_document:'배포용·보안 문서라 읽을 수 없습니다. 일반 문서로 다시 저장해주세요.',
  unsupported_version:'지원하지 않는 문서 버전입니다. 최신 한글이나 Word에서 다시 저장한 뒤 올려주세요.',
  unsupported_feature:'지원하지 않는 문서 기능이 들어 있어 읽지 않았습니다.',
  package_limit:'문서 안의 파일이 너무 많거나 커서 열지 않았습니다.',
  unsafe_package_path:'문서 안에 안전하지 않은 경로가 있어 열지 않았습니다.',
  duplicate_member:'문서 안에 같은 이름의 구성 파일이 중복되어 열지 않았습니다.',
  xml_limit:'문서 구조가 너무 크거나 깊어 열지 않았습니다.',
  unsafe_xml:'문서에 안전하지 않은 XML 구성이 있어 열지 않았습니다.',
  empty_document:'읽을 수 있는 본문이 없습니다.',
  too_many_pages:'50쪽을 넘는 문서는 열지 않습니다.',
  encrypted_pdf:'암호가 걸린 PDF는 읽을 수 없습니다.',
  invalid_pdf:'PDF가 손상되었거나 형식이 올바르지 않습니다.',
  invalid_config:'PDF 변환 도구 설정이 올바르지 않습니다. 서버 실행 설정을 확인해주세요.',
  unsupported_platform:'이 운영체제에서는 PDF 변환을 지원하지 않습니다.',
  unsupported_active_content:'스크립트·외부 연결처럼 실행되거나 밖으로 연결될 수 있는 내용이 있어 PDF 변환을 하지 않았습니다. 구조와 원문은 확인할 수 있습니다.',
  conversion_busy:'다른 문서를 PDF로 변환하고 있습니다. 잠시 후 다시 시도해주세요.',
  renderer_unavailable:'PDF 변환 도구가 준비되지 않았습니다. 서버 실행 설정을 확인해주세요.',
  renderer_failed:'PDF 변환 도구가 이 문서를 변환하지 못했습니다. 구조와 원문은 확인할 수 있습니다.',
  conversion_timeout:'PDF 변환 시간이 초과되었습니다.',
  process_output_limit:'PDF 변환 도구의 출력이 너무 커서 중단했습니다.',
  output_missing:'PDF 변환 결과 파일이 만들어지지 않았습니다.',
  output_invalid:'PDF 변환 결과가 올바르지 않습니다.',
  output_limit:'변환한 PDF가 너무 크거나 쪽수가 많습니다.',
  conversion_io_error:'PDF 변환 중 파일 처리 오류가 발생했습니다.',
  cleanup_failed:'PDF 변환 뒤 임시 파일을 정리하지 못했습니다.',
  session_not_found:'임시 문서가 만료되었거나 없습니다. 문서를 다시 준비해주세요.',
  preparation_busy:'다른 문서를 준비하고 있습니다. 잠시 후 다시 시도해주세요.',
  pair_failed:'이 문서를 준비하는 중 예상하지 못한 오류가 발생했습니다.',
  session_limit:'동시에 준비할 수 있는 문서 수를 넘었습니다. 기존 임시 문서를 삭제해주세요.',
  asset_unavailable:'요청한 페이지나 파일을 찾을 수 없습니다.',
  invalid_selection:'선택한 위치가 올바르지 않습니다.',
  preparation_timeout:'문서 준비 시간이 초과되었습니다.',
};
export function errorText(code){return Object.hasOwn(ERRORS,code)?ERRORS[code]:'이 문서를 준비하는 중 오류가 발생했습니다.';}
export function warningText(code){return Object.hasOwn(WARNINGS,code)?WARNINGS[code]:'문서 준비 중 추가 확인이 필요한 항목이 있습니다. 원본과 PDF를 함께 확인해주세요.';}
export function initialSelection(){return {guide:{block:null,page:1},report:{block:null,page:1}};}
export function selectBlock(state,role,block){return {...state,[role]:{...state[role],block}};}
export function selectPage(state,role,page,total){
  if(!Number.isInteger(page)||page<1||page>total)throw new Error('invalid_page');
  return {...state,[role]:{...state[role],page}};
}
export function unicodeRange(text,start,end){
  const boundary=n=>n===0||n===text.length||!(/[\uD800-\uDBFF]/u.test(text[n-1])&&/[\uDC00-\uDFFF]/u.test(text[n]));
  if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end<=start||end>text.length||!boundary(start)||!boundary(end))throw new Error('invalid_selection');
  return {start:[...text.slice(0,start)].length,end:[...text.slice(0,end)].length};
}
export function verifiedPages(result,total){
  const mapping=result?.mapping;
  if(result?.snapshot_origin!=='real_pdf'||!['identity','verified_anchor'].includes(mapping?.mapping_status))return [];
  const pages=mapping.target_page_numbers;
  return Array.isArray(pages)&&pages.length&&pages.every(p=>Number.isInteger(p)&&p>0&&p<=total)?pages:[];
}
export function mappingMatches(result,document,block,range){
  const mapping=result?.mapping;
  return result?.source_id===document.source.source_id&&result?.source_sha256===document.source.content_sha256&&result?.document_version_id===document.source.document_version_id&&result?.source_locator?.path===block.source_locator.path&&mapping?.source_block_id===block.block_id&&mapping?.source_char_range?.start===range.start&&mapping?.source_char_range?.end===range.end&&document.artifacts.some(artifact=>artifact.artifact_id===mapping.target_artifact_id&&artifact.artifact_sha256===result.target_artifact_sha256);
}
export function validateSession(value,now=Date.now()){
  if(!value||typeof value.project_name!=='string'||typeof value.session_id!=='string'||!/^[A-Za-z0-9_-]+$/u.test(value.session_id)||typeof value.expires_at!=='string'||!Number.isFinite(Date.parse(value.expires_at))||Date.parse(value.expires_at)<=now)throw new Error('invalid_session');
  for(const role of Object.keys(ROLES)){
    const entry=value[role];
    if(!entry||entry.role!==role||!Object.hasOwn(STATUS,entry.extraction_status)||!Object.hasOwn(STATUS,entry.rendering_status)||!Array.isArray(entry.warnings)||entry.warnings.some(w=>typeof w!=='string'))throw new Error('invalid_document');
    if(entry.preview_page_count!==null&&(!Number.isInteger(entry.preview_page_count)||entry.preview_page_count<1||entry.preview_page_count>50))throw new Error('invalid_pages');
    if(![null,'original_pdf','preview_pdf'].includes(entry.artifact_kind))throw new Error('invalid_artifact');
    if(entry.document!==null){
      const doc=entry.document;
      if(doc.source?.role!==role||typeof doc.source.filename!=='string'||!/^[a-f0-9]{64}$/u.test(doc.source.content_sha256)||!Array.isArray(doc.blocks)||!doc.coverage)throw new Error('invalid_document');
      const ids=new Set();
      for(const block of doc.blocks){
        if(typeof block.block_id!=='string'||ids.has(block.block_id)||typeof block.raw_text!=='string'||typeof block.source_locator?.path!=='string'||block.source_locator.source_sha256!==doc.source.content_sha256)throw new Error('invalid_block');
        ids.add(block.block_id);
      }
    }
  }
  return value;
}
export function createResources(urlAPI=URL){
  const requests=new Map();const urls=new Map();
  function release(key){const value=urls.get(key);if(value){urlAPI.revokeObjectURL(value);urls.delete(key);}}
  return {
    begin(key){requests.get(key)?.controller.abort();const request={key,controller:new AbortController()};request.signal=request.controller.signal;requests.set(key,request);return request;},
    current(request){return requests.get(request.key)===request&&!request.signal.aborted;},
    url(key,blob){release(key);const url=urlAPI.createObjectURL(blob);urls.set(key,url);return url;},
    release,
    clear(){for(const request of requests.values())request.controller.abort();requests.clear();for(const key of urls.keys())release(key);},
  };
}
