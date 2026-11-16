import {element,field,readingElement} from "/review-assets/primitives.mjs";
import {pageToolbar,notice} from "./primitives.mjs";
import {renderStructure} from "./structure.mjs";
import {ROLES,quoteParts} from "./state.mjs";

function pageImage(page,role) {
  const figure=element("figure","pdf-figure stack");
  const frame=element("div","pdf-frame");
  frame.style.aspectRatio=`${page.width} / ${page.height}`;
  const state=element("div","pdf-state");
  const image=element("img","pdf-image");
  image.id="pdf-page-image";image.width=page.width;image.height=page.height;
  image.alt=`${ROLES[role]} 원본 PDF ${page.page_number}쪽`;
  image.decoding="async";
  let attempt=0;
  const load=()=>{
    image.hidden=true;
    state.replaceChildren(notice("원본 PDF 페이지를 불러오고 있습니다."));
    image.src=page.image_url+(attempt++ ? `?retry=${attempt}` : "");
  };
  image.addEventListener("load",()=>{image.hidden=false;state.replaceChildren();});
  image.addEventListener("error",()=>{image.hidden=true;state.replaceChildren(notice("페이지 이미지를 불러오지 못했습니다. 아래 읽기용 추출문은 계속 확인할 수 있습니다.",{error:true,retry:load}));});
  frame.append(state,image);
  figure.append(frame,readingElement("figcaption","","원본 PDF에서 생성한 페이지 이미지입니다. 인용 표시는 아래 추출문에서 확인하세요."));
  load();
  return figure;
}

function extractedText(document,selection) {
  const section=element("section","stack result-section");
  section.id="readable-evidence";
  section.append(element("h3","","읽기용 추출문"));
  const blocks=document.blocks.filter((block)=>block.source_locator.original_page_number === selection.pages[selection.role]);
  const citation=selection.citations[selection.role];
  for(const block of blocks) {
    const group=element("div","text-block stack");
    const text=element("p","original-text");
    text.dataset.blockId=block.block_id;
    if(citation?.block_id === block.block_id) {
      const [before,quote,after]=quoteParts(block.raw_text,citation.char_range);
      text.append(readingElement("span","",before),readingElement("mark","",quote),readingElement("span","",after));
    } else text.append(readingElement("span","",block.raw_text));
    group.append(text,element("p","mono",`원본 위치 ${block.source_locator.path}`));
    section.append(group);
  }
  if(!blocks.length) section.append(element("p","muted","이 페이지에는 읽을 수 있는 추출문이 없습니다. 원본 PDF를 확인하세요."));
  return section;
}

function documentDetails(document) {
  const details=element("details");
  details.append(element("summary","","추출 범위와 문서 정보"));
  details.append(readingElement("p","",`PDF 텍스트층 ${document.coverage.processed_pages.length} / ${document.coverage.total_pages}쪽을 읽었습니다. 추출문이 원본의 모든 내용을 포함한다고 보장하지 않습니다.`));
  details.append(element("p","",`추출 경고 ${document.warnings.length}개 / 읽기 오류 ${document.typed_errors.length}개`),element("p","mono",document.source.filename),element("p","mono",`SHA-256 ${document.source.content_sha256}`));
  return details;
}

export function renderViewer(documents,selection,actions,scenarios=[]) {
  const document=documents[selection.role];
  if(document.representation === "source_structure") return renderStructure(document,selection,actions,scenarios);
  const page=document.pages.find((entry)=>entry.page_number === selection.pages[selection.role]);
  const panel=element("section","panel paper stack");
  const heading=element("h2","",`${ROLES[selection.role]} · 원본 PDF ${page.page_number} / ${document.page_count}쪽`);
  heading.id="viewer-heading";heading.tabIndex=-1;
  panel.append(heading);
  const toolbar=element("div","viewer-toolbar");
  const picker=field({id:"source-role",label:"확인할 원본 문서",value:selection.role,options:Object.entries(ROLES),onChange:actions.onRole});
  const original=element("a","original-link","원본 PDF 열기");
  original.id="original-pdf-link";original.href=document.original_url;original.target="_blank";original.rel="noopener";
  toolbar.append(picker,original);
  panel.append(toolbar,pageToolbar({page:page.page_number,pageCount:document.page_count},actions.onPage),pageImage(page,selection.role),extractedText(document,selection),documentDetails(document));
  return panel;
}
