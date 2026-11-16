// Lucian UX/UI Prompt #032 #039 #070 #079 #098 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/
// Ported behavior only: DOM is built with createElement so no markup is parsed from strings.
const SVG='http://www.w3.org/2000/svg';
const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function node(tag,className,text){const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el;}
function icon(viewBox,paths,className){
  const svg=document.createElementNS(SVG,'svg');svg.setAttribute('viewBox',viewBox);svg.setAttribute('aria-hidden','true');if(className)svg.setAttribute('class',className);
  for(const d of paths){const path=document.createElementNS(SVG,'path');path.setAttribute('d',d);svg.append(path);}
  return svg;
}

// #039 Sliding pill tabs: a persistent tablist whose ink pill glides to the selected tab.
export function createPillTabs({label,options,value,onSelect}){
  const root=node('div','ux u039');const tabs=node('div','u039-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',label);
  const pill=node('span','u039-pill');pill.setAttribute('aria-hidden','true');tabs.append(pill);root.append(tabs);
  const buttons=options.map(([key,text])=>{const tab=node('button','u039-tab',text);tab.type='button';tab.setAttribute('role','tab');tab.dataset.value=key;tabs.append(tab);return tab;});
  let current=value;
  function movePill(animate){
    const tab=buttons.find(item=>item.dataset.value===current);if(!tab||!tab.offsetWidth)return;
    if(!animate)pill.style.transition='none';
    pill.style.setProperty('--x',`${tab.offsetLeft}px`);pill.style.setProperty('--w',`${tab.offsetWidth}px`);
    if(!animate){void pill.offsetWidth;pill.style.transition='';}
  }
  function select(next,{notify=false,focus=false}={}){
    const changed=next!==current;current=next;
    for(const tab of buttons){const on=tab.dataset.value===current;tab.setAttribute('aria-selected',String(on));tab.tabIndex=on?0:-1;}
    if(focus)buttons.find(item=>item.dataset.value===current)?.focus();
    movePill(true);if(notify&&changed)onSelect(current);
  }
  buttons.forEach((tab,index)=>{
    tab.addEventListener('click',()=>select(tab.dataset.value,{notify:true}));
    tab.addEventListener('keydown',event=>{
      const step=event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0;if(!step)return;event.preventDefault();
      select(buttons[(index+step+buttons.length)%buttons.length].dataset.value,{notify:true,focus:true});
    });
  });
  select(current);
  // The pill is measured from layout, so re-measure once attached and whenever the bar resizes.
  const observer=new ResizeObserver(()=>movePill(false));observer.observe(tabs);
  return {element:root,select:next=>select(next),focus:()=>buttons.find(item=>item.dataset.value===current)?.focus(),dispose:()=>observer.disconnect()};
}

// #070 Stacking toasts: newest in front, older ones tucked behind; hover/focus fans the stack out.
const TONES={ok:['var(--ux-mint)',['M4 9.4l3.2 3.2L14 5.6']],info:['var(--ux-ink-2)',['M9 8v5M9 5h.01']],err:['var(--ux-danger)',['M9 5v5M9 13h.01']]};
export function createToaster(){
  const root=node('div','ux u070');const zone=node('div','u070-zone');zone.setAttribute('role','region');zone.setAttribute('aria-label','알림');
  const live=node('div','u070-live');live.setAttribute('aria-live','polite');zone.append(live);root.append(zone);document.body.append(root);
  const list=[];const DUR=4500;let open=false;let frame=0;let last=performance.now();
  function layout(){
    let acc=0;
    list.forEach((toast,index)=>{
      const el=toast.el;el.classList.toggle('back',!open&&index>0);
      if(open){el.style.setProperty('--y',`${-acc}px`);el.style.setProperty('--s','1');el.style.setProperty('--o','1');acc+=el.offsetHeight+8;}
      else{el.style.setProperty('--y',`${-(index*14)}px`);el.style.setProperty('--s',(1-index*0.06).toFixed(2));el.style.setProperty('--o',index>2?'0':'1');}
      el.style.zIndex=String(50-index);el.inert=!open&&index>0;
    });
  }
  function remove(toast,dir){
    const index=list.indexOf(toast);if(index<0)return;list.splice(index,1);
    toast.el.classList.add('leave');if(dir){toast.el.style.setProperty('--dir',String(dir));toast.el.classList.add('side');}
    setTimeout(()=>toast.el.remove(),450);layout();
  }
  function loop(now){
    const dt=now-last;last=now;
    if(!open)list.slice(0,1).forEach(toast=>{toast.left-=dt;toast.el.style.setProperty('--left',Math.max(0,toast.left/DUR).toFixed(3));if(toast.left<=0)remove(toast);});
    frame=list.length?requestAnimationFrame(loop):0;
  }
  function push(title,detail='',tone='ok'){
    const [color,paths]=TONES[tone]??TONES.ok;const el=node('div','u070-t enter');el.style.setProperty('--c',color);el.setAttribute('role',tone==='err'?'alert':'status');
    const ic=node('span','u070-ic');ic.setAttribute('aria-hidden','true');ic.append(icon('0 0 18 18',paths));
    const tx=node('span','u070-tx');tx.append(node('b','',title),node('small','',detail));
    const close=node('button','u070-x');close.type='button';close.setAttribute('aria-label','알림 닫기');close.append(icon('0 0 14 14',['M3.5 3.5l7 7M10.5 3.5l-7 7']));
    const bar=node('span','u070-bar');bar.setAttribute('aria-hidden','true');el.append(ic,tx,close,bar);
    const toast={el,left:DUR};zone.append(el);list.unshift(toast);void el.offsetWidth;el.classList.remove('enter');layout();live.textContent=title;
    close.addEventListener('click',()=>remove(toast));
    let startX=0;let dx=0;let down=false;
    el.addEventListener('pointerdown',event=>{if(event.target.closest('button'))return;down=true;startX=event.clientX;dx=0;el.setPointerCapture(event.pointerId);el.classList.add('drag');});
    el.addEventListener('pointermove',event=>{if(!down)return;dx=event.clientX-startX;el.style.setProperty('--dx',`${dx}px`);el.style.setProperty('--o',String(Math.max(0.2,1-Math.abs(dx)/260)));});
    const end=()=>{if(!down)return;down=false;el.classList.remove('drag');if(Math.abs(dx)>90)remove(toast,dx>0?1:-1);else{el.style.setProperty('--dx','0px');layout();}};
    el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);
    el.addEventListener('pointerenter',event=>{if(event.pointerType==='mouse')setOpen(true);});
    el.addEventListener('pointerleave',event=>{if(event.pointerType==='mouse'&&!zone.contains(event.relatedTarget)&&!zone.contains(document.activeElement))setOpen(false);});
    if(!frame){last=performance.now();frame=requestAnimationFrame(loop);}
  }
  const setOpen=value=>{if(open!==value){open=value;layout();}};
  zone.addEventListener('focusin',()=>setOpen(true));
  zone.addEventListener('focusout',event=>{if(!zone.contains(event.relatedTarget))setOpen(false);});
  return {push};
}

