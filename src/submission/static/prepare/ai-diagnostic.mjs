const STAGES=new Set(['transport','provider_response','output_validation','json_decode','report_validation','result_build']);
const MESSAGES=Object.freeze({
 upstream_http:'AI 제공자가 요청을 완료하지 못했습니다.',
 tls_failed:'AI 제공자의 보안 인증서를 확인하지 못했습니다.',
 timeout:'AI 응답 대기 시간이 초과되었습니다.',
 transport_failed:'AI 제공자와의 연결을 완료하지 못했습니다.',
 provider_envelope_invalid:'AI 제공자의 응답 형식을 확인하지 못했습니다.',
 output_truncated:'AI 응답이 출력 한도로 종료되어 완전한 결과를 받지 못했습니다.',
 response_refused:'AI가 응답을 거절하여 검사 결과를 만들지 못했습니다.',
 tool_call:'AI가 검사 결과 대신 도구 호출을 반환했습니다.',
 empty_output:'AI가 빈 응답을 반환하여 검사 결과를 만들지 못했습니다.',
 response_too_large:'AI 응답이 허용된 크기를 초과했습니다.',
 unsafe_output:'AI 응답이 안전 검증을 통과하지 못했습니다.',
 malformed_json:'AI 응답의 JSON을 해석하지 못했습니다.',
 report_contract_invalid:'AI 응답이 검사 계약을 충족하지 못했습니다.',
 citation_invalid:'AI 응답의 원문 인용을 검증하지 못했습니다.',
 result_invalid:'AI 응답 검증 후 결과 구성에 실패했습니다.',
});
export function validateDiagnostic(value){
 if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==3)return undefined;
 if(!['id','stage','reason'].every(key=>Object.hasOwn(value,key)))return undefined;
 if(typeof value.id!=='string'||! /^[a-f0-9]{32}$/u.test(value.id)||typeof value.stage!=='string'||typeof value.reason!=='string'||!STAGES.has(value.stage)||!Object.hasOwn(MESSAGES,value.reason))return undefined;
 return Object.freeze({id:value.id,stage:value.stage,reason:value.reason});
}
export function diagnosticMessage(value){
 const diagnostic=validateDiagnostic(value);
 return diagnostic?`${MESSAGES[diagnostic.reason]} 진단 ID: ${diagnostic.id}.`:'';
}
