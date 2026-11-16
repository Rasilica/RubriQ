import {element,button} from "./primitives.mjs";

export function requestDiscard() {
  const origin=document.activeElement;
  const dialog=element("dialog","discard-dialog");
  dialog.id="discard-dialog";
  dialog.setAttribute("aria-labelledby","discard-title");
  dialog.setAttribute("aria-describedby","discard-description");
  const title=element("h2","","저장 전 입력을 취소할까요?");
  title.id="discard-title";
  title.tabIndex=-1;
  title.autofocus=true;
  const description=element("p","","불러오면 저장하지 않은 수정 내용이 사라집니다. 계속 편집하면 입력을 유지합니다.");
  description.id="discard-description";
  const cancel=button("계속 편집",()=>dialog.close("cancel"));
  cancel.id="continue-editing";
  const accept=button("입력 취소하고 불러오기",()=>dialog.close("discard"),"danger");
  accept.id="discard-reload";
  const actions=element("div","cluster dialog-actions");
  actions.append(cancel,accept);
  dialog.append(title,description,actions);
  return new Promise((resolve)=>{
    dialog.addEventListener("cancel",(event)=>{event.preventDefault();dialog.close("cancel");});
    dialog.addEventListener("close",()=>{
      const accepted=dialog.returnValue === "discard";
      dialog.remove();
      if(origin instanceof HTMLElement && origin.isConnected) origin.focus();
      resolve(accepted);
    },{once:true});
    document.body.append(dialog);
    dialog.showModal();
    title.focus();
  });
}
