// Turn internal document locators (XPath-like paths) into words a reader understands.
const FALLBACK='문서 안 위치';
const PART_NAMES=[[/^word\/header\d*\.xml/,'머리말'],[/^word\/footer\d*\.xml/,'꼬리말'],[/^word\/footnotes\.xml/,'각주'],[/^word\/endnotes\.xml/,'미주'],[/^word\/comments\.xml/,'메모']];
const NOTE_NAMES=[['footNote','각주'],['endNote','미주'],['header','머리말'],['footer','꼬리말']];
const index=(path,name)=>{const match=path.match(new RegExp(`(?:^|/)(?:\\w+:)?${name}\\[(\\d+)\\]`));return match?Number(match[1]):null;};
const section=n=>n>1?`${n}구역 · `:'';

function tableCell(path,oneBased){
  const row=index(path,oneBased?'tr':'row');const cell=index(path,oneBased?'tc':'cell');
  if(row===null||cell===null)return null;
  const shift=oneBased?0:1;return `${row+shift}행 ${cell+shift}열`;
}

function docx(path){
  for(const [pattern,name] of PART_NAMES)if(pattern.test(path))return name;
  if(!path.startsWith('word/document.xml::'))return FALLBACK;
  const table=index(path,'tbl');const cell=tableCell(path,true);
  if(table!==null&&cell)return `표 ${table} · ${cell}`;
  const paragraph=path.match(/\/w:body\[1\]\/w:p\[(\d+)\]/);
  return paragraph?`본문 ${paragraph[1]}번째 문단`:FALLBACK;
}

function hwpx(path){
  const part=Number(path.match(/^Contents\/section(\d+)\.xml::/)[1])+1;
  for(const [tag,name] of NOTE_NAMES)if(path.includes(`hp:${tag}[`))return name;
  const cell=tableCell(path,true);if(path.includes('hp:tbl[')&&cell)return `${section(part)}표 · ${cell}`;
  const paragraph=path.match(/\/hs:sec\[1\]\/hp:p\[(\d+)\]/);
  return paragraph?`${section(part)}본문 ${paragraph[1]}번째 문단`:FALLBACK;
}

function hwp(path){
  const part=Number(path.match(/^BodyText\/Section(\d+)\//)[1])+1;
  const cell=tableCell(path,false);if(cell)return `${section(part)}표 · ${cell}`;
  const paragraph=path.match(/^BodyText\/Section\d+\/paragraph\[(\d+)\]/);
  return paragraph?`${section(part)}본문 ${Number(paragraph[1])+1}번째 문단`:FALLBACK;
}

export function locationLabel(path){
  if(typeof path!=='string')return FALLBACK;
  const page=path.match(/^pages\/(\d+)\//);if(page)return `${page[1]}쪽`;
  if(path.startsWith('word/'))return docx(path);
  if(/^Contents\/section\d+\.xml::/.test(path))return hwpx(path);
  if(/^BodyText\/Section\d+\//.test(path))return hwp(path);
  return FALLBACK;
}

// Only real content a reader would miss is counted; page/column/numbering settings,
// fields and package metadata are not content, so they never inflate the number.
const KINDS=[[new Set(['drawing','pict','pic','picture','image','img','gso']),'그림'],[new Set(['equation','oMath']),'수식'],[new Set(['tbl','table']),'표'],[new Set(['footNote','endNote','footnote','endnote']),'각주·미주']];

export function omittedSummary(locators){
  const counts=new Map();
  for(const item of locators??[]){
    const last=String(item?.path??'').split('/').pop().replace(/^\{[^}]*\}|^\w+:/,'').replace(/\[\d+\]$/,'');
    const kind=KINDS.find(([names])=>names.has(last))?.[1];
    if(kind)counts.set(kind,(counts.get(kind)??0)+1);
  }
  return [...counts].map(([kind,count])=>`${kind} ${count}개`).join(' · ');
}
