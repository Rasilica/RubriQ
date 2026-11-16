<p align="center">
  <img src="src/submission/static/brand/rubriq-mark.svg" width="64" height="64" alt="RubriQ 로고">
</p>

# RubriQ

**안내문과 보고서를 비교하고, 판단의 근거를 원문과 실제 PDF에서 확인하는 로컬 오픈소스 도구입니다.**

AI가 안내문에서 요구사항 후보를 추출하면 사용자가 먼저 확인·수정·확정합니다. 그 기준으로 보고서를 검사하고 항목별 판단, 이유, 원문 인용을 검토합니다. 확인된 문구만 PDF 페이지로 연결하며, 문서와 당시 결과를 명시적으로 저장해 다시 열 수 있습니다.

RubriQ는 채점기나 AI 작성 여부 탐지기가 아닙니다. 원문 인용의 일치와 AI 판단의 의미적 정확성은 별개이며, 최종 수정·제출 결정은 사용자가 합니다.

## 주요 기능

- PDF·DOCX·HWP·HWPX 입력과 원문 구조 확인. 읽기와 PDF 변환 상태를 나눠 부분 성공도 표시합니다.
- 안내문 요구사항 추출 → 사용자 수정·확정 → 보고서 AI 검사.
- 원문 해시·블록·문자 범위 검증과 실제 PDF 문구 대응. 중복·미발견·불일치를 구분하며 추정 위치를 만들지 않습니다.
- 명시적 문서 보관, 목록·삭제, 서버 재시작 후 저장한 기준·결과 재열기.
- Gemini, OpenAI(GPT), Anthropic(Claude), 빌링AI, 로컬 Ollama 연결.
- 선택 문구 윤문과 일부 공개 규칙을 활용한 한국어 표현 점검.

## 빠르게 실행하기

