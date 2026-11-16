# 입력 경계용 합성 형식 자료

T03B1의 형식 식별·컨테이너 경계·원본 구조 위치 시험에 쓰는 작은 개발 자료다. 작성 앱이 저장한 원본이 아니며, Word·한글·LibreOffice로 열기/렌더링한 자료도 아니다. **정식 reader, 변환, S1/S2/S3 호환성 또는 독립 평가 완료를 증명하지 않는다.** 사람 검수와 독립 평가는 모두 미완료다.

| 파일 | 구조 및 범위 |
|---|---|
| `../pdf/guide.pdf` | 기존 PDF 1.3, 2쪽. 기존 파일을 참조하며 생성·수정하지 않는다. 기존 `before-submit-development-001` 가족과 기존 정답을 유지한다. |
| `boundary.docx` | OOXML Transitional 2006 namespace. 본문 두 문단, 1행 2열 표, 각주 1개와 분리선, 머리말/꼬리말. OPC content types와 root/document relationships로 모든 part를 연결한다. |
| `spine-order.hwpx` | ZIP, `application/hwp+zip`, HCFVersion 5.1.1.0 / xmlVersion 1.5, 2011 head/section/paragraph namespace. `content.hpf`의 OPF namespace는 한컴 예제의 `http://www.idpf.org/2007/opf/`다. spine에는 header, section1, section0 순으로 참조가 있고 본문 구역 순서는 파일명 순서와 반대다. |
| `minimal-5.1.1.0.hwp` | CFB v3, 512바이트 sector·64바이트 mini sector. FileHeader 256바이트, 버전 5.1.1.0, flags=0. DocInfo의 문서 속성 레코드와 BodyText/Section0의 문단 헤더·UTF-16LE 문장·글자모양 위치 레코드가 있다. |
| `encrypted-ooxml.cfb` | CFB v3에 `EncryptionInfo`, `EncryptedPackage` 두 stream 이름과 무해한 placeholder 바이트만 넣은 거부 경계용 fixture. 실제 암호화/복호화 가능한 문서가 아니며 내부 OOXML 하위 형식은 알 수 없다(`format: unknown`, `version: null`). 파일명을 `.docx`로 전달해도 DOCX로 확정할 근거가 없다. |
| `sources/` | 두 ZIP 컨테이너의 작성한 XML 원문. HWPX mimetype 소스의 끝 줄바꿈은 패키징 때 제거한다. |
| `manifest.json` | 생성된 파일과 기존 PDF의 SHA-256·크기·형식·가족·합성 출처·미검수 상태. |
| `truth.json` | 생성기에서 출력하지 않는 AI 보조 작성 위치 정답. XML member/XPath, HWP stream/레코드 바이트 위치, 예상 문장을 기록한다. |
| `cases/hwpx-structure.xml` | T03B3에서 추가한 AI 보조 합성 구역 XML. 한국어·이모지·텍스트/tail·탭/줄바꿈, 중첩 표, 각주·머리말/꼬리말을 포함한다. 전체 작성 문서나 독립 평가 자료가 아니다. |

편집 문서 셋은 모두 `format-boundary-001` 가족이다. 같은 개발자가 만든 관련 자료이므로 독립 자료 세 개로 셀 수 없다. 편집 문서의 `original_page`와 `page_count`는 `null`이다. HWPX 구역 번호, OOXML 용지 설정, HWP 내부 시작 번호를 원본 페이지 정답으로 쓰지 않는다. PDF의 숫자는 파일상 페이지다.

기존 `spine-order.hwpx`는 본문 문단 두 개의 순서 경계만 다룬다. 형식 참조 목록은 축약되어 있고 표·각주·머리말/꼬리말 사례는 없다. HWP5도 스타일/글꼴 매핑·구역 정의·레이아웃 등 완전한 작성 문서에 필요한 레코드를 갖추지 않았다. 따라서 **두 파일은 컨테이너와 레코드 구문을 다루는 부분 fixture**이며 전체 문서 스키마 검증이나 앱 호환성을 주장하지 않는다. HWPX/HWP5의 실제 작성 프로그램 원본과 기준 출력 검증은 후속 작업이다. DOCX 역시 XML/관계 구조만 검사했으며 앱 저장/렌더링 여부는 미검증이다.

API 폴더에서 재생성:

T03B2에서 `boundary.docx`를 내부 `read_docx`로 읽고 정답 문장 7개와 모든 텍스트 span을 실제 XML 노드에 대조했다. 중첩 표·반복/누락 각주·공유 머리말·미연결 내용·추적 변경/텍스트 상자/필드·Unicode/제어 문자 사례는 테스트에서 작은 ZIP을 메모리로 구성해 확인한다. 기존 바이너리·정답·manifest의 해시와 검수/독립 평가/작성 앱/렌더링/전체 reader 보장 상태는 변경하지 않았다. 이 한정된 구조 검증을 작성 앱 호환성이나 S2/S3 완료로 확대하지 않는다.

