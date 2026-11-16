import {createReviewClient,ReviewError} from "./api.mjs";
import {element,button,badge,setReadingText} from "./primitives.mjs";
import {requestDiscard} from "./dialog.mjs";
import {editableItems,updateItem,updateSubcondition,hasChanges,confirmationBlocker,KIND_LABELS} from "./state.mjs";
import {renderEditor} from "./editor.mjs";
import {renderSource} from "./source.mjs";

const client=createReviewClient();
let session=null;
let items=[];
let selectedId=null;
let citationIndex=0;
let busy=false;
const find=(selector)=>document.querySelector(selector);
const BLOCKER_TEXT={busy:"요청을 처리하고 있습니다.",unsaved:"변경사항을 먼저 저장하면 기준을 확정할 수 있습니다.",empty:"한 개 이상의 요구사항을 포함해주세요.",undetermined:"포함한 조건부 항목의 적용 여부와 사유를 확인해주세요.",confirmed:"현재 저장본은 확정되었습니다. 수정 후 새 기준을 확정하세요."};

function isDirty() { return session ? hasChanges(session.items,items) : false; }

function updateStatus() {
  if(!session) return;
  const dirty=isDirty();
  const blocker=confirmationBlocker({...session,items,dirty,busy});
  find("#revision-status").textContent=dirty ? `저장 전 변경사항 / 저장본 ${session.revision}` : session.confirmed_revision === session.revision ? `현재 기준 확정됨 / 저장본 ${session.revision}` : `저장본 ${session.revision} / 아직 확정하지 않음`;
  setReadingText(find("#confirmation-help"),BLOCKER_TEXT[blocker] ?? "검사에 사용할 요구사항을 확인했다면 기준을 확정하세요.");
  find("#save-review").disabled=busy || !dirty;
  find("#confirm-review").disabled=blocker !== null;
  find("#save-review").textContent=busy ? "처리 중" : "변경사항 저장";
}

function renderNav() {
  const nav=find("#requirement-nav");
  const heading=element("p","muted nav-heading",`요구사항 ${items.length}개`);
  nav.replaceChildren(heading);
  for(const item of items) {
    const row=button("",()=>selectItem(item.requirement_id));
    row.className="requirement-row";
    row.dataset.requirementId=item.requirement_id;
    row.setAttribute("aria-current",String(item.requirement_id === selectedId));
    row.append(element("span","mono",item.requirement_id),element("strong","",item.title));
    const states=element("div","cluster");
    states.append(badge(item.included ? KIND_LABELS[item.classification] : "제외됨"));
    if(item.requirement_id === selectedId) states.append(element("span","muted","선택됨"));
    row.append(states); nav.append(row);
  }
}

function render(focusId) {
  if(!session) return;
  find("#welcome").hidden=true;
  find("#workspace").classList.remove("empty-workspace");
  for(const id of ["requirement-nav","editor-pane","source-pane","action-bar"]) find(`#${id}`).hidden=false;
  renderNav();
  find("#editor-pane").replaceChildren(renderEditor({session,items,selectedId,busy,onSelect:selectItem,onChange:changeItem,onQuote:selectQuote}));
  find("#source-pane").replaceChildren(renderSource(session,selectedId,citationIndex));
  syncQuoteButtons(); updateStatus();
  if(focusId) find(focusId)?.focus();
}

function selectItem(id) {
  selectedId=id; citationIndex=0;
  render();
  find("#editor-pane").scrollTop=0;
  if(matchMedia("(max-width:1099px)").matches) find("#requirement-select")?.focus();
  else find(`[data-requirement-id="${CSS.escape(id)}"]`)?.focus();
}

function syncQuoteButtons() {
  for(const control of document.querySelectorAll(".quote-button")) control.setAttribute("aria-pressed",String(Number(control.dataset.citationIndex) === citationIndex));
}

function selectQuote(index) {
  citationIndex=index;
  find("#source-pane").replaceChildren(renderSource(session,selectedId,citationIndex));
  syncQuoteButtons();
  const original=find("#original-document");
  if(matchMedia("(max-width:1099px)").matches) original.scrollIntoView({block:"start",behavior:"instant"});
  original.focus({preventScroll:true});
}

function changeItem(id,patch,mode) {
  if(busy) return;
  if(mode === "subcondition") {
    items=updateSubcondition(items,id,patch.subcondition_id,patch.description);
  } else items=updateItem(items,id,patch);
  if(["classification","application","inclusion"].includes(mode)) {
    render(mode === "classification" ? "#edit-classification" : mode === "application" ? "#application-status" : "#include-item");
  } else {
    if(patch.title !== undefined) {
      find(".editor-title h2").textContent=patch.title;
      find(`[data-requirement-id="${CSS.escape(id)}"] strong`).textContent=patch.title;
      const option=find(`#requirement-select option[value="${CSS.escape(id)}"]`);
      if(option) option.textContent=`${id} ${patch.title}`;
    }
    if(mode === "condition") {
      find("#application-status").value="undetermined";
      find("#application-reason").value="";
      find("#application-reason").required=false;
    }
    updateStatus();
  }
}

function showMessage(text,error=false,code=null) {
  const notice=element("div",`notice${error ? " error" : ""}`);
  notice.setAttribute("role",error ? "alert" : "status");
  notice.append(element("p","grow",text));
  if(error && session) {
    const expired=code === "session_unavailable";
    notice.append(button(expired ? "새 데모 시작" : "저장 상태 다시 불러오기",async()=> {
      if(isDirty() && !await requestDiscard()) return;
      run(()=>expired ? client.start() : client.read(),expired ? "새 데모를 시작했습니다." : "서버의 저장 상태를 불러왔습니다.");
    }));
  }
  find("#message-area").replaceChildren(notice);
}

async function run(operation,successText) {
  busy=true;
  find("#start-demo").disabled=true;
  find("#start-demo").textContent="불러오는 중";
  render();
  showMessage("요청을 처리하고 있습니다.");
  try {
    const next=await operation();
    session=next; items=editableItems(next.items).map((item,index)=>({...item,edited_fields:next.items[index].edited_fields}));
    if(!selectedId || !items.some((item)=>item.requirement_id === selectedId)) selectedId=items[0]?.requirement_id ?? null;
    showMessage(successText);
  } catch(error) {
    const known=error instanceof ReviewError;
    showMessage(known ? error.message : "요청을 처리하지 못했습니다. 입력 내용은 유지됩니다.",true,known ? error.code : null);
  } finally {
    busy=false;
    find("#start-demo").disabled=false;
    find("#start-demo").textContent="데모 시작";
    render();
  }
}

find("#start-demo").addEventListener("click",()=>run(()=>client.start(),"데모 초안을 불러왔습니다. 원문과 함께 확인해주세요."));
find("#save-review").addEventListener("click",()=> {
  if(busy || !session || !find("#review-form")?.reportValidity()) return;
  const body=editableItems(items);
  run(()=>client.save(session.revision,body),"변경사항을 저장했습니다. 조건을 바꿨다면 적용 여부를 다시 확인해주세요.");
});
find("#confirm-review").addEventListener("click",()=> {
  if(!session || confirmationBlocker({...session,items,dirty:isDirty(),busy})) return;
  run(()=>client.confirm(session.revision),"새 검사 기준을 확정했습니다. 이전 확정 기록도 보존됩니다.");
});
window.addEventListener("beforeunload",(event)=> {
  if(isDirty()) { event.preventDefault(); event.returnValue=""; }
});
