import {element,badge,readingElement} from "/review-assets/primitives.mjs";
import {resultRow,pageToolbar,notice} from "./primitives.mjs";

const grid=element("div","results-showcase-grid");
const list=element("section","panel stack");
list.append(element("h2","","결과 행"));
for(const view of [
  {id:"R1",title:"문제와 대상 사용자",kind:"필수",status:"근거 확인",selected:true,attention:false},
  {id:"R3",title:"선택 사항은 경고 없이 표시합니다",kind:"선택",status:"근거 미확인",selected:false,attention:false},
  {id:"R5",title:"분량과 전체 페이지 범위",kind:"필수",status:"판정 보류",selected:false,attention:true},
]) list.append(resultRow(view,()=>{}));
const detail=element("section","panel stack");
detail.append(element("h2","","근거와 범위"),badge("기계 검증"),element("p","","전체 PDF 2쪽 / 최대 2쪽"),readingElement("p","muted","이 컴포넌트는 상태 표현 예시입니다. 실제 문서 근거는 결과 화면에서 불러옵니다."));
detail.append(notice("전체 페이지 범위가 확인되지 않아 판정을 보류합니다."));
const viewer=element("section","panel paper stack");
viewer.append(element("h2","","원본 PDF"),pageToolbar({page:1,pageCount:2},()=>{}),notice("원본 페이지를 불러오고 있습니다."),notice("페이지 이미지를 불러오지 못했습니다. 읽기용 추출문은 계속 확인할 수 있습니다.",{error:true,retry:()=>{}}));
viewer.append(element("h3","","읽기용 추출문"),readingElement("p","original-text","원문과 다른 시각 자료를 넣지 않습니다. 실제 페이지를 선택하면 해당 문서의 이미지와 추출문을 표시합니다."));
grid.append(list,detail,viewer);
document.querySelector("#showcase").append(grid);
