import {element,field,button,readingElement} from "/review-assets/primitives.mjs";
import {notice} from "./primitives.mjs";
import {ROLES,quoteParts,blockChildren} from "./state.mjs";

const KINDS={paragraph:"본문 문단",table_cell:"표 셀",footnote:"각주",header:"머리말",footer:"꼬리말",extraction_block:"추출 블록"};
const STATUS={complete:"완료",partial:"부분 읽기",not_started:"미실행",failed:"실패",unsupported:"지원 범위 밖"};
const DIAGNOSTICS={unsupported_element:"지원하지 않는 요소",unsupported_part:"지원하지 않는 영역",invalid_reference:"참조 미확인",invalid_structure:"구조 오류",empty_content:"읽은 내용 없음",parser_warning:"읽기 경고",extraction_error:"추출 오류",text_unavailable:"텍스트 미확인"};
const MAPPING={ambiguous:"대응 후보가 여러 곳이어서 페이지를 확정할 수 없습니다.",unmapped:"변환 표현과 연결하지 못했습니다. 원본에 내용이 없다는 뜻이 아닙니다.",mismatch:"대응한 표현이 원본 인용과 일치하지 않아 페이지를 확정할 수 없습니다."};

function sourceDetails(document) {
  const details=element("details","stack");
  details.id="structure-coverage";
  details.append(element("summary","","읽은 범위 · 누락 · 경고 확인"),element("p","",`구조 읽기: ${STATUS[document.extraction_status]} · PDF 생성: ${STATUS[document.rendering_status]}`),element("p","","분량 기준: 미확인 · 판정 보류"));
  details.append(element("h3","","처리한 영역"));
  for(const part of document.coverage.processed_parts) details.append(element("p","mono",part));
  details.append(element("h3","",`읽기에서 제외된 위치 ${document.coverage.omitted_locators.length}곳`));
  for(const locator of document.coverage.omitted_locators) details.append(element("p","mono",locator.path));
  details.append(readingElement("p","muted","읽은 범위만 확인했습니다. 제외된 위치나 연결 실패는 원본 내용의 부재를 뜻하지 않습니다."),element("h3","",`경고 ${document.warnings.length}개 · 오류 ${document.typed_errors.length}개`));
  for(const issue of [...document.warnings,...document.typed_errors]) details.append(element("p","",`${DIAGNOSTICS[issue.code] ?? "문서 읽기 진단"}`),element("p","mono",issue.source_locator?.path ?? "문서 전체"));
  details.append(element("h3","",`구조 참조 ${(document.references ?? []).length}개`));
  for(const reference of document.references ?? []) details.append(element("p","",`${KINDS[reference.kind]} · ${reference.status === "resolved" ? "연결됨" : "연결 미확인"}`),element("p","mono",`${reference.source_locator.path} → ${reference.target_locator?.path ?? "대상 미확인"}`));
  details.append(element("p","mono",document.source.filename),element("p","mono",`SHA-256 ${document.source.content_sha256}`));
  return details;
}

function mappingExamples(scenarios,actions) {
  const section=element("section","stack result-section");
  section.id="mapping-scenarios";
  section.append(element("h3","","표시 불확실성 · 합성 대응 예시"),readingElement("p","muted","아래는 상태 설명용 합성 예시입니다. 실제 변환 PDF나 확인된 원본 페이지가 아니며, 위 의미 판정을 바꾸지 않습니다."));
  for(const scenario of scenarios) {
    const status=scenario.result.mapping.mapping_status;
    const item=element("div","stack text-block");
    item.dataset.mappingStatus=status;
    item.append(element("strong","",scenario.label),readingElement("p","",MAPPING[status]));
    item.append(readingElement("p","original-text",scenario.citation.quote),element("p","mono",scenario.citation.source_locator.path),button("원본 구조 인용 보기",()=>actions.onEvidence({role:"report",citation:scenario.citation})));
    item.append(element("p","muted",`합성 대응 후보 ${scenario.result.candidates.length}개 · 실제 PDF 페이지 아님`));
    for(const [index,ranges] of scenario.result.candidates.entries()) {
      const positions=ranges.map((range)=>`합성 페이지 식별자 ${range.page_number}, Unicode [${range.char_range.start}, ${range.char_range.end})`).join(" / ");
      item.append(element("p","mono",`합성 후보 ${index+1}: ${positions}`));
    }
    section.append(item);
  }
  return section;
}