T03B3의 `read_hwpx`는 기존 파일의 spine 순서를 확인하고, `cases/hwpx-structure.xml`을 테스트 ZIP의 첫 구역에 넣어 물리 XML 순서·문단 조각·중첩 표·내장 story 참조를 검증한다. 각 span은 실제 ZIP XML의 node.text·child.tail·제어 문자에 독립적으로 대조한다. 구역 XML은 한컴의 [RunType 구조](https://github.com/hancom-io/hwpx-owpml-model/blob/1453388472c703a4b299a0834f425cdac16644b9/OWPML/Class/Para/RunType.cpp#L53-L94), [표 셀 구조](https://github.com/hancom-io/hwpx-owpml-model/blob/1453388472c703a4b299a0834f425cdac16644b9/OWPML/Class/Para/tc.cpp#L56-L72), [ctrl 구조](https://github.com/hancom-io/hwpx-owpml-model/blob/1453388472c703a4b299a0834f425cdac16644b9/OWPML/Class/Para/ctrl.cpp#L49-L82), [텍스트 제어 구조](https://github.com/hancom-io/hwpx-owpml-model/blob/1453388472c703a4b299a0834f425cdac16644b9/OWPML/Class/Para/t.cpp#L49-L80)를 참고했다. 스타일·글꼴 등 전체 스키마 필드는 축약했고 작성 앱 저장·열기·렌더링은 미검증이다. 기존 corpus와 같은 개발 자료이며 독립 평가 가족을 추가하지 않는다.

HWPX reader는 알려진 head/core·version·container 메타데이터의 구조와 OPF/DC scalar 메타데이터를 본문에서 제외한다. 외부 namespace나 예상하지 않은 text/tail이 들어오면 해당 member를 위치와 함께 미처리로 표시한다. 정확한 `Preview/PrvText.txt`·`Preview/PrvImage.png`는 미리보기 캐시이므로 원본 텍스트나 표시 artifact로 사용하지 않는다. secPr·미주·필드·그림·수식·hyphen/hypen 등 제한된 프로파일 밖 요소는 진단한다. 구역·story 순서는 인쇄 페이지 순서가 아니며 원본 쪽번호는 null이다.

```sh
.venv/bin/python tools/generate_format_fixtures.py
```

표준 라이브러리만 사용하며 `uv run tools/generate_format_fixtures.py`도 가능하다. ZIP 타임스탬프와 CFB 구조는 고정되어 같은 입력에서 같은 바이트가 나온다. 생성기는 네 바이너리와 `manifest.json`만 갱신한다. `truth.json`은 자동 재생성하지 않으므로 의도적인 내용 변경 시 정답과 해시를 검토해야 한다. 암호화 컨테이너 placeholder는 읽을 문서 내용이 없으므로 위치 정답 대상에 넣지 않는다. 이 거부 사례도 같은 개발 가족이며 작성 앱 원본이나 독립 corpus 자료가 아니다. CFB 생성 함수는 고정 크기의 해당 fixture 전용이며 production writer/parser가 아니다.

확인한 1차 자료(2026-10-06):

- [Microsoft Open XML SDK 문서](https://learn.microsoft.com/en-us/office/open-xml/about-the-open-xml-sdk): ZIP/OPC, content types, relationships 및 본문·각주·머리말 part 구성.
- [한컴 HWPX 포맷 구조](https://tech.hancom.com/hwpxformat/)와 [한컴 Python HWPX 파싱 예제](https://tech.hancom.com/python-hwpx-parsing-1/): mimetype/version.xml, content.hpf의 manifest/spine 및 2011 namespace·문단 구조. 전체 XSD 적합성은 검증하지 않았다.
- [한컴 HWP 5.0 공개 명세 revision 1.2](https://cdn.hancom.com/link/docs/한글문서파일형식_5.0_revision1.2.pdf): 표 3(FileHeader), 표 14(문서 속성의 실제 필드 합 26바이트), 표 58(5.0.3.2 이후 문단 헤더 24바이트), 표 60/61(문자·글자모양) 참조. 5.1.1.0은 fixture의 선언 버전이며 이 명세로 모든 5.1 레코드를 검증했다는 뜻이 아니다.
- [Microsoft CFB header](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/05060311-bfce-4b12-874d-71fd4ce63aea), [MiniFAT](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/c5d235f7-b73c-4ec5-bf8d-5c08306cd023), [directory](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/60fe8611-66c3-496b-b70d-a504c94c9ace): sector·stream·directory 형식.
- [Microsoft EncryptedPackage](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-offcrypto/b60c8b35-2db2-4409-8710-59d88a793f83)와 [EncryptionInfo](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-offcrypto/2895eba1-acb1-4624-9bde-2cdad3fea015): 암호화된 ECMA-376 컨테이너의 stream 이름을 확인했다. 본 placeholder의 바이트는 암호화 명세에 맞춘 payload가 아니다.

본 제품은 한컴의 HWP 문서 파일(.hwp) 공개 문서를 참고하여 개발하였습니다.
