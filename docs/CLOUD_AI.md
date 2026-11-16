# Gemini · GPT · Claude · 빌링AI 연결

RubriQ `/prepare`에서 Gemini, OpenAI(GPT), Anthropic(Claude), 빌링AI를 선택해 원문 일부의 윤문 제안을 받을 수 있다. [빌링AI](BILLING_AI.md)는 빌링AI 키와 접두사 없는 모델 ID로 호출하는 별도 게이트웨이다. Ollama 로컬 모델 연결은 별도 패널로 유지한다. 윤문 기능은 요구사항 충족 여부 검사·AI 작성 여부 판정·자동 수정을 수행하지 않는다. 안내문과 보고서의 비교는 별도의 [요구사항 확인 후 AI 검사](SEMANTIC_AI.md) 흐름을 사용한다.

## 사용 순서

1. 문서를 준비하거나 저장본을 다시 연다.
2. 클라우드 AI 패널에서 제공자와 해당 계정에서 사용할 수 있는 모델 ID를 입력한다. 모델 이름은 공급사의 현재 문서를 확인한다. RubriQ는 임의의 모델을 자동 선택하거나 다른 제공자로 전환하지 않는다.
3. 설정에서 제공자별 API 키를 운영체제 보안 저장소에 등록하거나 이번 요청에 사용할 키를 직접 입력한다. 저장한 키는 브라우저에 다시 전달하지 않는다. 원본에서 최대 4,000자를 선택한다. 입력란은 저장 또는 실행 후 비운다.
4. 전송 미리보기에서 제공자·모델·정확한 선택 문구를 확인한다. 선택 문구와 윤문 지시문이 외부 제공자에게 전달되고 비용이 발생할 수 있다는 확인을 표시한 뒤 실행한다.
5. 원문과 제안을 비교한다. 사실·숫자·인용·의미 보존을 모델이 보장하지 않으므로 사람이 검토한다. 원문은 자동으로 바뀌지 않으며 결과는 영구 저장하지 않는다.

저장한 키는 새로고침·서버 재시작 뒤에도 재사용한다. 직접 입력한 일회성 키는 복원하지 않는다. 보관 방식과 교체·삭제는 [API 키 설정](AI_SETTINGS.md)을 참고한다. 사용자 브라우저 확장·운영체제·네트워크 프록시의 보안은 별도로 관리해야 한다.

## 전송·비용·데이터 정책

로컬에서 앱을 실행해도 클라우드 AI 요청은 외부 전송이다. 원본 파일이나 문서 전체를 업로드하지 않으며 사용자가 미리보기에서 확인한 범위와 시스템 지시문만 보낸다. 오류·대기·새로고침만으로 자동 재시도하지 않는다. 재실행은 별도 확인이 필요하며 중복 과금될 수 있다. 브라우저 취소가 이미 처리 중인 외부 요청의 취소나 비용 취소를 보장하지 않는다.

동시 클라우드 요청은 1개이며 분당 최대 10회의 실행을 허용한다. 입력은 4,000자, 출력 요청은 최대 1,024 토큰, 표시 제안은 8,000자다. 응답은 1 MiB 이내이며 HTTP 소켓 timeout은 60초다. 실제 토큰 사용량이 제공되면 표시하지만 이를 달러 비용이나 청구서로 해석하지 않는다. 키 계정의 예산·사용량 경보도 제공자에서 설정한다.

OpenAI 요청에는 `store: false`를 사용한다. 이는 제공자의 모든 보관을 없애거나 Zero Data Retention을 보장한다는 뜻이 아니다. 학습 사용·보관·무료/유료 계정 조건은 제공자의 정책을 따른다.

- [OpenAI 데이터 관리](https://developers.openai.com/api/docs/guides/your-data)
- [Gemini API 이용 약관](https://ai.google.dev/gemini-api/terms)
- [Claude API 데이터 보관](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)

## API와 검증

`POST /api/document-pairs/{session_id}/{role}/cloud-rewrite`

- 인증 헤더: `X-Session-Token`, `X-Local-Client: prepare`, `X-AI-API-Key`.
- JSON: `{block_id, start, end, provider, model, consent, source_sha256, use_saved_key}`. `provider`는 `gemini`, `openai`, `anthropic`, `billingai`이다. 저장한 키를 사용할 때 `use_saved_key: true`로 요청하며 키 헤더를 보내지 않는다. 일회성 키는 인증 헤더로 전달한다. 추론 요청 본문·URL에 키를 넣지 않는다.
- 서버는 동의와 원본 해시·구조 블록·Unicode 범위를 검증한 뒤 해당 원문을 다시 읽는다. 사용자 입력 원문을 그대로 신뢰하지 않는다.
- 응답은 기존 envelope에 제공자·모델·원문 해시·블록·범위·원문·제안·사용량을 포함한다. 브라우저도 원문과 응답을 다시 대조한다.
- 공식 HTTPS 주소만 사용하며 프록시·리디렉션·사용자 지정 URL·도구·스트리밍·파일 업로드·자동 재시도를 사용하지 않는다.
- 키 오류·권한·요청 제한·시간 초과·잘못된 응답·중단된 생성은 안전한 오류로 반환한다. 키와 문구를 로그나 예외 응답에 넣지 않는다. 길이 제한으로 잘린 생성이나 거절을 성공 제안으로 표시하지 않는다.

공식 인터페이스: [Gemini generateContent](https://ai.google.dev/api/generate-content), [OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create). 모델별 기능·사용 가능 여부는 다를 수 있다.

실제 키가 없는 개발 환경에서는 공급사 계약 시험과 합성 자료·시험용 응답으로 검증한다. 이는 실제 계정 권한·과금·생성 품질·모델 호환성의 검증을 대신하지 않는다.
