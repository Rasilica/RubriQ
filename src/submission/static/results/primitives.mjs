import {element,button,badge,field,readingElement} from "/review-assets/primitives.mjs";

export function resultRow(view,onSelect) {
  const row=button("",()=>onSelect(view.id));
  row.className="requirement-row result-row";
  row.dataset.requirementId=view.id;
  row.setAttribute("aria-current",String(view.selected));
  const labels=element("div","cluster");
  const status=badge(view.status);status.classList.add(view.tone);labels.append(badge(view.kind),status);
  row.append(element("span","mono",view.id),element("strong","",view.title),labels);
  if(view.attention) row.append(element("span","attention-label","확인 필요"));
  if(view.selected) row.append(element("span","muted","선택됨"));
  return row;
}

export function pageToolbar(model,onPage) {
  const bar=element("div","page-toolbar");
  const previous=button("이전 쪽",()=>onPage(model.page-1));
  previous.id="previous-page"; previous.disabled=model.page <= 1;
  const next=button("다음 쪽",()=>onPage(model.page+1));
  next.id="next-page"; next.disabled=model.page >= model.pageCount;
  const picker=field({id:"page-select",label:"원본 PDF 페이지",value:String(model.page),options:Array.from({length:model.pageCount},(_,index)=>[String(index+1),`${index+1} / ${model.pageCount}쪽`]),onChange:(value)=>onPage(Number(value))});
  bar.append(previous,picker,next);
  return bar;
}

export function notice(message,{error=false,retry}={}) {
  const node=element("div",`notice${error ? " error" : ""} result-notice`);
  node.setAttribute("role",error ? "alert" : "status");
  node.append(readingElement("p","",message));
  if(retry) node.append(button("다시 시도",retry));
  return node;
}
