const MESSAGES = Object.freeze({
  application_undetermined:"조건부 항목의 적용 여부를 확인해주세요.",
  exclusion_reason_required:"제외한 항목의 사유를 적어주세요.",
  invalid_condition:"조건부 항목의 적용 조건을 적어주세요.",
  application_reason_required:"조건 적용 여부를 선택한 사유를 적어주세요.",
  stale_revision:"서버의 저장 상태가 달라졌습니다. 입력을 유지한 채 서버 상태를 확인해보세요.",
  empty_criteria:"포함한 요구사항이 하나 이상 있어야 확정할 수 있습니다.",
  version_limit:"이 데모 세션의 확정 횟수 한도에 도달했습니다.",
  session_limit:"데모 세션이 많아 시작하지 못했습니다. 잠시 뒤 다시 시도해주세요.",
  session_unavailable:"데모 세션이 만료되었거나 사용할 수 없습니다. 새 데모를 시작해주세요.",
  network_error:"서버에 연결하지 못했습니다. 입력 내용은 유지됩니다.",
  invalid_review_request:"입력 내용을 확인해주세요. 빈 제목이나 설명은 저장할 수 없습니다.",
});

export class ReviewError extends Error {
  constructor(code) {
    super(MESSAGES[code] ?? "요청을 처리하지 못했습니다. 입력을 유지하고 다시 시도해주세요.");
    this.name = "ReviewError";
    this.code = code;
  }
}

export function createReviewClient(fetcher = globalThis.fetch) {
  let sessionId = null;
  let sessionToken = null;
  async function request(method, path, body) {
    const headers = {"X-Review-Request":"1","Content-Type":"application/json"};
    if (path && sessionToken) headers["X-Review-Token"] = sessionToken;
    let response;
    try {
      response = await fetcher(`/api/review-sessions${path}`, {
        method,headers,credentials:"omit",cache:"no-store",
        signal:AbortSignal.timeout(15000),
        ...(body === undefined ? {} : {body:JSON.stringify(body)}),
      });
    } catch {
      throw new ReviewError("network_error");
    }
    let payload;
    try { payload = await response.json(); }
    catch { throw new ReviewError("invalid_response"); }
    if (!response.ok || payload?.success !== true) throw new ReviewError(payload?.error?.code ?? "invalid_response");
    return payload.data;
  }
  function path(suffix = "") {
    if (!sessionId || !sessionToken) throw new ReviewError("session_unavailable");
    return `/${encodeURIComponent(sessionId)}${suffix}`;
  }
  return Object.freeze({
    async start() {
      const data = await request("POST","",{});
      sessionId = data.session_id;
      sessionToken = data.session_token;
      const {session_token:removed,...publicData} = data;
      return publicData;
    },
    read:() => request("GET",path()),
    save:(revision,items) => request("PUT",path("/working-copy"),{expected_revision:revision,items}),
    confirm:(revision) => request("POST",path("/confirm"),{expected_revision:revision}),
  });
}
