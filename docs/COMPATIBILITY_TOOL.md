# 문서 호환성 검토 도구

프로젝트 API 폴더에서 실행한다. 출력 폴더는 새 경로여야 한다.

```sh
PYTHONPATH=src .venv/bin/python -m tools.run_compatibility manifest.json review-output .runtime/batch/pair-runtime.json
```

마지막 런타임 인수를 생략하면 `DOCUMENT_PAIR_RUNTIME_FILE`을 읽는다. 둘 다 없으면 PDF 읽기와 DOCX/HWPX 구조 읽기는 가능하지만 설치형 reader/변환이 필요한 작업은 실패 상태로 기록한다. 전역 Java 설정을 바꾸거나 외부 서비스에 자료를 전송하지 않는다.

manifest 예시:

```json
{
  "schema_version": 1,
  "cases": [{
    "case_id": "family-a-hwp",
    "family_id": "family-a",
    "split": "development",
    "provenance": "synthetic",
    "format": "hwp",
    "authoring_app": "합성 fixture generator",
    "authoring_version": "1",
    "fonts": ["Noto Sans CJK KR"],
    "source": {"path": "source.hwp", "sha256": "실제 파일의 소문자 SHA256 64자리"},
    "reference": null,
    "reference_origin": "authoring_app_export",
    "anchors": [{"quote": "기대 문구", "locator_path": null}],
    "layout_review": null
  }]
}
```

경로는 manifest 기준 상대 경로나 절대 경로다. 심볼릭 링크가 포함된 경로는 거부하므로 macOS 임시 경로는 `/tmp` 대신 실제 `/private/tmp` 경로를 사용한다. 파일당 10 MiB, PDF 100쪽, 문구 추출 20만 자, manifest 1 MiB, 최대 100개 case/100개 문구, 생성 PDF 합계 256 MiB를 제한한다. case 준비와 문구 비교는 180초 제한을 공유한다. 각 PDF snapshot은 case당 한 번 읽고 재사용한다.

`source` 또는 `reference`가 없으면 `material_missing`이다. 기준 PDF가 있으면 `reference`에도 path/SHA를 기록하고, 작성 앱에서 별도로 내보낸 자료임을 `reference_origin: authoring_app_export`로 선언한다. `service_preview` 선언과 편집 형식의 서비스 변환본과 동일한 SHA의 기준 출력은 거부한다. 출처 선언 자체를 암호학적으로 증명하지는 않는다. 원본 형식이 PDF이면 원본 자체와 동일한 기준 출력은 허용된다.

`locator_path`는 reader가 반환한 `block.source_locator.path`이며, 지정 시 그 위치의 문구만 source 대응으로 인정한다. 반복되는 source 문구는 `source_ambiguous`, 반복 PDF 후보는 `repeated_anchor`로 남긴다. 페이지 후보는 기계적 문구 탐색 결과이며 레이아웃 일치 판정이 아니다.

결과는 `report.json`과 `index.html`이다. HTML은 기준/서비스 PDF를 나란히 열며 PDF 내장 표시를 지원하지 않는 브라우저에서는 각 링크를 사용한다. 원본 경로·런타임 경로는 결과에 저장하지 않는다. 생성 환경은 산출물 tool/version/OS/font manifest hash로 기록한다. 원본 및 기준 파일은 변경하지 않는다. 종료 코드 0은 보고서 생성 성공(자료 미확보 포함), 1은 invalid case 존재, 2는 manifest·런타임·출력 실패다.

사람이 페이지들을 검토한 뒤 다음 내용을 manifest의 `layout_review`에 기록한다. 일반 준비 명령은 PDF를 다시 변환하므로 생성 시각 등으로 해시가 달라질 수 있다. 검수 기록에는 아래 전용 명령을 사용한다. 이전 PDF 바이트를 재사용하며 reader·Java·LibreOffice를 호출하지 않는다.

```sh
PYTHONPATH=src .venv/bin/python -m tools.run_compatibility --record-review manifest.json review-output reviewed-output
```

`reviewed-output`도 새 폴더여야 한다. 원본·기준 파일과 이전 보고서의 실제 기준/서비스 PDF를 다시 해시 검증한 뒤 복사한다. 세 해시가 검수 선언과 다르면 `stale_layout_review` 또는 `hash_mismatch`로 거부한다. 이전 report의 case ID 집합, 가족·개발/평가·합성/작성 provenance, 작성 앱·폰트와 기대 문구도 동일해야 한다. 적어도 한 case에 검수 기록을 제공해야 하며, 그 case는 원본·기준 PDF·서비스 PDF가 모두 있어야 한다. 다른 case의 `layout_review`는 null로 두면 이전 자료 미확보·검수 대기 상태와 사용 가능한 PDF를 그대로 보존한다.

```json
{"reviewer":"검토자","source_sha256":"원본 해시","reference_sha256":"기준 해시","preview_sha256":"서비스 PDF 해시","outcome":"matches","notes":"검토한 페이지와 관찰 내용"}
```

차이가 있으면 `outcome: differences`를 사용한다. 검토 기록이 없으면 `review_pending`, 유효한 기록은 `review_recorded`다. 어느 경우에도 도구가 T03C2·S2/S3 또는 실제 자료 수용 완료를 인증하지 않는다. 합성 자료는 회귀 시험 전용이며 실제 작성 자료의 개발/평가 가족을 섞으면 manifest를 거부한다.
