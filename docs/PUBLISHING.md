# GitHub 공개용 소스 준비

이 배포는 RubriQ 소스와 합성 샘플이다. 실제 참가 신청서·보고서·사진·실제 AI 응답·문서 DB·API 키·로컬 실행 기록은 포함하지 않는다. 원래 작업 폴더를 통째로 업로드하지 않는다.

## 공개용 폴더 만들기

```sh
uv run python tools/export_public_source.py
```

검토한 경로를 명시한 `tools/public-files.txt`의 파일만 `_release/RubriQ/`와 `_release/RubriQ-source.zip`으로 복사한다. 목록에 없는 새 파일은 자동 포함하지 않는다. 파일 부재·위험한 경로·심볼릭 링크는 오류로 처리하며 원본 자료를 이동하거나 삭제하지 않는다. 기존 공개용 폴더나 ZIP이 있으면 덮어쓰지 않는다. 재생성할 때는 기존 산출물을 먼저 확인하고 별도로 옮긴다.

| 포함 | 제외 |
|---|---|
| 서버·화면 소스, 시험, 합성 샘플, 사용 설명 | 실제 제출 문서·참가 신청서·사용자 문서·개인 사진 |
| 의존성 명세와 잠금 파일 | `.env*`, 키·인증서, SQLite와 백업, 세션·사용자 설정 |
| Apache 2.0 원문, NOTICE, 제삼자 고지 | `.runtime/`, `.omo/`, `_workspace/`, 개발 계획·실행 로그 |
| hwplib JAR 및 고지, im-not-ai·Lucian MIT 고지 | JDK, LibreOffice, H2Orestart 실행 바이너리·설치 프로필, 모델·폰트 |

`samples/`의 PDF·DOCX·HWP·HWPX·PNG는 합성 회귀 자료이므로 남긴다. 실제 문서를 같은 폴더에 넣거나 공개 목록에 추가하지 않는다. 예시 API 키나 인증 토큰처럼 보이는 시험 문자열은 실제 계정 값이 아닌 합성 값이다.

## 업로드 전 확인

1. 공개용 폴더의 README대로 로컬 실행하고 합성 PDF 한 쌍을 준비한다. API 키 입력이나 유료 AI 호출은 필요 없다.
2. `uv sync --frozen` 후 Python 시험과 Node 시험을 실행한다. 네이티브 HWP 시험은 JDK17의 `JAVA_HOME`이 필요하며 미설치 시 해당 시험을 건너뛴다.
3. 공개 목록·ZIP 내용을 확인하고 실제 문서·사진·원문 응답·사용자 경로·비밀정보가 없는지 검토한다. 공개 목록은 비밀정보 탐지기를 대신하지 않는다.
4. GitHub에서 빈 저장소를 만든 뒤 **공개용 폴더 안에서만** 아래 명령을 실행한다. URL은 자신의 저장소로 바꾼다.

```sh
cd _release/RubriQ
git init -b main
git add -- .
git status --short
git commit -m "chore: publish RubriQ source"
git remote add origin https://github.com/YOUR_ACCOUNT/RubriQ.git
git push -u origin main
```

웹 업로드를 사용한다면 공개용 폴더 내부 파일만 선택한다. 제출용 저장소에는 `README.md`, `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`와 `src/`, `samples/`가 최상위에 보여야 한다.

`.gitignore`는 이미 커밋한 파일이나 과거 Git 이력을 지우지 않는다. 이전에 키를 공개했다면 파일 삭제만으로 해결하지 말고 제공자에서 키를 폐기·재발급한 뒤 해당 저장소 이력을 별도로 처리해야 한다. 이 내보내기 도구는 `.git` 자체를 복사하지 않는다.

## 라이선스 범위

자체 소스는 [Apache License 2.0](../LICENSE), 제삼자 자료는 [각 고지](../THIRD_PARTY_NOTICES.md)를 따른다. [Apache 공식 적용 안내](https://www.apache.org/foundation/license-faq.html#Apply-My-Software)와 원문의 조건에 맞춰 LICENSE와 고지를 보존한다. 사용자가 올리는 문서와 외부 API·모델·폰트의 권리를 재허가하지 않는다. 실행 환경을 묶은 설치 프로그램·컨테이너는 이번 소스 공개 범위에 포함하지 않는다.
