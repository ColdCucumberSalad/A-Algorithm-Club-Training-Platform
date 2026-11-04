(() => {
  const root = document.getElementById('extensionResources');
  const escape = value => String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let items = [];
  let selectedCategory = 'all';
  const categoryOptions = value => `<option value="library" ${value !== 'games' ? 'selected' : ''}>资料库</option><option value="games" ${value === 'games' ? 'selected' : ''}>小游戏</option>`;
  async function api(url, options) {
    const response = await clubApi.request(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || '操作失败，请重试');
    return payload;
  }
  async function load() {
    window.PokerModule?.close();
    root.innerHTML = '<p role="status">正在加载资源…</p>';
    try {
      const result = await api('/api/extensions'); items = result.items;
      root.innerHTML = `<section class="page-heading"><div><p class="kicker">EXPLORE & LEARN</p><h1>拓展</h1></div>${result.can_manage ? '<button class="primary-button" id="extensionAdd">＋ 添加资源</button>' : ''}</section><div data-site-themed="true"><div class="segmented extension-filters" role="tablist" aria-label="拓展分类">${[['all','全部'],['library','资料库'],['games','小游戏']].map(([value,label]) => `<button class="segment ${selectedCategory === value ? 'active' : ''}" type="button" data-category="${value}">${label}</button>`).join('')}</div></div><div class="extension-wall"><article class="extension-tile" data-resource-category="${result.poker_category || 'games'}"><button type="button" class="extension-tile poker-entry" id="pokerEntry"><span class="extension-placeholder" aria-hidden="true">♠</span><span class="extension-copy"><small>RBC POKER CLUB</small><strong>德州扑克</strong><span>多人联机 · 免费练习 · 人机对战</span></span></button>${result.can_manage ? '<div class="extension-controls"><button id="pokerCategoryEdit">编辑归属</button></div>' : ''}</article>${items.map(item => `<article class="extension-tile" data-resource-category="${escape(item.category || 'library')}"><a class="extension-link" href="${escape(item.href)}" ${item.kind === 'link' ? 'target="_blank" rel="noopener noreferrer"' : 'download'} aria-label="${escape(item.title)} · ${item.kind === 'file' ? '下载文件' : '打开链接'}">${item.cover ? `<img src="${escape(item.cover)}" alt="" loading="lazy">` : `<span class="extension-placeholder" aria-hidden="true">${item.kind === 'file' ? '↓' : '↗'}</span>`}<span class="extension-copy"><small>${item.kind === 'file' ? '↓ 文件下载' : '↗ 外部链接'}</small><strong>${escape(item.title)}</strong><span>${escape(item.description || '')}</span></span></a>${result.can_manage ? `<div class="extension-controls"><button data-edit="${item.id}">编辑</button><button data-delete="${item.id}">删除</button></div>` : ''}</article>`).join('')}</div>`;
      const filter = () => {
        root.querySelectorAll('[data-resource-category]').forEach(tile => {
          tile.hidden = selectedCategory !== 'all' && tile.dataset.resourceCategory !== selectedCategory;
        });
        syncSegmented(root.querySelector('.extension-filters'), root.querySelector(`[data-category="${selectedCategory}"]`));
      };
      const tabs = [...root.querySelectorAll('[data-category]')];
      tabs.forEach((button, index) => {
        button.onclick = () => { selectedCategory = button.dataset.category; filter(); };
        button.onkeydown = event => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
          tabs[next].focus(); tabs[next].click();
        };
      });
      filter();
      root.querySelector('#pokerCategoryEdit')?.addEventListener('click', () => {
        const el = dialog(`<form class="extension-form"><h2>德州扑克归属</h2><label>显示分类<select name="category">${categoryOptions(result.poker_category || 'games')}</select></label><p role="alert"></p><div class="extension-actions"><button type="button" data-cancel class="secondary-button">取消</button><button class="primary-button" type="submit">保存</button></div></form>`);
        el.querySelector('form').onsubmit = async event => {
          event.preventDefault();
          const button = el.querySelector('[type=submit]'); button.disabled = true;
          try { await api('/api/extensions/builtin/poker', {method:'POST', body:new FormData(event.target)}); el.close(); await load(); }
          catch (error) { el.querySelector('[role=alert]').textContent = error.message; }
          finally { button.disabled = false; }
        };
      });
      root.querySelector('#pokerEntry').onclick = () => window.PokerModule.open();
      root.querySelector('#extensionAdd')?.addEventListener('click', () => editor());
      root.querySelectorAll('[data-edit]').forEach(button => button.onclick = () => editor(items.find(i => i.id === Number(button.dataset.edit))));
      root.querySelectorAll('[data-delete]').forEach(button => button.onclick = () => remove(items.find(i => i.id === Number(button.dataset.delete))));
    } catch (error) { root.innerHTML = `<p role="alert">${escape(error.message)}</p><button id="extensionRetry" class="secondary-button">重试</button>`; root.querySelector('button').onclick = load; }
  }
  function dialog(content) {
    const el = document.createElement('dialog'); el.className = 'extension-dialog'; el.innerHTML = content;
    document.body.append(el); el.addEventListener('close', () => el.remove()); el.showModal();
    el.querySelector('[data-cancel]').onclick = () => el.close(); return el;
  }
  function remove(item) {
    const el = dialog(`<h2>删除资源</h2><p>确定删除“${escape(item.title)}”？删除后成员将无法再访问此资源。</p><p role="alert"></p><div class="extension-actions"><button data-cancel class="secondary-button">取消</button><button data-confirm class="primary-button">确认删除</button></div>`);
    el.querySelector('[data-confirm]').onclick = async event => {
      event.target.disabled = true;
      try { await api(`/api/extensions/${item.id}`, {method:'DELETE'}); el.close(); await load(); }
      catch (error) { el.querySelector('[role=alert]').textContent = error.message; event.target.disabled = false; }
    };
  }
  function editor(item = {}) {
    const el = dialog(`<form class="extension-form"><h2>${item.id ? '编辑资源' : '添加资源'}</h2><label>名称<input name="title" maxlength="100" required value="${escape(item.title)}"></label><label>简介<textarea name="description" maxlength="300" rows="2">${escape(item.description)}</textarea></label><label>显示分类<select name="category">${categoryOptions(item.category)}</select></label><label>资源类型<select name="kind"><option value="link">超链接</option><option value="file" ${item.kind === 'file' ? 'selected' : ''}>下载文件</option></select></label><label data-url>链接地址<input type="url" name="url" placeholder="https://" value="${escape(item.url)}"></label><label data-file>下载文件<input type="file" name="file"><small>${item.filename ? `当前：${escape(item.filename)}，不选择则保留` : ''}</small></label><label>方格封面（可选）<input type="file" name="cover" accept="image/png,image/jpeg,image/webp"></label>${item.cover ? '<label class="extension-checkbox"><input type="checkbox" name="remove_cover" value="1">移除现有封面</label>' : ''}<p role="alert"></p><div class="extension-actions"><button type="button" data-cancel class="secondary-button">取消</button><button type="submit" class="primary-button">保存资源</button></div></form>`);
    const form = el.querySelector('form'), kind = form.elements.kind;
    function toggle() {
      form.querySelector('[data-url]').hidden = kind.value !== 'link';
      form.querySelector('[data-file]').hidden = kind.value !== 'file';
      form.elements.url.disabled = kind.value !== 'link';
      form.elements.url.required = kind.value === 'link';
      form.elements.file.disabled = kind.value !== 'file';
      form.elements.file.required = kind.value === 'file' && item.kind !== 'file';
    }
    kind.onchange = toggle; toggle();
    let busy = false;
    el.addEventListener('cancel', e => { if (busy) e.preventDefault(); });
    form.onsubmit = async event => {
      event.preventDefault(); if (busy) return;
      const body = new FormData(form);
      busy = true; form.querySelectorAll('button').forEach(b => b.disabled = true);
      try { await api(`/api/extensions${item.id ? '/' + item.id : ''}`, {method:'POST', body}); el.close(); await load(); }
      catch (error) { form.querySelector('[role=alert]').textContent = error.message; }
      finally { busy = false; form.querySelectorAll('button').forEach(b => b.disabled = false); }
    };
  }
  window.ExtensionResources = {load};
})();
