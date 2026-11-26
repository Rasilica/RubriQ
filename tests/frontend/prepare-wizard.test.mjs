import test from 'node:test';
import assert from 'node:assert/strict';
import {STEPS,reachableStep,clampStep,stepHelp,pageTitle} from '../../src/submission/static/prepare/wizard.mjs';
import {locationLabel,omittedSummary} from '../../src/submission/static/prepare/location.mjs';

test('steps follow the required order',()=>{
  assert.deepEqual(STEPS.map(step=>step.label),['문서 올리기','읽은 내용 확인','요구사항 뽑기','요구사항 확정','보고서 검사','결과·보관']);
});

test('each finished stage unlocks only the next step',()=>{
  assert.equal(reachableStep({}),1);
  assert.equal(reachableStep({prepared:true}),3);
  assert.equal(reachableStep({prepared:true,draft:true}),4);
  assert.equal(reachableStep({prepared:true,draft:true,confirmed:true}),5);
  assert.equal(reachableStep({prepared:true,draft:true,confirmed:true,checked:true}),6);
  assert.equal(reachableStep({prepared:true,checked:true}),3,'results without confirmed criteria do not skip ahead');
});

test('a requested step is pulled back to the furthest reachable one',()=>{
  assert.equal(clampStep(6,{prepared:true,draft:true}),4);
  assert.equal(clampStep(2,{prepared:true,draft:true}),2);
  assert.equal(clampStep(0,{prepared:true}),1);
  assert.equal(clampStep(Number.NaN,{}),1);
});

test('DOCX locations read as table cells, paragraphs and page parts',()=>{
  assert.equal(locationLabel('word/document.xml::/w:document[1]/w:body[1]/w:tbl[1]/w:tr[1]/w:tc[2]/w:p[1]'),'표 1 · 1행 2열');
  assert.equal(locationLabel('word/document.xml::/w:document[1]/w:body[1]/w:p[13]'),'본문 13번째 문단');
  assert.equal(locationLabel('word/footer1.xml::/w:ftr[1]/w:p[1]'),'꼬리말');
  assert.equal(locationLabel('word/header2.xml::/w:hdr[1]'),'머리말');
  assert.equal(locationLabel('word/footnotes.xml::/w:footnotes[1]/w:footnote[3]/w:p[1]'),'각주');
});

test('HWPX locations read as sections, tables, notes and paragraphs',()=>{
  assert.equal(locationLabel('Contents/section0.xml::/hs:sec[1]/hp:p[4]'),'본문 4번째 문단');
  assert.equal(locationLabel('Contents/section1.xml::/hs:sec[1]/hp:p[2]'),'2구역 · 본문 2번째 문단');
  assert.equal(locationLabel('Contents/section0.xml::/hs:sec[1]/hp:p[2]/hp:run[1]/hp:tbl[1]/hp:tr[3]/hp:tc[2]/hp:subList[1]/hp:p[1]'),'표 · 3행 2열');
  assert.equal(locationLabel('Contents/section0.xml::/hs:sec[1]/hp:p[2]/hp:run[1]/hp:ctrl[1]/hp:footNote[1]/hp:subList[1]/hp:p[1]'),'각주');
});

test('HWP locations are zero based and become human counts',()=>{
  assert.equal(locationLabel('BodyText/Section0/paragraph[0]'),'본문 1번째 문단');
  assert.equal(locationLabel('BodyText/Section0/paragraph[0]/control[2]/row[0]/cell[1]/paragraph[0]'),'표 · 1행 2열');
  assert.equal(locationLabel('BodyText/Section2/paragraph[4]'),'3구역 · 본문 5번째 문단');
});

test('PDF locations use the page and unknown shapes never leak internals',()=>{
  assert.equal(locationLabel('pages/3/blocks/p3-b1'),'3쪽');
  assert.equal(locationLabel('report-86fe699e:weird::path'),'문서 안 위치');
  assert.equal(locationLabel(undefined),'문서 안 위치');
});

test('only unread content (pictures, formulas, tables, notes) is counted, never settings or package parts',()=>{
  const omitted=[
    'word/document.xml::/w:document[1]/w:body[1]/w:p[13]/w:r[1]/w:drawing[1]',
    'word/document.xml::/w:document[1]/w:body[1]/w:p[76]/w:r[1]/w:drawing[1]',
    'Contents/section0.xml::/hs:sec[1]/hp:p[1]/hp:run[1]/hp:secPr[1]',
    'Contents/section0.xml::/hs:sec[1]/hp:p[1]/hp:run[1]/hp:ctrl[1]/hp:colPr[1]',
    'Contents/section0.xml::/hs:sec[1]/hp:p[7]/hp:run[1]/hp:ctrl[1]/hp:fieldBegin[1]',
    'BodyText/Section0/paragraph[0]/control[0]',
    'Contents/section0.xml::/hs:sec[1]/hp:p[2]/hp:run[1]/hp:ctrl[1]/hp:endNote[1]',
    'settings.xml::/{urn:oasis:names:tc:opendocument:xmlns:manifest:1.0}manifest[1]',
    'Contents/content.hpf::/',
  ].map(path=>({path}));
  assert.equal(omittedSummary(omitted),'그림 2개 · 각주·미주 1개');
  assert.equal(omittedSummary([]),'');
  assert.equal(omittedSummary(undefined),'');
});
test('tab title follows the step and demo help never claims that an AI works',()=>{
  assert.equal(pageTitle(4),'요구사항 확정 | RubriQ');
  assert.equal(stepHelp(3,false),STEPS[2].help);
  for(const step of [3,5])assert.doesNotMatch(stepHelp(step,true),/AI가/);
  assert.equal(stepHelp(4,true),STEPS[3].help);
});
