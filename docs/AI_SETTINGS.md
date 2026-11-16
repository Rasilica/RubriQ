# 로컬 API 키 설정

`/prepare`의 API 키 설정에서 Gemini·OpenAI(GPT)·Anthropic(Claude)·빌링AI 키를 제공자별로 등록한다. 문서 업로드 전에도 사용할 수 있다. 키 입력란은 저장 시 비우고 화면에는 등록 여부만 표시한다. 같은 설정에서 키를 교체하거나 삭제한다. Ollama에는 API 키가 필요 없다.

명시적으로 저장한 키는 macOS Keychain, Windows Credential Manager, Linux Secret Service에 보관한다. 브라우저 저장소·문서 SQLite·프로젝트 설정 파일에 키를 기록하지 않는다. 운영체제 보안 저장소를 사용할 수 없거나 접근을 거부하면 저장이 실패한다. 평문 파일로 대신 저장하지 않으며 일회성 입력으로 실행할 수 있다. Linux에는 잠금 해제된 Secret Service와 사용자 D-Bus 세션이 필요하다.

저장한 키는 새로고침과 서버 재시작 뒤에 재사용한다. 키를 브라우저로 돌려보내지 않으며 추론 시 서버가 선택한 제공자의 키를 읽는다. 저장은 키의 유효성·잔액·모델 권한을 확인하는 외부 호출을 실행하지 않는다. 윤문·요구사항 추출·보고서 검사에는 매번 기존 전송 범위 확인과 동의가 필요하다. 키 저장만으로 AI 호출이나 자동 재시도가 발생하지 않는다.

운영체제가 Python의 보안 저장소 접근 허용을 요청할 수 있다. 이 보관 방식은 현재 사용자 계정의 운영체제 보안 경계를 사용한다. 같은 사용자 권한으로 실행되는 프로그램이나 손상된 운영체제로부터 키를 완전히 격리하는 별도의 금고는 아니다. 등록한 키가 노출된 경우 제공자에서 폐기·재발급해야 한다. 설정의 삭제는 로컬 보관만 제거하며 제공자 키 자체를 폐기하지 않는다.

## 로컬 API

- `GET /api/ai-settings`: 저장소 가용성과 제공자별 등록 여부만 조회한다.
- `PUT /api/ai-settings/{provider}`: JSON의 `api_key`로 등록 또는 교체한다. URL에 키를 넣지 않는다.
- `DELETE /api/ai-settings/{provider}`: 해당 제공자 키를 삭제한다.

설정 요청에는 `X-Local-Client: prepare`가 필요하다. 로컬 Host·동일 출처·요청 크기·요청 횟수 검사와 `no-store`를 적용한다. 추론 요청은 `use_saved_key: true`로 저장한 키 사용을 지정하거나 기존 `X-AI-API-Key`로 일회성 키를 전달한다. 키는 세션 토큰이나 문서 보관 스냅샷에 포함하지 않는다.

보관 라이브러리의 공식 설명: [Python keyring](https://keyring.readthedocs.io/en/latest/index.html). RubriQ는 지원하는 운영체제의 기본 보안 저장소를 직접 선택하고 임의의 제삼자·평문 backend를 사용하지 않는다.