Python **3.13 이상**과 [uv](https://docs.astral.sh/uv/)가 필요합니다. 저장소를 내려받은 폴더에서 실행합니다.

```sh
uv sync --frozen --no-dev
uv run --no-dev uvicorn submission.main:app --app-dir src --host 127.0.0.1 --port 8027
```

[http://127.0.0.1:8027/prepare](http://127.0.0.1:8027/prepare)에서 안내문·보고서를 준비합니다. 소개 페이지는 `/`, 고정 합성 예제는 `/results`, API 명세는 `/docs`에 있습니다. 같은 출처의 주소로 접속하며 서버는 `127.0.0.1`에만 바인딩합니다.

처음에는 `samples/pdf/guide.pdf`와 `samples/pdf/normal.pdf`로 확인할 수 있습니다. 이 자료는 실제 제출물이 아닌 합성 개발 자료입니다. 서버 시작이나 업로드만으로 AI를 호출하지 않습니다. AI 기능 없이 PDF 읽기·원문 확인·보관을 먼저 사용할 수 있습니다.

기본 실행에는 외부 문서 변환기가 설정돼 있지 않습니다. 원본 PDF의 텍스트 읽기와 PDF 제공은 가능하지만 **페이지 이미지에는 Poppler 설정이 필요**합니다. DOCX·HWPX 구조는 읽을 수 있으며, PDF 변환이나 HWP 읽기는 아래의 추가 설정이 필요합니다.

## 문서 형식과 추가 실행 도구

| 기능 | 추가 요구사항 |
|---|---|
| PDF 읽기·원본 PDF 제공 | Python 의존성만 필요. 이미지 기반 PDF의 OCR은 제공하지 않음 |
| PDF 페이지 이미지 | Poppler의 `pdftoppm` 경로 설정 |
| DOCX 원문 구조 읽기 | Python 의존성만 필요 |
| DOCX 확인용 PDF | 별도 설치한 LibreOffice와 `docx` 런타임 설정 |
| HWPX 원문 구조 읽기 | Python 의존성만 필요 |
| HWP 원문 구조 읽기 | 별도 JDK17, 포함된 hwplib, `HwpNestedReader.java`의 해시를 고정한 `hwp` 설정 |
| HWP·HWPX 확인용 PDF | 별도 LibreOffice·JDK17·H2Orestart 0.7.14와 봉인한 전용 프로필 설정 |

공개 저장소에는 Java·LibreOffice·H2Orestart 실행 환경이나 모델 가중치를 포함하지 않습니다. 각 도구를 신뢰할 수 있는 배포처에서 설치하고 해당 라이선스를 확인하세요. JDK17은 현재 보안 패치를 적용한 버전을 사용하고, 전역 Java 설정 대신 프로젝트 전용 경로를 지정합니다.

`DOCUMENT_PAIR_RUNTIME_FILE`은 로컬 JSON 설정 파일 경로입니다. 설정은 [PairRuntime](src/submission/pair_contracts.py)의 `pdftoppm`, `docx`, `hwp`, `hancom` 항목을 사용합니다. 예를 들어 Poppler만 연결하는 설정은 다음과 같습니다. 경로는 자신의 설치 위치로 바꿉니다.

```json
{
  "pdftoppm": "/absolute/path/to/pdftoppm"
}
```

```sh
DOCUMENT_PAIR_RUNTIME_FILE=.runtime/pair-runtime.json \
  uv run --no-dev uvicorn submission.main:app --app-dir src --host 127.0.0.1 --port 8027
```

DOCX 변환 설정은 [ConversionConfig](src/submission/conversion_contracts.py)의 `soffice`와 `work_root`를 사용합니다. HWP reader는 [provision_hwp_reader](src/submission/hwp_reading.py), 한컴 변환 프로필은 [seal_profile](src/submission/hancom_profile.py)로 파일 해시를 고정합니다. `seal_profile`은 이미 준비한 전용 프로필을 검증·봉인하며 확장을 설치하지 않습니다. 프로그램·확장·프로필이 바뀌면 재봉인과 재검증이 필요합니다. 다른 사람의 로컬 설정이나 사용 중인 일반 LibreOffice 프로필을 복사하지 마세요.

**현재 설치형 HWP 경로는 macOS 중심입니다.** POSIX 실행과 macOS Java 라이브러리 경로를 사용하므로 Windows·Linux에서 같은 구성이 동작한다고 보장하지 않습니다. PDF·DOCX·HWP·HWPX 입력 경로가 있다는 뜻과 모든 작성 앱·버전·폰트의 호환성이 검증됐다는 뜻은 다릅니다. 변환 PDF는 원본의 페이지 수나 레이아웃을 보증하지 않습니다.

## AI 연결과 데이터 전송

`/prepare`에서 제공자와 자신의 계정에서 사용할 수 있는 모델 ID를 선택합니다. API 키는 설정 화면에서 등록하거나 일회성으로 입력합니다. **키를 소스 코드·환경 설정 예제·GitHub에 넣지 마세요.**

| 경로 | 키와 실행 환경 | 문서 전송 |
|---|---|---|
| Gemini · OpenAI · Anthropic | 각 제공자의 API 키와 모델 권한 | 동의한 텍스트와 분석 지시문을 해당 제공자로 전송 |
| 빌링AI | 빌링AI 키와 해당 계정의 모델 ID | 빌링AI 게이트웨이로 전송. 직접 제공자 연결과 별도 경로 |
| Ollama | 사용자가 설치한 로컬 서비스와 모델, 키 불필요 | 고정 로컬 주소 `127.0.0.1:11434`로 요청 |

요구사항 추출과 보고서 검사는 각각 전송 범위를 확인하고 실행에 동의해야 합니다. 자동 실행·자동 재시도·제공자 자동 전환은 하지 않습니다. 클라우드 호출에는 비용이 발생할 수 있으며 로컬에서 앱을 실행해도 클라우드 AI를 선택하면 외부 전송입니다. 취소가 이미 시작된 추론이나 비용을 취소한다고 보장하지 않습니다.

저장한 키는 macOS Keychain, Windows Credential Manager, Linux Secret Service용 구현을 사용합니다. 브라우저에는 키가 아닌 등록 여부만 반환하고, 보안 저장소를 사용할 수 없으면 평문 파일로 대체하지 않습니다. macOS에서의 실제 보관·재사용 검증과 다른 OS의 실기기 검증 범위는 구분해야 합니다. Linux에는 사용 가능한 사용자 D-Bus와 잠금 해제된 Secret Service가 필요합니다.

Ollama는 RubriQ가 설치하거나 모델을 내려받지 않습니다. 별도로 설치한 로컬 모델을 준비한 뒤 실행합니다.

```sh
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 ollama serve
```

모델의 라이선스·메모리 요구사항·생성 품질은 별도로 확인하세요. 모델 출력은 원문 일치 검증을 통과하더라도 사람이 의미를 검토해야 합니다.

자세한 사용법: [AI 키 설정](docs/AI_SETTINGS.md) · [요구사항 확인 후 검사](docs/SEMANTIC_AI.md) · [클라우드 AI](docs/CLOUD_AI.md) · [빌링AI](docs/BILLING_AI.md) · [로컬 Ollama](docs/LOCAL_AI.md) · [표현 점검](docs/EXPRESSION_CHECK.md).

## 저장과 주요 제한

자동 영구 저장은 하지 않습니다. 사용자가 **문서 보관하기**를 누르면 원본 바이트·읽은 구조·PDF·경고·확정 기준과 현재 유효한 검사 결과를 로컬 SQLite에 보관합니다. 저장본 재열기에서는 AI 재호출이나 자동 변환 없이 당시 자료를 검증해 복원합니다.

기본 DB는 `.runtime/library/documents.sqlite3`이며 `DOCUMENT_LIBRARY_FILE`로 별도 경로를 지정할 수 있습니다. 저장 문서에는 민감한 원문이 들어갈 수 있습니다. `.runtime/`, DB 파일, 설정, 백업과 실제 업로드 문서는 공개 저장소에 포함하지 마세요. 키는 문서 DB와 별도의 운영체제 저장소에 있습니다.

| 항목 | 기본 한도 |
|---|---|
| 업로드 | 파일당 10 MiB, PDF 50쪽 |
| 문서 준비 | 동시 1건, 전체 180초 |
| 임시 문서 | 30분, 최대 4쌍, 합계 256 MiB |
| 영구 보관 | 스냅샷당 256 MiB, 전체 payload 1 GiB, 최대 100개 |
| 요구사항 추출 | 최대 20,000자·200블록 |
| 보고서 AI 검사 | 안내문·보고서·요구사항·수정 기준 합계 최대 60,000자, 원문 500블록 |

읽지 못한 영역·변환 실패·폰트와 레이아웃 미확인은 경고로 확인합니다. 읽은 범위에서 근거가 없다는 결과가 문서 전체의 누락을 증명하지는 않습니다. 암호화·보호·손상·한도 초과·지원하지 않는 활성 콘텐츠는 거절될 수 있습니다.

로그인 없는 로컬 단일 사용자용입니다. 인터넷 공개 서버나 여러 사용자용 서비스로 배포하기 위한 인증·운영 구성을 제공하지 않습니다.

## 개발과 검사

```sh
uv sync --frozen
uv run python -m pytest -q --cov=submission --cov-branch --cov-report=term-missing
uv run ruff check src tests tools
uv run ruff format --check src tests tools
uv run basedpyright
node --test tests/frontend/*.test.mjs
```

프론트 테스트에는 Node.js가 필요합니다. 별도 프론트 빌드나 npm 의존성 설치는 하지 않습니다. 설치형 Java·변환기 통합 시험에는 대응하는 로컬 런타임이 필요하며, 기본 Python 환경만의 시험과 구분합니다. 합성 자료·시험용 공급사 응답은 실제 AI 품질·계정 권한·과금·작성 앱 호환성의 증거가 아닙니다.

네이티브 HWP 시험에는 별도로 설치한 JDK17의 `JAVA_HOME`을 지정합니다. JDK나 LibreOffice가 없으면 해당 설치형 시험만 건너뛰며, 설치돼 있지만 변환이 실패하면 시험도 실패합니다.

[합성 샘플 설명](samples/README.md)과 [문서 호환성 검토 도구](docs/COMPATIBILITY_TOOL.md)를 참고하세요. 호환성 평가의 기준 PDF는 작성 앱의 독립 출력으로 준비하며 서비스 변환본을 정답으로 재사용하지 않습니다.

## 저장소 구성

```text
src/submission/     FastAPI 서버, 문서 처리·AI·보관, 정적 웹 화면
tests/             Python 회귀 시험과 Node 프론트 시험
tools/             합성 자료 생성기, 로컬 검증 도구, Java HWP worker
samples/           공개 가능한 합성 개발 자료
docs/              기능별 사용법과 계약 설명
vendor/            재배포 고지와 함께 포함한 제삼자 자료
```

실제 안내문·참가 신청서·제출 보고서, 개인 문서의 화면 사진, 실행 로그, API 응답 원문, 문서 DB, 사용자 런타임과 API 키는 공개 소스의 일부가 아닙니다.

유지보수자가 공개용 사본을 만들 때에는 [GitHub 공개 절차](docs/PUBLISHING.md)와 `tools/public-files.txt`를 사용합니다. 원래 작업 폴더 전체를 업로드하지 마세요.

## 라이선스

RubriQ 자체 코드는 **Apache License 2.0**으로 공개합니다. [LICENSE](LICENSE)와 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하세요.

포함된 im-not-ai 자료는 MIT, hwplib는 Apache-2.0 등 각자의 라이선스를 유지합니다. Java·LibreOffice·H2Orestart·모델·폰트·사용자 문서는 RubriQ의 라이선스로 재허가되지 않습니다. 실행 환경을 묶은 설치 파일이나 컨테이너를 배포할 때에는 실제로 포함되는 구성 요소의 고지·소스 제공·재배포 조건을 별도로 확인해야 합니다.