function blockText(block,citation,document,actions) {
  const section=element("section","stack result-section");
  section.id="readable-evidence";
  section.append(element("h3","",`${KINDS[block.kind]} · 원본 페이지 미확인`),element("p","mono",`원본 위치 ${block.source_locator.path}`));
  const parent=document.blocks.find((candidate)=>candidate.block_id === block.parent_block_id);
  if(parent) section.append(element("p","",`포함 영역: ${KINDS[parent.kind]}`));
  if(block.source_fragment_index !== null && block.source_fragment_index !== undefined) section.append(element("p","",`원문 조각 ${block.source_fragment_index}`));
  if(block.raw_char_range) section.append(element("p","mono",`원문 Unicode 범위 [${block.raw_char_range.start}, ${block.raw_char_range.end}) · 끝 위치 제외`));
  if(!block.raw_text) {
    const children=blockChildren(document,block.block_id);
    section.append(readingElement("p","muted",children.length ? "이 위치는 내용을 묶는 구조 영역입니다. 아래 하위 블록에서 원문을 확인하세요." : "이 구조 위치에서 읽은 텍스트가 없습니다. 원본 내용의 부재를 뜻하지 않습니다."));
    for(const [index,child] of children.entries()) section.append(button(`하위 블록 ${index+1} · ${KINDS[child.kind]} 보기`,()=>actions.onBlock(child.block_id)));
  }
  const text=element("p","original-text");text.dataset.blockId=block.block_id;
  if(citation?.block_id === block.block_id) {
    const [before,quote,after]=quoteParts(block.raw_text,citation.char_range);
    text.append(readingElement("span","",before),readingElement("mark","",quote),readingElement("span","",after));
  } else text.append(readingElement("span","",block.raw_text));
  section.append(text);
  return section;
}

export function renderStructure(document,selection,actions,scenarios) {
  const panel=element("section","panel paper stack");
  const heading=element("h2","",`${ROLES[selection.role]} · 원본 구조`);heading.id="viewer-heading";heading.tabIndex=-1;
  panel.append(heading,field({id:"source-role",label:"확인할 원본 문서",value:selection.role,options:Object.entries(ROLES),onChange:actions.onRole}),notice("원본 페이지를 확인하지 못해 분량 판정을 보류합니다. 구조에서 읽은 내용이며 원본 화면 배치와 다를 수 있습니다. 확인용 PDF는 아직 없습니다."));
  const blocks=document.blocks;
  const index=Math.max(0,blocks.findIndex((block)=>block.block_id === selection.blocks[selection.role]));
  if(blocks.length) {
    const bar=element("div","page-toolbar");
    const previous=button("이전 블록",()=>actions.onBlock(blocks[index-1].block_id));previous.disabled=index === 0;previous.id="previous-block";
    const next=button("다음 블록",()=>actions.onBlock(blocks[index+1].block_id));next.disabled=index === blocks.length-1;next.id="next-block";
    bar.append(previous,field({id:"block-select",label:"원본 구조 위치",value:blocks[index].block_id,options:blocks.map((block,i)=>[block.block_id,`${i+1} / ${blocks.length} · ${KINDS[block.kind]}`]),onChange:actions.onBlock}),next);
    panel.append(bar,blockText(blocks[index],selection.citations[selection.role],document,actions));
  } else panel.append(notice("읽을 수 있는 구조 블록이 없습니다. 처리 범위와 경고를 확인하세요."));
  panel.append(sourceDetails(document));
  if(scenarios.length) panel.append(mappingExamples(scenarios,actions));
  return panel;
}
