window.ReportReason=(()=>{
  let modal,resolve,returnFocus;
  function close(value=null){modal.classList.remove('open');modal.setAttribute('aria-hidden','true');const finish=resolve;resolve=null;if(returnFocus?.isConnected)returnFocus.focus();finish?.(value);}
  function init(){
    modal=document.createElement('div');modal.id='reportReasonModal';modal.className='modal-backdrop account-action-overlay';modal.setAttribute('aria-hidden','true');
    modal.innerHTML='<section class="modal account-action-modal" role="dialog" aria-modal="true" aria-labelledby="reportReasonTitle"><div class="modal-header"><h2 id="reportReasonTitle">举报提交</h2><button type="button" class="close-button" data-report-close aria-label="取消举报">×</button></div><form id="reportReasonForm" class="account-action-form"><label>常见理由<select name="preset"><option value="">选择理由或自行填写</option><option>截图与题目不符</option><option>疑似抄袭或虚假提交</option><option>材料不完整或无法核验</option><option>其他</option></select></label><label>举报理由<textarea name="reason" required maxlength="500" rows="4" placeholder="请说明需要管理员核查的问题（最多500字）"></textarea></label><div class="modal-footer"><button type="button" class="secondary-button" data-report-close>取消</button><button type="submit" class="primary-button">提交举报</button></div></form></section>';
    document.body.append(modal);modal.querySelectorAll('[data-report-close]').forEach(button=>button.onclick=()=>close());
    const form=modal.querySelector('form');form.elements.preset.onchange=()=>{if(form.elements.preset.value&&form.elements.preset.value!=='其他')form.elements.reason.value=form.elements.preset.value;form.elements.reason.focus();};
    form.onsubmit=event=>{event.preventDefault();const reason=form.elements.reason.value.trim();if(reason)close(reason);else form.elements.reason.focus();};
    document.addEventListener('keydown',event=>{
      if(!resolve)return;if(event.key==='Escape'){event.preventDefault();close();return;}
      if(event.key!=='Tab')return;const controls=[...modal.querySelectorAll('button,select,textarea')].filter(el=>el.getClientRects().length),first=controls[0],last=controls.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    });
  }
  function prompt(){returnFocus=document.activeElement;if(!modal)init();if(resolve)return Promise.resolve(null);modal.querySelector('form').reset();modal.classList.add('open');modal.setAttribute('aria-hidden','false');modal.querySelector('textarea').focus();return new Promise(finish=>resolve=finish);}
  return {prompt};
})();
