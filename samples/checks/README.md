# 오프라인 보고서 검사 개발 예제

세 JSON은 기존 합성 개발 가족의 normal·missing·paraphrased PDF에 대해 직접 작성한 테스트 응답이다. 의미 판단과 인용할 문장은 별도로 작성하고, 출처 해시와 블록 로컬 문자 범위는 실제 PDF 추출 결과에 연결했다. 기존 truth.json에서 생성하거나 런타임에 정답을 읽지 않는다. 사람 검수·독립 평가·실제 AI 응답으로 사용하지 않는다.

기준은 T04b 데모의 기존 5항목을 유지하고 R4를 `does_not_apply`, 사유를 `합성 문장만 사용`으로 저장한 revision 1 / 확정 version 1이다. 응답의 criteria_sha256는 원본 초안과 확정 기준의 내용 전체에 귀속된다. 제목·하위 조건·제외/적용 상태·사유를 수정하면 새 응답이 필요하다. R4는 응답에서 빠지며 신뢰한 기준으로 미적용 결과를 생성한다.

normal·paraphrased는 R1/R2의 하위 조건에 본문 인용을 연결한다. missing은 R2-S2 출력 설명을 `evidence_missing`으로 남겨 부모를 부분 충족으로 산출한다. 누락본에 남아 있는 `입력과 출력` 제목을 본문 근거로 사용하지 않는다. R3 선택 항목의 근거 미확인은 필수 누락 경고가 아니다. R5 분량은 T05b 규칙 평가 전까지 판단 보류이며 보고서 자기 설명으로 페이지 수를 확정하지 않는다.

인용 존재 검증은 의미적 충족의 정답 검증이 아니다. evidence_role과 relation도 응답자의 주장이며 허위 content 라벨을 탐지한다고 보장하지 않는다. reviewed_block_ids는 검토했다고 선언한 범위이며 실제 AI가 읽었다는 증거가 아니다. 결과에는 테스트 응답·실제 AI 미호출·의미 정확도 미검증·전체 요구사항 보장 없음 표시와 원본/보고서의 처리 범위를 보존한다.

API 폴더에서 기존 가상환경으로 재현한다:

```sh
PYTHONPATH=src .venv/bin/python tools/run_report_check_demo.py
.venv/bin/python -m pytest -q tests/test_report_check_demo.py
```

출력은 세 보고서의 불변 검사 JSON이다. 이 내부 경로는 기존 `/review` 화면이나 업로드 endpoint와 아직 연결하지 않았다. 원본 PDF 이미지·검사 결과 화면은 T06, 실제 AI 공급사 호출·평가는 D04와 T09의 후속 범위다.
