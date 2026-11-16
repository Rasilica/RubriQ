import {element,field} from "/review-assets/primitives.mjs";
import {createResultsClient,ResultsError} from "./api.mjs";
import {createLatestRequest,resultView,evidenceEntries,initialSelection,selectPage,selectCitation,selectBlock,statCounts} from "./state.mjs";
import {statTile} from "/brand-assets/stats.mjs";
import {resultRow,notice} from "./primitives.mjs";
import {renderDetail} from "./detail.mjs";
import {renderViewer} from "./viewer.mjs";

const client=createResultsClient();
const requests=createLatestRequest();
const find=(selector)=>document.querySelector(selector);
let data=null;
let selectedId=null;
let selection=initialSelection();
let requestedCase=null;

function showMessage(message,options) {
  find("#result-message").replaceChildren(notice(message,options));
}

function currentItem() {return data.check.items.find((item)=>item.semantic.requirement_id === selectedId);}

function renderSource(focus) {
  find("#result-viewer").replaceChildren(renderViewer(data.documents,selection,{
    onRole:(role)=>{selection=selectPage(selection,data.documents,{role,page:selection.pages[role]});renderSource("#source-role");},
    onEvidence:showEvidence,
    onBlock:(blockId)=>{selection=selectBlock(selection,data.documents,blockId);renderSource("#block-select");},
    onPage:(page)=>{selection=selectPage(selection,data.documents,{role:selection.role,page});renderSource("#page-select");},
  },data.structure_scenarios ?? []));
  if(focus) find(focus)?.focus({preventScroll:true});
}

function showEvidence(entry) {
  const next=selectCitation(selection,data.documents,entry);
  if(next === selection) {showMessage("인용 위치를 원본과 연결하지 못했습니다.",{error:true});return;}
  selection=next;
  renderSource("#viewer-heading");
  find("#readable-evidence mark")?.scrollIntoView({block:"center",behavior:"instant"});
}

function render() {
  const list=find("#result-list");
  list.replaceChildren(element("p","muted",`전체 ${data.check.items.length}항목`));
  for(const item of data.check.items) list.append(resultRow(resultView(item,selectedId),selectItem));
  const detail=find("#result-detail");
  const picker=field({id:"result-select",label:"확인할 검사 항목",value:selectedId ?? "",options:data.check.items.map((item)=>[item.semantic.requirement_id,`${item.semantic.requirement_id} ${item.semantic.criterion.title}`]),onChange:selectItem});
  picker.classList.add("result-picker");
  detail.replaceChildren(picker);
  const item=currentItem();
  detail.append(item ? renderDetail(item,showEvidence) : notice("표시할 검사 항목이 없습니다."));
  renderSource();
  for(const id of ["result-list","result-detail","result-viewer"]) find(`#${id}`).hidden=false;
}


function renderStats() {
  const counts=statCounts(data.check.items);
  find("#result-stats").replaceChildren(
    statTile("critical","확인 필요",counts.attention,"원문과 직접 대조할 항목"),
    statTile("default","근거 확인",counts.found,"보고서에서 근거를 찾은 항목"),
    statTile("default","근거 미확인",counts.missing,"근거를 찾지 못했거나 미충족"),
    statTile("attention","판정 보류",counts.deferred,"규칙 확인이 더 필요한 항목"),
  );
}

function selectItem(id) {
  selectedId=id;
  selection=initialSelection();
  const entries=evidenceEntries(currentItem());
  const first=entries.find((entry)=>entry.role === "report") ?? entries[0];
  if(first) selection=selectCitation(selection,data.documents,first);
  render();
  find("#result-detail").scrollTop=0;
  if(matchMedia("(max-width:1099px)").matches) find("#result-select").focus({preventScroll:true});
  else find(`[data-requirement-id="${CSS.escape(id)}"]`).focus({preventScroll:true});
}

async function loadCase(id) {
  requestedCase=id;
  find("#result-workspace").setAttribute("aria-busy","true");
  showMessage(data ? "새 예제를 불러오고 있습니다. 아래에는 이전 예제 결과가 표시됩니다." : "예제 결과와 원본 문서를 불러오고 있습니다.");
  const result=await requests.run(()=>client.detail(id));
  if(result.status === "stale") return;
  find("#result-workspace").setAttribute("aria-busy","false");
  if(result.status === "error") {
    const message=result.error instanceof ResultsError ? result.error.message : "결과를 표시하지 못했습니다. 다시 시도해주세요.";
    showMessage(`${message}${data ? " 아래는 이전 예제 결과입니다." : ""}`,{error:true,retry:()=>loadCase(requestedCase)});
    return;
  }
  data=result.data;
  selectedId=data.check.items[0]?.semantic.requirement_id ?? null;
  selection=initialSelection();
  find("#case-title").textContent=data.label;
  find("#case-description").textContent=data.description;
  find("#criteria-version").textContent=`준비된 예제 기준 v${data.check.semantic.criteria_version} · 의미 정확도 미검증`;
  find("#result-message").replaceChildren();
  render();
  renderStats();
}

async function start() {
  showMessage("고정 예제 목록을 불러오고 있습니다.");
  try {
    const index=await client.list();
    if(!index.cases.length) {
      data=null;selectedId=null;requestedCase=null;selection=initialSelection();
      find("#case-picker").replaceChildren();find("#result-stats").replaceChildren();
      find("#case-title").textContent="준비된 예제 없음";
      find("#case-description").textContent="";find("#criteria-version").textContent="";
      for(const id of ["result-list","result-detail","result-viewer"]) {find(`#${id}`).replaceChildren();find(`#${id}`).hidden=true;}
      find("#result-workspace").setAttribute("aria-busy","false");
      showMessage("현재 준비된 예제가 없습니다.",{retry:start});
      return;
    }
    const picker=field({id:"case-select",label:"확인할 문서 예제",value:index.cases[0].case_id,options:index.cases.map((entry)=>[entry.case_id,entry.label]),onChange:loadCase});
    find("#case-picker").replaceChildren(picker);
    await loadCase(index.cases[0].case_id);
  } catch(error) {showMessage(error instanceof ResultsError ? error.message : "예제 목록을 표시하지 못했습니다.",{error:true,retry:start});}
}

start();
