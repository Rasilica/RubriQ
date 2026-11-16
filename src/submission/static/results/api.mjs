const CASE_IDS=Object.freeze(["normal","missing","over_limit","unconfirmed_scope","docx_structure","hwpx_structure"]);
const MESSAGES=Object.freeze({network_error:"결과를 불러오지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해주세요.",result_not_found:"요청한 예제를 찾을 수 없습니다.",result_demo_unavailable:"예제 결과를 준비하지 못했습니다. 잠시 뒤 다시 시도해주세요.",result_rate_limited:"요청이 많습니다. 잠시 뒤 다시 시도해주세요.",invalid_response:"결과 응답을 읽을 수 없습니다. 다시 시도해주세요."});

export class ResultsError extends Error {
  constructor(code) {super(MESSAGES[code] ?? MESSAGES.invalid_response);this.name="ResultsError";this.code=code;}
}

export function createResultsClient(fetcher=globalThis.fetch) {
  async function request(suffix) {
    let response;
    try {response=await fetcher(`/api/result-demos${suffix}`,{method:"GET",credentials:"omit",cache:"no-store",signal:AbortSignal.timeout(15000)});}
    catch {throw new ResultsError("network_error");}
    let payload;
    try {payload=await response.json();} catch {throw new ResultsError("invalid_response");}
    if(!response.ok || payload?.success !== true || !payload.data) throw new ResultsError(payload?.error?.code ?? "invalid_response");
    return payload.data;
  }
  return Object.freeze({list:()=>request(""),detail:(id)=>{
    if(!CASE_IDS.includes(id)) throw new ResultsError("result_not_found");
    return request(`/${id}`);
  }});
}
