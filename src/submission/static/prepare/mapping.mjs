import {verifiedPages} from './state.mjs';

const texts={
  identity:'원본 PDF의 문구와 연결되었습니다.',
  verified_anchor:'변환 PDF에서 같은 문구를 확인했습니다. 원본 페이지나 레이아웃 검증은 아닙니다.',
  ocr_page:'이 문구는 이미지에서 글자 인식으로 읽었습니다(오류 가능). 해당 쪽만 연결하며 문구 위치는 확인하지 않았습니다.',
  ambiguous:'문구 후보가 여러 곳입니다. 페이지를 확정할 수 없습니다.',
  unmapped:'대응한 문구를 찾지 못했습니다. 원본 내용의 부재를 뜻하지 않습니다.',
  mismatch:'원문과 대응 결과가 일치하지 않습니다. 페이지를 확정할 수 없습니다.'
};

export function renderMappingResult({target,result,matches,total,ui,onPage}){
  const pages=matches?verifiedPages(result,total):[];
  const status=matches?result?.mapping?.mapping_status:'mismatch';
  const message=status==='verified_anchor'&&result.reason_code==='layout_whitespace_anchor'
    ?'공백·탭·줄바꿈을 제외한 문구가 변환 PDF와 일치합니다. 원본 페이지나 레이아웃 검증은 아닙니다.'
    :texts[status];
  target.replaceChildren(ui.notice(message??'대응 결과를 검증할 수 없습니다.',!pages.length));
  for(const page of pages)target.append(ui.button(`${page}쪽 PDF 보기`,()=>onPage(page)));
}