// #032 Drag-and-drop upload: wraps an existing file input; drops are written back to that input.
function size(bytes){return bytes>1048576?`${(bytes/1048576).toFixed(1)} MB`:`${Math.max(1,Math.round(bytes/1024))} KB`;}
export function mountDropzone(input,{title,hint}){
  const root=node('div','ux u032');const zone=node('button','u032-zone');zone.type='button';
  const dash=document.createElementNS(SVG,'svg');dash.setAttribute('class','u032-dash');dash.setAttribute('aria-hidden','true');
  const rect=document.createElementNS(SVG,'rect');rect.setAttribute('width','100%');rect.setAttribute('height','100%');rect.setAttribute('rx','25');dash.append(rect);
  const orb=node('span','u032-orb');orb.setAttribute('aria-hidden','true');orb.append(icon('0 0 28 28',['M8.5 20.5H7a5 5 0 0 1-.6-10 7 7 0 0 1 13.4-1.6A5.5 5.5 0 0 1 21 20.5h-1.5M14 13v10M10.5 16.5L14 13l3.5 3.5']));
  const heading=node('b',undefined,'끌어다 놓거나 ');heading.append(node('em','','파일 선택'));
  zone.append(dash,orb,heading,node('small','',hint));zone.setAttribute('aria-label',`${title} 파일 선택`);
  input.classList.add('u032-file');input.tabIndex=-1;input.setAttribute('aria-hidden','true');
  input.replaceWith(root);root.append(zone,input);
  let row=null;
  function show(){
    row?.remove();row=null;const file=input.files[0];
    zone.setAttribute('aria-label',file?`${title} 다시 선택 · 선택한 파일 ${file.name}`:`${title} 파일 선택`);if(!file)return;
    row=node('div','u032-row done');const meta=node('div','u032-meta');meta.append(node('b','',file.name),node('small','',size(file.size)));
    const status=node('span','u032-st');status.setAttribute('aria-hidden','true');status.append(icon('0 0 16 16',['M3.5 8.4l2.8 2.8L12.5 5']));
    row.append(meta,status);root.append(row);
  }
  zone.addEventListener('click',()=>input.click());
  input.addEventListener('change',show);
  let depth=0;
  zone.addEventListener('dragenter',event=>{event.preventDefault();depth++;root.classList.add('is-over');});
  zone.addEventListener('dragover',event=>event.preventDefault());
  zone.addEventListener('dragleave',()=>{if(--depth<=0){depth=0;root.classList.remove('is-over');}});
  zone.addEventListener('drop',event=>{
    event.preventDefault();depth=0;root.classList.remove('is-over');
    const file=event.dataTransfer?.files?.[0];if(!file)return;
    const transfer=new DataTransfer();transfer.items.add(file);input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));
  });
  return {zone};
}

// #079 Skeleton: shimmering placeholders while loading, then content blooms in top-down.
export function skeleton(lines=[100,86,58,92,70]){
  const root=node('div','ux');root.setAttribute('aria-hidden','true');
  for(const width of lines){const line=node('div','u079-s u079-line');line.style.width=`${width}%`;line.append(node('span','u079-sk'));root.append(line);}
  const block=node('div','u079-s u079-block');block.append(node('span','u079-sk'));root.append(block);
  return root;
}
export function bloom(container){
  if(reduced())return;
  container.classList.remove('is-done');container.classList.add('ux','u079');
  [...container.children].forEach((child,index)=>{child.classList.add('u079-r');child.style.setProperty('--d',`${index*0.04}s`);});
  requestAnimationFrame(()=>requestAnimationFrame(()=>container.classList.add('is-done')));
}

// #098 Rolling digits: each digit column rolls from 0 to its value, staggered left to right.
export function rollingNumber(value,label){
  const root=node('span','ux u098-num');root.setAttribute('role','img');root.setAttribute('aria-label',label);
  const columns=String(value).split('').map((digit,index)=>{
    const column=node('span','u098-col');column.setAttribute('aria-hidden','true');column.style.setProperty('--i',String(index));column.style.setProperty('--d','0');
    for(let n=0;n<10;n++)column.append(node('span','',String(n)));root.append(column);return [column,digit];
  });
  const settle=()=>columns.forEach(([column,digit])=>column.style.setProperty('--d',digit));
  if(reduced())settle();else requestAnimationFrame(()=>requestAnimationFrame(settle));
  return root;
}
