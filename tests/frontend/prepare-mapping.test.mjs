import test from 'node:test';
import assert from 'node:assert/strict';
import {renderMappingResult} from '../../src/submission/static/prepare/mapping.mjs';

function result(status='verified_anchor',reason='layout_whitespace_anchor'){
  return {snapshot_origin:'real_pdf',reason_code:reason,mapping:{mapping_status:status,target_page_numbers:[2,3]}};
}

function harness(){
  const navigated=[];
  const target={children:[],replaceChildren(...children){this.children=children;},append(child){this.children.push(child);}};
  const ui={notice:(text,error)=>({tag:'p',text,error}),button:(text,click)=>({tag:'button',text,click})};
  return {target,navigated,render(value,options={}){renderMappingResult({target,result:value,matches:true,total:3,ui,onPage:page=>navigated.push(page),...options});}};
}

for(const [status,reason,text] of [
  ['identity','exact_identity','원본 PDF의 문구와 연결되었습니다.'],
  ['verified_anchor','exact_anchor','변환 PDF에서 같은 문구를 확인했습니다. 원본 페이지나 레이아웃 검증은 아닙니다.'],
  ['verified_anchor','layout_whitespace_anchor','공백·탭·줄바꿈을 제외한 문구가 변환 PDF와 일치합니다. 원본 페이지나 레이아웃 검증은 아닙니다.'],
]){
  test(`${status}/${reason} renders its honest notice and verified PDF actions`,()=>{
    const h=harness();h.render(result(status,reason));
    assert.deepEqual(h.target.children[0],{tag:'p',text,error:false});
    assert.deepEqual(h.target.children.slice(1).map(node=>[node.tag,node.text]),[['button','2쪽 PDF 보기'],['button','3쪽 PDF 보기']]);
    assert.deepEqual(h.navigated,[]);
    h.target.children[1].click();h.target.children[2].click();
    assert.deepEqual(h.navigated,[2,3]);
  });
}

for(const [status,text] of [
  ['ambiguous','문구 후보가 여러 곳입니다. 페이지를 확정할 수 없습니다.'],
  ['unmapped','대응한 문구를 찾지 못했습니다. 원본 내용의 부재를 뜻하지 않습니다.'],
  ['mismatch','원문과 대응 결과가 일치하지 않습니다. 페이지를 확정할 수 없습니다.'],
  ['unknown','대응 결과를 검증할 수 없습니다.'],
]){
  test(`${status} removes previous page buttons even with claimed page numbers`,()=>{
    const h=harness();h.render(result());h.render(result(status));
    assert.deepEqual(h.target.children,[{tag:'p',text,error:true}]);
    assert.deepEqual(h.navigated,[]);
  });
}

for(const status of ['identity','verified_anchor']){
  for(const origin of ['synthetic',undefined]){
    test(`${status} from ${origin} has no page buttons`,()=>{
      const h=harness();h.render({...result(status),snapshot_origin:origin});
      assert.equal(h.target.children.length,1);assert.equal(h.target.children[0].error,true);
    });
  }
}

test('a failed source binding overrides the layout notice and removes verified actions',()=>{
  const h=harness();h.render(result());h.render(result(),{matches:false});
  assert.deepEqual(h.target.children,[{tag:'p',text:'원문과 대응 결과가 일치하지 않습니다. 페이지를 확정할 수 없습니다.',error:true}]);
});

test('invalid page ranges never render navigation buttons',()=>{
  for(const pages of [[],[0],[4],[1.5],['2'],[2,4],null]){
    const h=harness();const value=result();h.render({...value,mapping:{...value.mapping,target_page_numbers:pages}});
    assert.equal(h.target.children.length,1);assert.equal(h.target.children[0].error,true);
  }
});

test('a missing mapping uses the unverified result notice',()=>{
  const h=harness();h.render({});
  assert.deepEqual(h.target.children,[{tag:'p',text:'대응 결과를 검증할 수 없습니다.',error:true}]);
});
