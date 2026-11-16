import {element,button,badge,field,setReadingText} from "./primitives.mjs";
import {KIND_LABELS,allCitations} from "./state.mjs";

function originalComparison(original) {
  const details = element("details");
  details.append(element("summary","","원래 초안과 비교"));
  const body = element("div","original-summary");
  body.append(element("strong","",original.title),element("p","",`원래 구분: ${KIND_LABELS[original.classification]}`));
  for(const sub of original.subconditions) body.append(element("p","",sub.description));
  if(original.condition) body.append(element("p","",`원래 적용 조건: ${original.condition.description}`));
  details.append(body);
  return details;
}

function conditionFields(item,change) {
  const group = element("div","stack section-divider");
  group.append(element("h3","","조건 적용 확인"));
  group.append(field({id:"condition-description",label:"적용 조건",value:item.condition_description ?? "",multiline:true,required:true,
    help:"조건 내용을 바꾸면 적용 확인이 초기화됩니다. 먼저 저장한 뒤 적용 여부를 다시 확인하세요.",
    onChange:(value)=>change({condition_description:value},"condition") }));
  group.append(field({id:"application-status",label:"조건 적용 여부",value:item.application_status,
    options:[["undetermined","아직 확인하지 않음"],["applies","이 보고서에 적용"],["does_not_apply","이 보고서에 적용하지 않음"]],
    onChange:(value)=>change({application_status:value,...(value === "undetermined" ? {application_reason:null} : {})},"application") }));
  group.append(field({id:"application-reason",label:"적용 확인 사유",value:item.application_reason ?? "",multiline:true,
    required:item.application_status !== "undetermined",
    help:"적용하거나 적용하지 않는 이유를 적어주세요. 보고서 내용의 충족 여부를 판정하는 단계는 아닙니다.",
    onChange:(value)=>change({application_reason:value || null}) }));
  return group;
}

export function renderEditor({session,items,selectedId,busy,onSelect,onChange,onQuote}) {
  const item = items.find((entry)=>entry.requirement_id === selectedId);
  const original = session.original_draft.requirements.find((entry)=>entry.requirement_id === selectedId);
  const wrapper = element("div");
  const picker = field({id:"requirement-select",label:"확인할 요구사항",value:selectedId,
    options:items.map((entry)=>[entry.requirement_id,`${entry.requirement_id} ${entry.title}`]),onChange:onSelect});
  picker.classList.add("mobile-picker");
  wrapper.append(picker);
  if(!item || !original) {
    wrapper.append(element("p","notice","확인할 요구사항이 없습니다."));
    return wrapper;
  }
  const panel = element("div","panel stack");
  const header = element("div","cluster editor-title");
  header.append(badge(item.requirement_id),element("h2","grow",item.title),badge(item.included ? KIND_LABELS[item.classification] : "제외됨"));
  panel.append(header,originalComparison(original));
  if(item.edited_fields?.length) panel.append(element("p","muted",`저장된 수정 항목: ${item.edited_fields.map((key)=>({title:"제목",classification:"구분",condition_description:"적용 조건",subconditions:"하위조건",included:"포함 여부",exclusion_reason:"제외 사유",application_status:"적용 여부",application_reason:"적용 사유"}[key] ?? key)).join(", ")}`));
  const form = element("form","editor-form");
  form.id="review-form";
  form.addEventListener("submit",(event)=>event.preventDefault());
  const fields = element("fieldset");
  fields.disabled=busy;
  const change=(patch,mode)=>onChange(item.requirement_id,patch,mode);
  fields.append(field({id:"edit-title",label:"요구사항 제목",value:item.title,required:true,onChange:(value)=>change({title:value})}));
  fields.append(field({id:"edit-classification",label:"구분",value:item.classification,
    options:Object.entries(KIND_LABELS),onChange:(value)=>change({classification:value},"classification")}));
  for(const [index,sub] of item.subconditions.entries()) fields.append(field({
    id:`subcondition-${sub.subcondition_id}`,label:`하위조건 ${index+1}`,value:sub.description,multiline:true,required:true,
    onChange:(value)=>change({subcondition_id:sub.subcondition_id,description:value},"subcondition"),
  }));
  if(item.classification === "conditional") fields.append(conditionFields(item,change));
  const inclusion=element("div","stack section-divider");
  inclusion.append(element("h3","","기준에 포함할 항목"));
  inclusion.append(element("p","muted",item.included ? "이 항목은 확정할 검사 기준에 포함됩니다." : "제외된 항목도 원래 초안과 제외 사유를 보존합니다."));
  const toggle=button(item.included ? "기준에서 제외" : "기준에 다시 포함",()=>change({included:!item.included,exclusion_reason:null},"inclusion"));
  toggle.id="include-item";
  inclusion.append(toggle);
  if(!item.included) inclusion.append(field({id:"exclusion-reason",label:"제외 사유",value:item.exclusion_reason ?? "",multiline:true,required:true,onChange:(value)=>change({exclusion_reason:value || null})}));
  fields.append(inclusion);
  form.append(fields);
  panel.append(form);
  const quotes=element("div","stack section-divider");
  quotes.append(element("h3","","근거가 된 안내문"));
  const list=element("div","citation-list");
  for(const [index,cite] of allCitations(original).entries()) {
    const control=button("",()=>onQuote(index));
    setReadingText(control,`원문 ${index+1}: ${cite.quote}`);
    control.classList.add("quote-button"); control.dataset.citationIndex=index;
    list.append(control);
  }
  quotes.append(list); panel.append(quotes); wrapper.append(panel);
  return wrapper;
}
