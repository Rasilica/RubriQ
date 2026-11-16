import {element,button} from '/review-assets/primitives.mjs';
import {createResources} from './state.mjs';
import {createLibraryAPI,libraryError} from './library-api.mjs';

export function mountLibrary({getSession,canOpen,acceptSession,setOpening,getSaveState,notify}){
  const api=createLibraryAPI();const requests=createResources();
  const list=document.querySelector('#library-list');const status=document.querySelector('#library-status');
  const pagination=document.querySelector('#library-pagination');const refresh=document.querySelector('#library-refresh');
  const dialog=document.querySelector('#library-delete-dialog');const cancel=document.querySelector('#library-delete-cancel');const confirm=document.querySelector('#library-delete-confirm');
  let page=1;let pendingDelete=null;let trigger=null;let opening=false;
  const notice=(text,error=false)=>{const node=element('p',`notice${error?' error':''}`,text);node.setAttribute('role',error?'alert':'status');return node;};
  function showError(error){status.replaceChildren(notice(libraryError(error),true));}
  async function load(requestedPage=page){
    const request=requests.begin('list');status.replaceChildren(notice('저장 목록을 불러오는 중입니다.'));refresh.disabled=true;
    try{
      const data=await api.list(requestedPage,request.signal);if(!requests.current(request))return;
      if(!data.items.length&&requestedPage>1){void load(requestedPage-1);return;}
      page=data.page;list.replaceChildren();status.replaceChildren(notice(data.total?`${data.total}개의 저장본`:'아직 저장한 문서가 없습니다. 준비 결과에서 문서 보관하기를 눌러주세요.'));
      for(const item of data.items){
        const row=element('li','library-row');const label=element('div','stack');
        label.append(element('strong','',item.project_name),element('span','muted',new Date(item.saved_at).toLocaleString('ko-KR')));
        const actions=element('div','cluster');const open=button('열기',()=>openSaved(item.saved_id));open.setAttribute('aria-label',`${item.project_name} 열기`);
        const remove=button('저장본 삭제',()=>askDelete(item,remove));remove.setAttribute('aria-label',`${item.project_name} 저장본 삭제`);
        actions.append(open,remove);row.append(label,actions);list.append(row);
      }
      const previous=button('이전 목록',()=>load(page-1));previous.disabled=page<=1;
      const next=button('다음 목록',()=>load(page+1));next.disabled=page*20>=data.total;
      pagination.replaceChildren(previous,element('span','',`${page} / ${Math.max(1,Math.ceil(data.total/20))}`),next);
    }catch(error){if(requests.current(request)){showError(error);status.append(button('목록 다시 불러오기',()=>load(requestedPage)));}}
    finally{if(requests.current(request))refresh.disabled=false;}
  }
  async function openSaved(id){
    if(opening)return;
    if(!canOpen()){status.replaceChildren(notice('현재 임시 문서를 삭제하고 준비 작업이 끝난 뒤 저장본을 열어주세요.',true));return;}
    opening=true;setOpening(true);const request=requests.begin('open');status.replaceChildren(notice('저장본을 확인하고 여는 중입니다.'));
    try{const session=await api.open(id,request.signal);if(!requests.current(request))return;acceptSession(session);status.replaceChildren(notice('저장한 준비 결과를 열었습니다.'));}
    catch(error){if(requests.current(request))showError(error);}
    finally{if(requests.current(request)){opening=false;setOpening(false);}}
  }
  function askDelete(item,buttonNode){
    pendingDelete=item;trigger=buttonNode;document.querySelector('#library-delete-name').textContent=item.project_name;dialog.showModal();cancel.focus();
  }
  function closeDialog(){dialog.close();}
  cancel.addEventListener('click',closeDialog);
  dialog.addEventListener('close',()=>{pendingDelete=null;(trigger?.isConnected?trigger:refresh).focus();});
  confirm.addEventListener('click',async()=>{
    if(!pendingDelete)return;
    const item=pendingDelete;const request=requests.begin('remove');confirm.disabled=true;cancel.disabled=true;
    dialog.addEventListener('cancel',preventPendingCancel);
    try{await api.remove(item.saved_id,request.signal);if(!requests.current(request))return;closeDialog();notify?.('저장본을 삭제했습니다',item.project_name);await load();refresh.focus();}
    catch(error){if(requests.current(request)){closeDialog();showError(error);}}
    finally{if(requests.current(request)){dialog.removeEventListener('cancel',preventPendingCancel);confirm.disabled=false;cancel.disabled=false;}}
  });
  function preventPendingCancel(event){event.preventDefault();}
  refresh.addEventListener('click',()=>load());
  void load();
  return {
    async save(buttonNode){
      const session=getSession();if(!session)return;const state=getSaveState?.();if(state&&!state.allowed){document.querySelector('#save-status').replaceChildren(notice(state.reason,true));return;}const request=requests.begin('save');buttonNode.disabled=true;buttonNode.textContent='보관 중…';
      const target=document.querySelector('#save-status');target.replaceChildren(notice('준비 결과를 보관하는 중입니다.'));
      try{
        const result=await api.save(session,request.signal);if(!requests.current(request)||session!==getSession())return;
        const contents=result.has_check?'문서·확정한 요구사항·AI 검사 결과':result.has_semantic_archive?'문서·확정한 요구사항':'문서 준비 결과';
        target.replaceChildren(notice(`${contents}${result.already_saved?'는 이미 보관되어 있습니다.':'를 보관했습니다.'} 새로고침하거나 서버를 다시 시작한 뒤 목록에서 열 수 있습니다. 확정 전 초안과 입력 중인 수정은 포함되지 않습니다.`));notify?.(result.already_saved?'이미 보관된 문서입니다':'문서를 보관했습니다',contents);void load(1);
      }catch(error){if(requests.current(request)&&session===getSession())target.replaceChildren(notice(libraryError(error),true));}
      finally{if(requests.current(request)){buttonNode.disabled=getSaveState?.().allowed===false;buttonNode.textContent='문서 보관하기';}}
    },
    sessionChanged(){requests.begin('save');},
    restore(){void load(page);},
    dispose(){
      requests.clear();opening=false;setOpening(false);refresh.disabled=false;
      confirm.disabled=false;cancel.disabled=false;dialog.removeEventListener('cancel',preventPendingCancel);
      if(dialog.open)closeDialog();pendingDelete=null;
    },
  };
}
