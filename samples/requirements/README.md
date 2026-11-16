# 요구사항 초안 오프라인 예제

`guide-offline-response.json`은 `../pdf/guide.pdf`의 추출 텍스트를 읽고 별도로 작성한 개발용 테스트 응답이다. 필수 3개, 선택 1개, 조건부 1개와 하위조건 5개를 포함한다. 실제 AI 응답이나 독립 평가 자료, 사람 검수 완료 결과가 아니다. 초안 어댑터는 호출자가 명시적으로 전달한 응답 JSON을 검증하며 `truth.json`을 읽어 추론하지 않는다. T04b의 고정 데모 로더만 이 파일과 안내문 PDF를 읽어 어댑터에 전달한다.

`prepare_requirement_request(document)`는 버전이 기록된 고정 지침·JSON schema·안내문 블록을 준비한다. `OfflineRequirementAdapter(response_json).extract(document)` 또는 `build_requirement_draft(document, response_json)`는 GUIDE 공통 문서와 응답을 검증해 미확정 초안을 반환한다. 네트워크·저장·사용자 확정·보고서 충족 판단은 이 단계에 포함되지 않는다.

인용 범위는 각 `block.raw_text` 안의 Python Unicode `[start, end)`다. PDF 페이지 안 오프셋이나 DOCX/HWPX 원본 문단 오프셋을 더하지 않는다. 응답은 `block_id`, `char_range`, `quote`만 제시하고 XML 위치·해시·원본 페이지는 검증 후 문서 블록에서 복사한다. 각주·표 뒤의 HWPX 문단 조각에서도 조각 ID와 로컬 범위가 기준이다.

모든 요구사항·하위조건·적용조건의 인용을 검증하며 하나라도 틀리면 전체 응답을 거부한다. 인용이 존재한다는 확인은 분류나 설명의 의미가 옳다는 증명이 아니므로 `needs_review`, `confirmed=false`, `semantic_accuracy_verified=false`, `guarantees_all_requirements=false`가 유지된다. `response_label=test_response`, `adapter_id=offline-fixture-v1`, `fake=true`, `ai_called=false`, `stored=false`가 함께 기록된다. 부분 읽기의 coverage·warnings·typed_errors를 보존하며 빈 목록은 `no_requirements_returned` 진단을 갖는다.

초기 개발용 한도는 2,000블록·입력 200,000문자·응답 UTF-8 1,000,000바이트다. 최대 요구사항 100개, 항목별 하위조건 20개, 각 인용 묶음 10개, 설명 2,000문자, 인용 10,000문자다. `RequirementLimits`로 더 작은 한도를 적용할 수 있으며 초과 시 자르지 않고 안전한 오류 코드로 거부한다.

API 디렉터리에서 검증:

```sh
.venv/bin/python -m pytest -q tests/test_requirement_*.py
```

PDF 다섯 항목은 실제 샘플 추출을 거치고, DOCX 표 셀과 HWPX 조각의 인용은 각 실제 reader 출력으로 검증한다. Office 원본 페이지는 미확인 상태인 `null`을 유지한다. 분량 항목은 안내문 문장과 포함 범위의 초안이며 실제 페이지 수 판정은 후속 단계다.

T04b 검토 화면은 로컬 FastAPI 서버의 `/review`에서 `데모 시작`으로 연다. 이 PDF와 테스트 응답을 실제 추출·인용 검증한 5개 항목을 수정·제외/복원·조건 확인하고 기준을 확정한다. 원본 초안은 바꾸지 않고 사용자 작업본과 불변 확정 버전을 별도로 유지한다. 버전의 원본 인용은 같은 세션의 `original_draft`와 항목 ID로 연결한다. 임시 메모리 세션이므로 새로고침·서버 재시작 뒤 복구되지 않으며, 임의 업로드·보고서 검사·실제 AI 호출·영구 저장은 아직 연결하지 않았다.
