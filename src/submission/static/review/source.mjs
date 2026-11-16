import {element,badge,readingElement} from "./primitives.mjs";
import {KIND_LABELS,allCitations,quoteSegments} from "./state.mjs";

function historyView(versions) {
  const history=element("details");
  history.id="version-history";
  history.append(element("summary","",`이전 확정 기준 (${versions.length})`));
  if(!versions.length) history.append(element("p","muted","확정한 기준이 아직 없습니다."));
  for(const version of [...versions].reverse()) {
    const entry=element("div","history-version");
    entry.append(element("h3","",`확정 기준 v${version.version}`),element("p","muted",`저장본 ${version.revision}에서 확정한 읽기 전용 기록`));
    for(const item of version.items) {
      const row=element("div","history-item");
      row.append(element("strong","",`${item.requirement_id} ${item.title}`),element("p","",`${KIND_LABELS[item.classification]} / ${item.included ? "포함" : "제외"}`));
      for(const sub of item.subconditions) row.append(element("p","",sub.description));
      if(item.condition_description) row.append(element("p","",`적용 조건: ${item.condition_description}`));
      if(item.classification === "conditional") row.append(element("p","",`적용 확인: ${{applies:"적용",does_not_apply:"적용하지 않음",undetermined:"미확인"}[item.application_status]}`));
      if(item.application_reason) row.append(element("p","",`적용 사유: ${item.application_reason}`));
      if(item.exclusion_reason) row.append(element("p","",`제외 사유: ${item.exclusion_reason}`));
      entry.append(row);
    }
    history.append(entry);
  }
  return history;
}

export function renderSource(session,selectedId,citationIndex) {
  const wrapper=element("div","stack");
  const original=session.original_draft.requirements.find((item)=>item.requirement_id === selectedId);
  const cite=original ? allCitations(original)[citationIndex] : null;
  const block=cite ? session.source_blocks.find((item)=>item.block_id === cite.block_id) : null;
  const paper=element("section","panel paper source-paper stack");
  paper.id="original-document";
  paper.tabIndex=-1;
  const header=element("div","source-head");
  header.append(element("h2","grow","안내문 원문"),badge("읽기 전용"));
  paper.append(header);
  if(cite && block) {
    const page=cite.source_locator.original_page_number;
    paper.append(element("p","muted",page === null ? "원본 위치 확인 / 페이지 미확인" : `원본 PDF ${page}쪽`));
    const text=element("p","original-text");
    const [before,quote,after]=quoteSegments(block.raw_text,cite.char_range);
    text.append(readingElement("span","",before),readingElement("mark","",quote),readingElement("span","",after));
    paper.append(text);
    const metadata=element("details");
    metadata.append(element("summary","","원본 위치 정보"));
    metadata.append(element("p","mono",cite.source_locator.path),element("p","mono",`블록 ${cite.block_id}`),element("p","mono",`문자 ${cite.char_range.start}-${cite.char_range.end}`));
    paper.append(metadata);
  } else paper.append(element("p","muted","요구사항의 원문을 선택하면 이곳에 표시됩니다."));
  wrapper.append(paper,historyView(session.versions));
  return wrapper;
}
