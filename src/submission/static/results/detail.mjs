import {element,badge,button,readingElement} from "/review-assets/primitives.mjs";
import {resultView,JUDGMENTS,ROLES,evidenceEntries,pageSummary} from "./state.mjs";

function definition(values) {
  const list=element("dl","result-definition");
  for(const [label,value] of values) list.append(element("dt","",label),readingElement("dd","",value));
  return list;
}

function mechanicalFinding(rule) {
  const summary=pageSummary(rule);
  const panel=element("section","stack result-section");
  panel.id="page-rule-result";
  panel.append(element("h3","","PDF 분량 · 기계 검증"));
  panel.append(definition([["검증된 페이지 수",summary.count === null ? "미확정" : `${summary.count}쪽`],["허용 상한",summary.maximum === null ? "미확인" : `${summary.maximum}쪽`],["포함 범위",summary.scopeVerified ? "원본 PDF 전체 페이지 확인" : "전체 페이지 포함 범위 미확정"]]));
  const status={compliant:"확인한 전체 페이지가 상한 이내입니다.",noncompliant:"확인한 전체 페이지가 상한을 초과합니다.",deferred:"포함 범위 또는 계산 근거가 미확정이어서 판정을 보류합니다.",not_applicable:"이 분량 규칙은 적용 대상이 아닙니다."};
  panel.append(readingElement("p","",status[summary.status]));
  return panel;
}

function childFindings(item) {
  const section=element("section","stack result-section");
  section.append(element("h3","","하위조건별 확인"));
  for(const child of item.semantic.subconditions) {
    const criterion=item.semantic.criterion.subconditions.find((entry)=>entry.subcondition_id === child.subcondition_id);
    const row=element("div","stack");
    row.dataset.subconditionId=child.subcondition_id;
    row.append(element("strong","",criterion?.description ?? child.subcondition_id),element("p","muted",`의미 판정: ${JUDGMENTS[child.judgment]}`));
    if(child.proposed_judgment !== child.judgment) row.append(element("p","muted",`제안된 의미 판정: ${JUDGMENTS[child.proposed_judgment]}`));
    row.append(readingElement("p","",child.reason));
    const scope=item.page_rule?.scope_subconditions.find((entry)=>entry.subcondition_id === child.subcondition_id);
    if(scope) row.append(element("p","",`페이지 범위 기계 검증: ${scope.status === "verified" ? "전체 페이지 확인" : scope.status === "deferred" ? "판정 보류" : "적용 대상 아님"}`));
    section.append(row);
  }
  return section;
}

function evidenceActions(item,onEvidence) {
  const section=element("section","stack result-section");
  section.append(element("h3","","원문 근거로 이동"));
  const entries=evidenceEntries(item);
  for(const [index,entry] of entries.entries()) {
    const control=button("",()=>onEvidence(entry));
    control.classList.add("evidence-action");
    control.dataset.evidenceRole=entry.role;control.dataset.evidenceIndex=index;
    control.append(element("strong","",`${ROLES[entry.role]} · ${entry.citation.source_locator.original_page_number === null ? "원본 구조 · 페이지 미확인" : `원본 ${entry.citation.source_locator.original_page_number}쪽`}`),readingElement("p","original-text",entry.citation.quote));
    section.append(control);
  }
  if(!entries.some((entry)=>entry.role === "report")) section.append(element("p","muted","보고서에서 연결된 내용 근거가 없습니다. 근거 부재만으로 모든 내용을 판정하지 않습니다."));
  return section;
}

export function renderDetail(item,onEvidence) {
  const view=resultView(item,item.semantic.requirement_id);
  const panel=element("article","panel stack");
  const heading=element("div","cluster");
  const status=badge(view.status);status.classList.add(view.tone);heading.append(badge(view.id),badge(view.kind),status);
  panel.append(heading,element("h2","",view.title));
  if(view.attention) panel.append(element("p","attention-label","확인 필요"));
  if(item.semantic.applicability === "not_applicable") panel.append(readingElement("p","",item.semantic.criterion.application_reason ?? item.semantic.criterion.exclusion_reason ?? "적용 대상이 아닌 기준입니다."));
  else {
    if(item.page_rule) panel.append(mechanicalFinding(item.page_rule));
    const semantic=element("section","stack result-section");
    semantic.append(element("h3","","보존된 의미 판정"),definition([["제안된 판정",JUDGMENTS[item.semantic.proposed_judgment] ?? "없음"],["정책 적용 후",JUDGMENTS[item.semantic.judgment] ?? "없음"]]),readingElement("p","",item.semantic.reason ?? "의미 판정 없음"),element("p","muted","고정 응답의 의미 정확도는 검증되지 않았습니다. 인용 위치와 실제 문장을 함께 확인하세요."));
    panel.append(semantic);
    if(item.semantic.subconditions.length) panel.append(childFindings(item));
  }
  const original=element("details");
  original.append(element("summary","","원래 안내문 초안과 예제 기준"),readingElement("p","",`원래 초안: ${item.semantic.original_requirement.title}`),readingElement("p","",`예제 확정 기준: ${item.semantic.criterion.title}`));
  if(item.semantic.criterion.condition_description) original.append(readingElement("p","",`적용 조건: ${item.semantic.criterion.condition_description}`));
  panel.append(original,evidenceActions(item,onEvidence));
  return panel;
}
