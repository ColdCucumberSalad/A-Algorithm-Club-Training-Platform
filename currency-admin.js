/**
 * RBC Currency System - Admin Panel JavaScript
 */

const CurrencyAdminModule = (() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // Load currency configuration
  async function loadConfig(teamId) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/config" + (teamId ? `?team_id=${encodeURIComponent(teamId)}` : ""), {
        credentials: "include",
      });

      if (response.ok) {
        return await response.json();
      }
      throw new Error("Failed to load config");
    } catch (error) {
      console.error("Failed to load currency config:", error);
      return null;
    }
  }

  // Save currency configuration
  async function saveConfig(config) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/config", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(config),
      });

      if (response.ok) {
        showToast("货币配置已保存");
        return true;
      } else {
        const data = await response.json();
        alert(data.error || "保存失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to save currency config:", error);
      alert("保存失败，请稍后重试");
      return false;
    }
  }

  // Adjust member balance
  async function adjustBalance(memberId, amount, description) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/adjust", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          member_id: memberId,
          amount: amount,
          description: description,
        }),
      });

      const data = await response.json();

      if (response.ok) {
        alert(`余额调整成功，新余额: ${data.new_balance} RBC`);
        return true;
      } else {
        alert(data.error || "调整失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to adjust balance:", error);
      alert("调整失败，请稍后重试");
      return false;
    }
  }

  // Load shop items for admin
  async function loadShopItems() {
    try {
      const response = await window.clubApi.request("/api/currency/admin/shop", {
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();
        return data.items;
      }
      return [];
    } catch (error) {
      console.error("Failed to load shop items:", error);
      return [];
    }
  }

  // Create shop item
  async function createShopItem(itemData) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/shop", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(itemData),
      });

      if (response.ok) {
        alert("商品创建成功");
        return true;
      } else {
        const data = await response.json();
        alert(data.error || "创建失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to create shop item:", error);
      alert("创建失败，请稍后重试");
      return false;
    }
  }

  // Update shop item
  async function updateShopItem(itemData) {
    try {
      const response = await window.clubApi.request("/api/currency/admin/shop", {
        method: "PUT",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(itemData),
      });

      if (response.ok) {
        alert("商品更新成功");
        return true;
      } else {
        const data = await response.json();
        alert(data.error || "更新失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to update shop item:", error);
      alert("更新失败，请稍后重试");
      return false;
    }
  }

  // Delete shop item
  async function deleteShopItem(itemId) {
    if (!confirm("确定要删除这个商品吗？")) {
      return false;
    }

    try {
      const response = await window.clubApi.request("/api/currency/admin/shop", {
        method: "DELETE",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ item_id: Number(itemId) }),
      });

      if (response.ok) {
        alert("商品删除成功");
        return true;
      } else {
        const data = await response.json();
        alert(data.error || "删除失败");
        return false;
      }
    } catch (error) {
      console.error("Failed to delete shop item:", error);
      alert("删除失败，请稍后重试");
      return false;
    }
  }

  // Render currency configuration panel
  async function renderConfigPanel(container, teamId) {
    const config = await loadConfig(teamId);
    if (!config || !container.isConnected) {
      container.innerHTML = '<p role="alert">无法加载货币配置，请重新打开团队配置。</p>';
      return;
    }
    const groupNames = config.reward_groups;
    const groupKeys = ['beginner', 'experienced'];
    const platforms = {codeforces:'Codeforces',atcoder:'AtCoder',nowcoder:'牛客',luogu:'洛谷',leetcode:'LeetCode',qoj:'QOJ'};
    const rewardGroups = config.reward_settings;
    const rewardMarkup = groupKeys.map(group => {
      const settings = rewardGroups[group];
      return `<section class="identity-reward-settings" data-reward-group="${group}" ${group===groupKeys[0]?'':'hidden'}><h4>${groupNames[group]}</h4><h4>平台单题奖励</h4><div class="platform-reward-table-wrap"><table class="platform-reward-table"><thead><tr><th rowspan="2">平台</th><th colspan="3">赛内 AC</th><th colspan="3">补题 AC</th></tr><tr>${['第一档','第二档','第三档','第一档','第二档','第三档'].map(label=>`<th>${label}</th>`).join('')}</tr></thead><tbody>${Object.entries(platforms).map(([platform,name])=>`<tr><th>${name}</th>${['contest','practice'].map(source=>platform==='qoj' ? `<td colspan="3"><input type="number" aria-label="${groupNames[group]} QOJ ${source==='contest'?'赛内':'补题'}每题 Coins" data-platform-reward="${platform}" data-source="${source}" min="0" max="100000" required value="${settings[source+'_rewards'][platform][0]}"></td>` : settings[source+'_rewards'][platform].map((value,index)=>`<td><input type="number" aria-label="${groupNames[group]} ${name} ${source==='contest'?'赛内':'补题'}第${index+1}档 Coins" data-platform-reward="${platform}" data-source="${source}" min="0" max="100000" required value="${value}"></td>`).join('')).join('')}</tr>`).join('')}</tbody></table></div></section>`;
    }).join('');
    container.innerHTML = `
      <form class="currency-config-panel workbench-form">
        <h3>货币系统配置</h3>
        <label class="workbench-check"><input name="currency_enabled" type="checkbox" ${config.currency_enabled ? 'checked' : ''}>启用 RBC 货币系统</label>
        <p class="muted">关闭后，该团队的余额与商店入口会隐藏。</p>
        <fieldset class="currency-config-options" ${config.currency_enabled ? '' : 'hidden disabled'}>
          <label>货币图标（SVG）<input name="currency_icon" type="file" accept=".svg,image/svg+xml"></label>
          ${config.currency_icon ? `<div class="currency-icon-preview"><img src="${escape(config.currency_icon)}" width="32" height="32" alt="当前货币图标"><label class="workbench-check"><input name="remove_icon" type="checkbox">恢复默认图标</label></div>` : ''}
          <label>每日签到奖励 (RBC)<input name="daily_checkin_reward" type="number" min="0" max="100" required value="${config.daily_checkin_reward}"></label>
          <p class="muted">签到和自然周连签全队统一，不区分小登、老登或分队。</p>
          <h4>自然周连签奖励</h4><div class="currency-streak-rules"></div><button type="button" class="secondary-button" data-add-streak>＋ 添加连签奖励</button>
          <label>奖励身份<select name="reward_group">${groupKeys.map(group=>`<option value="${group}">${groupNames[group]}</option>`).join('')}</select></label>
          <p class="muted">小登：入学后的第一个秋季学期（包含次年 1 月）；2 月 15 日起为老登。赛内按比赛开始日期、补题按首次 AC 日期判定，日期未知时按当前日期。各平台赛内和补题奖励分别配置，0 表示不奖励。</p>
          ${rewardMarkup}
        </fieldset>
        <div class="workbench-form-actions"><button type="submit" class="primary-button">保存货币配置</button><span class="currency-config-status" role="status"></span></div>
      </form>`;
    const form = container.querySelector('form');
    const status = container.querySelector('.currency-config-status');
    const options = container.querySelector('fieldset');
    const addRow = rule => {
      const row = document.createElement('div'); row.className='currency-rule-row'; row.dataset.kind='streak';
      row.innerHTML = `<label>连签天数<input class="rule-threshold" aria-label="连签天数" type="number" min="1" max="7" required value="${rule.days}"></label>`;
      row.innerHTML += `<label>奖励 Coins<input class="rule-reward" aria-label="奖励 Coins" type="number" min="1" max="100000" required value="${rule.reward}"></label><button class="text-button" type="button" aria-label="删除奖励规则">删除</button>`;
      row.querySelector('button').onclick=()=>row.remove();
      container.querySelector('.currency-streak-rules').append(row);
    };
    const streaks = config.streak_rewards.length || config.currency_enabled ? config.streak_rewards : [{days:3,reward:1},{days:7,reward:2}];
    streaks.forEach(addRow);
    container.querySelector('[data-add-streak]').onclick=()=>addRow({days:7,reward:2});
    form.elements.reward_group.onchange=()=>{
      container.querySelectorAll('[data-reward-group]').forEach(block=>{block.hidden=block.dataset.rewardGroup!==form.elements.reward_group.value;});
    };
    form.elements.currency_enabled.onchange=()=>{options.hidden=!form.elements.currency_enabled.checked;options.disabled=options.hidden;};
    form.onsubmit=async event=>{
      event.preventDefault(); event.stopPropagation();
      const button=event.submitter; button.disabled=true; status.textContent='正在保存…';
      const payload={team_id:teamId,currency_enabled:form.elements.currency_enabled.checked};
      try {
        if (payload.currency_enabled) {
          payload.daily_checkin_reward=Number(form.elements.daily_checkin_reward.value);
          payload.streak_rewards=[...container.querySelectorAll('[data-kind="streak"]')].map(row=>({days:Number(row.querySelector('.rule-threshold').value),reward:Number(row.querySelector('.rule-reward').value)}));
          payload.reward_settings=Object.fromEntries(Object.keys(groupNames).map(group=>{
            const block=container.querySelector(`[data-reward-group="${group}"]`);
            const settings={};
            for (const source of ['contest','practice']) settings[source+'_rewards']=Object.fromEntries(Object.keys(platforms).map(platform=>{
              const values=[...block.querySelectorAll(`[data-platform-reward="${platform}"][data-source="${source}"]`)].map(input=>Number(input.value));
              return [platform,platform==='qoj'?[values[0],values[0],values[0]]:values];
            }));
            return [group,settings];
          }));
          const file=form.elements.currency_icon.files[0];
          if(file){payload.currency_icon_svg=await file.text();}
          else if(form.elements.remove_icon?.checked)payload.currency_icon_svg=null;
        }
        const response=await window.clubApi.request('/api/currency/admin/config', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error || '保存失败');
        await window.CurrencyModule.init();
        status.textContent='已保存';showToast('货币配置已保存');
        await renderConfigPanel(container,teamId);
      } catch(error){status.textContent=error.message;}
      finally{button.disabled=false;}
    };
  }

  // Render shop management panel
  async function renderShopManagementPanel(container) {
    const items = await loadShopItems();

    container.innerHTML = `
      <div class="shop-management-panel">
        <div class="panel-header">
          <h3>RBC商店管理</h3><button type="button" id="manageCosmetics" class="secondary-button">装扮管理 / 主题包</button>
          <button type="button" id="addShopItem" class="primary-button">+ 添加商品</button>
        </div>

        <div class="shop-items-table">
          <table>
            <thead>
              <tr>
                <th>商品名称</th>
                <th>价格</th>
                <th>库存</th>
                <th>类型</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${items.length === 0 ? '<tr><td colspan="6" class="empty-state">暂无商品</td></tr>' : items.map(item => `
                <tr>
                  <td>${escape(item.name)}</td>
                  <td>${item.price} RBC</td>
                  <td>${item.stock === -1 ? '无限' : item.stock}</td>
                  <td>${({general:'普通商品',makeup_ticket:'补签券',consumable:'消耗品',redeem_code:'核销类',physical:'实物类',title:'称号',badge:'徽章',theme:'主题',frame:'头像框',cosmetic:'装扮套装'})[item.item_type] || escape(item.item_type)}</td>
                  <td>${item.is_active ? '上架' : '下架'}</td>
                  <td>
                    <button type="button" class="toggle-item-btn secondary-button" data-item-id="${item.id}" data-active="${item.is_active}">${item.is_active?'下架':'上架'}</button>
                    <button type="button" class="edit-item-btn" data-item-id="${item.id}">编辑</button>
                    <button type="button" class="delete-item-btn" data-item-id="${item.id}">删除</button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

    container.querySelector("#manageCosmetics").onclick=()=>window.CosmeticStudio.open();
    // Attach handlers
    container.querySelector("#addShopItem").addEventListener("click", () => showItemEditModal());

    container.querySelectorAll(".edit-item-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const itemId = e.target.getAttribute("data-item-id");
        const item = items.find(i => i.id == itemId);
        showItemEditModal(item);
      });
    });

    container.querySelectorAll('.toggle-item-btn').forEach(button=>button.onclick=async()=>{
      button.disabled=true;try{if(await updateShopItem({item_id:Number(button.dataset.itemId),is_active:button.dataset.active!=='true'}))await renderShopManagementPanel(container);}finally{button.disabled=false;}
    });

    container.querySelectorAll(".delete-item-btn").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        const itemId = e.target.getAttribute("data-item-id");
        if (await deleteShopItem(itemId)) {
          renderShopManagementPanel(container);
        }
      });
    });
  }

  // Show item edit modal
  function showItemEditModal(item = null) {
    const isEdit = !!item;

    const modal = document.createElement("div");
    modal.className = "modal-overlay";
    modal.innerHTML = `
      <div class="modal-content">
        <div class="modal-header">
          <h2>${isEdit ? '编辑商品' : '添加商品'}</h2>
          <button class="modal-close" type="button">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>商品名称</label>
            <input type="text" id="itemName" value="${escape(item?.name)}" placeholder="输入商品名称" />
          </div>
          <div class="form-group">
            <label>商品描述</label>
            <textarea id="itemDescription" placeholder="输入商品描述">${escape(item?.description)}</textarea>
          </div>
          <div class="form-group">
            <label>商品图标</label>
            <input type="file" id="itemIcon" accept="image/*" />
            ${item?.icon ? `<div class="current-icon"><img src="${escape(item.icon)}" alt="当前图标" style="max-width: 100px; max-height: 100px; margin-top: 8px;" /><p class="muted">留空保持当前图标</p></div>` : '<p class="muted">可选：上传商品展示图片</p>'}
          </div>
          <div class="form-group">
            <label>价格 (RBC)</label>
            <input type="number" id="itemPrice" value="${item?.price || 1}" min="1" />
          </div>
          <div class="form-group">
            <label>库存 (-1表示无限)</label>
            <input type="number" id="itemStock" value="${item?.stock !== undefined ? item.stock : -1}" />
          </div>
          <div class="form-group">
            <label>商品类型</label>
            <select id="itemType">
              <optgroup label="装扮"><option value="cosmetic" ${item?.item_type==='cosmetic'?'selected':''}>主题 / 徽章 / 头像框 / 自选套装</option><option value="title" ${item?.item_type==='title'?'selected':''}>称号</option>${['theme','badge','frame'].includes(item?.item_type)?`<option value="${item.item_type}" selected>原有${({theme:'主题',badge:'徽章',frame:'头像框'})[item.item_type]}商品</option>`:''}</optgroup>
              <optgroup label="实物与核销"><option value="physical" ${item?.item_type==='physical'?'selected':''}>实物（人工派发）</option><option value="redeem_code" ${item?.item_type==='redeem_code'?'selected':''}>核销卡密（库存 / API / Pro）</option></optgroup>
              <optgroup label="功能道具"><option value="makeup_ticket" ${item?.item_type==='makeup_ticket'?'selected':''}>补签券</option><option value="consumable" ${item?.item_type==='consumable'?'selected':''}>消耗品</option><option value="general" ${!item||item.item_type==='general'?'selected':''}>普通商品</option></optgroup>
            </select>
          </div>
          <div class="form-group" id="itemGiftBadgeField" hidden><label for="itemGiftBadge">赠送永久徽章</label><select id="itemGiftBadge"><option value="">不赠送</option><option value="rbc-pendant" ${item?.gift_badge_key==='rbc-pendant'?'selected':''}>RBC 挂坠纪念徽章</option></select></div>
          <div class="form-group" id="itemPurchaseLimitField" hidden>
            <label for="itemPurchaseLimit">限购数量</label>
            <input type="number" id="itemPurchaseLimit" min="0" max="2147483647" step="1" value="${Number(item?.purchase_limit || 0)}" aria-describedby="itemPurchaseLimitHint" />
            <small id="itemPurchaseLimitHint">每个账号累计可购买的件数，0 表示不限购。已购买、已派送的数量均计入。</small>
          </div>
          <section id="shopCosmeticFields" class="shop-title-fields" hidden><label>外观内容<select id="shopCosmeticKey"><option value="${escape(item?.cosmetic_key||'taffy')}">塔菲</option></select></label><div class="cosmetic-stock-preview"><img src="/static/cosmetics/taffy-original-head.svg" alt="小塔菲徽章"><p id="shopCosmeticHint"></p></div></section>
          <section id="shopTitleFields" class="shop-title-fields" hidden>
            <label for="shopTitleText">称号文字<input id="shopTitleText" maxlength="20" value="${escape(item?.title_definition?.text || '')}" placeholder="例如：算法新星"></label>
            <div class="shop-title-options"><label>颜色<input id="shopTitleColor" type="color" value="${escape(item?.title_definition?.color || '#c96c7a')}"></label><label>字体<select id="shopTitleFont">${Object.entries({system:'默认黑体',serif:'典雅宋体',kai:'手写楷体',mono:'等宽字体',rounded:'圆润字体'}).map(([key,label])=>`<option value="${key}" ${item?.title_definition?.font===key?'selected':''}>${label}</option>`).join('')}</select></label><label>样式<select id="shopTitleStyle">${Object.entries(window.MemberTitles?.styles || {plain:'简约'}).map(([key,label])=>`<option value="${key}" ${(item?.title_definition?.style||'plain')===key?'selected':''}>${label}</option>`).join('')}</select></label></div>
            <div id="shopTitlePreview" class="shop-title-preview" aria-live="polite"></div><small>所有已加入团队可选佩戴；有效期内不可重复购买。</small>
          </section>
          <section id="cosmeticDurationFields" class="shop-title-fields" hidden>
            <label>有效时长<select id="cosmeticTermMode"><option value="permanent">永久</option><option value="days" ${item?.cosmetic_duration_days?'selected':''}>指定天数</option></select></label>
            <label id="cosmeticDaysField">天数<input id="cosmeticDays" type="number" min="1" max="36500" step="1" value="${Number(item?.cosmetic_duration_days||30)}"></label>
          </section>
          <div id="cardSourceFields" hidden>
            <div class="form-group"><label for="itemCardSource">卡密来源</label><select id="itemCardSource"><option value="inventory" ${!item?.card_source || item.card_source === 'inventory' ? 'selected' : ''}>库存类</option><option value="api" ${item?.card_source === 'api' ? 'selected' : ''}>API 类</option><option value="pro" ${item?.card_source === 'pro' ? 'selected' : ''}>内部 Pro 卡密</option></select></div>
            <div id="cardProFields" hidden><div class="form-group"><label for="itemProApp">Pro 应用</label><select id="itemProApp"><option value="">请选择应用</option><option value="rbc_helper" ${item?.pro_app === 'rbc_helper' ? 'selected' : ''}>RBC Helper</option></select></div><div class="form-group"><label for="itemProDays">每张卡密时长（天）</label><input id="itemProDays" type="number" min="1" max="36500" step="1" value="${Number(item?.pro_duration_days || 31)}"><small>背包领取后生成卡密；App 验证后占用卡密 30 秒，收到激活完成回执才作废；超时未确认则释放。购买时保存时长快照。库存仍按上方设置，0 表示暂不可购买。</small></div></div>
            <div class="form-group" id="cardStockFields"><label>追加卡密（每行一个）</label><textarea id="itemCardCodes" rows="6" autocomplete="off" placeholder="每行填写一条卡密"></textarea><small>可分配卡密：${Number(item?.available_codes || 0)}。已预留、已核销的卡密会保留；重复卡密不重复入库。</small></div>
            <div class="form-group" id="cardMultiplePurchaseField" hidden>
              <label class="card-multiple-label" for="itemAllowMultiplePurchase"><input class="shop-toggle" id="itemAllowMultiplePurchase" type="checkbox" ${item?.allow_multiple_purchase ? 'checked' : ''} aria-describedby="itemMultiplePurchaseHint" />允许单次多购</label>
              <small id="itemMultiplePurchaseHint">购买数量合并为一张卡密的可用次数，按单价 × 数量扣款，核销时发送 num。每次最多购买 100 件。</small>
            </div>
            <div class="form-group" id="cardApiFields"><label>API 配置（JSON）</label><textarea id="itemCardApi" rows="8" autocomplete="off" spellcheck="false" placeholder='{"url":"https://example.com/cards","method":"POST","headers":{},"body":{},"response_path":"data.code"}'></textarea><small>${item?.has_card_api ? '已有配置，留空保留。' : ''}配置会加密保存。接口需识别 Idempotency-Key 请求头，避免重试重复发卡。</small></div>
          </div>
          <div class="form-group">
            <label>
              <input type="checkbox" id="itemActive" ${item?.is_active !== false ? 'checked' : ''} />
              上架销售
            </label>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="secondary-button modal-cancel">取消</button>
          <button type="button" class="primary-button modal-save">保存</button>
        </div>
      </div>
    `;

    document.body.appendChild(modal);
    window.CosmeticStudio.mountShop(modal,item);
    const updateTerm=()=>{modal.querySelector('#cosmeticDurationFields').hidden=!['title','theme'].includes(modal.querySelector('#itemType').value);modal.querySelector('#cosmeticDaysField').hidden=modal.querySelector('#cosmeticTermMode').value!=='days';};
    modal.querySelector('#itemType').addEventListener('change',updateTerm);modal.querySelector('#cosmeticTermMode').addEventListener('change',updateTerm);updateTerm();
    let giftOptionsLoaded=false;
    const updateCosmeticFields=()=>{
      const kind=modal.querySelector('#itemType').value;modal.querySelector('#shopCosmeticFields').hidden=!['badge','theme','frame'].includes(kind);
      const select=modal.querySelector('#shopCosmeticKey'),current=select.value||item?.cosmetic_key||'';
      const choices=(modal.assetCatalog||[]).filter(a=>a.kind===kind);
      if(choices.length){select.innerHTML=choices.map(a=>`<option value="${escape(a.key)}">${escape(a.name)}</option>`).join('');select.value=choices.some(a=>a.key===current)?current:choices[0].key;}
      modal.querySelector('#shopCosmeticHint').textContent='选择资源库中的装扮';
      const resource=choices.find(a=>a.key===select.value),picture=modal.querySelector('.cosmetic-stock-preview img');
      const image=resource?.poster||resource?.icon;picture.hidden=!window.CosmeticMedia.safe(image);if(!picture.hidden){picture.src=image;picture.alt=resource.name;}
      select.onchange=updateCosmeticFields;
      const gift=modal.querySelector('#itemGiftBadge');if(modal.assetCatalog){const value=giftOptionsLoaded?gift.value:(item?.gift_badge_key||gift.value);gift.innerHTML='<option value="">不赠送</option>'+modal.assetCatalog.filter(a=>a.kind==='badge'&&(a.is_active||a.key===value)).map(a=>`<option value="${escape(a.key)}">${escape(a.name)}</option>`).join('');gift.value=value;giftOptionsLoaded=true;}
    };
    modal.querySelector('#itemType').addEventListener('change',updateCosmeticFields);updateCosmeticFields();
    const titleDefinition=()=>({text:modal.querySelector('#shopTitleText').value.trim(),color:modal.querySelector('#shopTitleColor').value,font:modal.querySelector('#shopTitleFont').value,style:modal.querySelector('#shopTitleStyle').value});
    const updateTitlePreview=()=>{modal.querySelector('#shopTitleFields').hidden=modal.querySelector('#itemType').value!=='title';modal.querySelector('#shopTitlePreview').innerHTML=window.MemberTitles?.markup(titleDefinition())||'<span class="muted">预览称号</span>';};
    modal.querySelector('#shopTitleFields').addEventListener('input',updateTitlePreview);
    modal.querySelector('#shopTitleFields').addEventListener('change',updateTitlePreview);
    modal.querySelector('#itemType').addEventListener('change',updateTitlePreview);updateTitlePreview();
    const updateLimitField=()=>{const physical=modal.querySelector('#itemType').value==='physical';modal.querySelector('#itemGiftBadgeField').hidden=!physical;modal.querySelector('#itemPurchaseLimitField').hidden=!physical;};
    modal.querySelector('#itemType').addEventListener('change',updateLimitField);updateLimitField();
    const updateCardFields=()=>{const redeem=modal.querySelector('#itemType').value==='redeem_code';modal.querySelector('#cardSourceFields').hidden=!redeem;const source=modal.querySelector('#itemCardSource').value;modal.querySelector('#cardStockFields').hidden=source!=='inventory';modal.querySelector('#cardApiFields').hidden=source!=='api';modal.querySelector('#cardMultiplePurchaseField').hidden=!redeem||source!=='api';modal.querySelector('#cardProFields').hidden=source!=='pro';};
    modal.querySelector('#itemType').addEventListener('change',updateCardFields);modal.querySelector('#itemCardSource').addEventListener('change',updateCardFields);updateCardFields();

    // Close handlers
    modal.querySelector(".modal-close").addEventListener("click", () => modal.remove());
    modal.querySelector(".modal-cancel").addEventListener("click", () => modal.remove());

    // Save handler
    modal.querySelector(".modal-save").addEventListener("click", async event => {
      const saveButton=event.currentTarget;
      if(saveButton.disabled)return;
      saveButton.disabled=true;
      try {
      const iconFile = document.getElementById("itemIcon").files[0];
      let iconData = null;

      // Convert image to base64 if provided
      if (iconFile) {
        try {
          iconData = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => resolve(e.target.result);
            reader.onerror = reject;
            reader.readAsDataURL(iconFile);
          });
        } catch (error) {
          alert("图片读取失败");
          return;
        }
      }

      const itemData = {
        name: document.getElementById("itemName").value.trim(),
        description: document.getElementById("itemDescription").value.trim(),
        price: parseInt(document.getElementById("itemPrice").value),
        stock: parseInt(document.getElementById("itemStock").value),
        item_type: document.getElementById("itemType").value,
        gift_badge_key: modal.querySelector('#itemType').value==='physical'?modal.querySelector('#itemGiftBadge').value:'',
        purchase_limit: document.getElementById('itemType').value==='physical' ? Number(document.getElementById('itemPurchaseLimit').value) : 0,
        is_active: document.getElementById("itemActive").checked,
        allow_multiple_purchase: modal.querySelector('#itemType').value==='redeem_code' && modal.querySelector('#itemCardSource').value==='api' && modal.querySelector('#itemAllowMultiplePurchase').checked,
      };

      if(!Number.isInteger(itemData.purchase_limit)||itemData.purchase_limit<0||itemData.purchase_limit>2147483647){alert('限购数量必须为0（不限购）或正整数');return;}
      itemData.cosmetic_duration_days=['title','theme','badge','frame'].includes(itemData.item_type)&&modal.querySelector('#cosmeticTermMode').value==='days'?Number(modal.querySelector('#cosmeticDays').value):0;
      if(!Number.isInteger(itemData.cosmetic_duration_days)||itemData.cosmetic_duration_days<0||itemData.cosmetic_duration_days>36500||(modal.querySelector('#cosmeticTermMode').value==='days'&&['title','theme','badge','frame'].includes(itemData.item_type)&&itemData.cosmetic_duration_days===0)){alert('请填写 1–36500 天的整数时长');return;}
      if(['badge','theme','frame'].includes(itemData.item_type))itemData.cosmetic_key=modal.querySelector('#shopCosmeticKey').value;
      if(itemData.item_type==='cosmetic'){itemData.cosmetic_bundle=modal.cosmeticComponents;if(!itemData.cosmetic_bundle?.length){alert('请选择至少一项装扮资源');return;}}
      if(itemData.item_type==='title'){itemData.title_definition=titleDefinition();if(!itemData.title_definition.text){alert('请填写称号文字');return;}}
      if(itemData.item_type==='redeem_code'){
        itemData.card_source=modal.querySelector('#itemCardSource').value;
        if(itemData.card_source==='pro'){
          itemData.pro_app=modal.querySelector('#itemProApp').value;
          itemData.pro_duration_days=Number(modal.querySelector('#itemProDays').value);
          if(!itemData.pro_app||!Number.isInteger(itemData.pro_duration_days)||itemData.pro_duration_days<1||itemData.pro_duration_days>36500){alert('请选择 Pro 应用并填写 1–36500 天的整数时长');return;}
        }else{
          if(itemData.card_source==='inventory')itemData.card_codes=modal.querySelector('#itemCardCodes').value;
          const config=modal.querySelector('#itemCardApi').value.trim();
          if(itemData.card_source==='api'&&config){try{itemData.card_api=JSON.parse(config);}catch{alert('API 配置不是有效 JSON');return;}}
        }
      }
      if (iconData) {
        itemData.icon = iconData;
      }

      if (!itemData.name) {
        alert("请输入商品名称");
        return;
      }

      if (isEdit) {
        itemData.item_id = item.id;
        if (await updateShopItem(itemData)) {
          modal.remove();
          // Refresh shop management panel
          const container = document.querySelector(".shop-management-panel")?.parentElement;
          if (container) {
            renderShopManagementPanel(container);
          }
        }
      } else {
        if (await createShopItem(itemData)) {
          modal.remove();
          // Refresh shop management panel
          const container = document.querySelector(".shop-management-panel")?.parentElement;
          if (container) {
            renderShopManagementPanel(container);
          }
        }
      }
      } finally {saveButton.disabled=false;}
    });
  }

  function showBalanceAdjustment(member) {
    const modal=document.createElement('div'); modal.className='modal-overlay';
    modal.innerHTML=`<form class="modal-content currency-adjust-modal" role="dialog" aria-modal="true" aria-label="调整 RBC 余额"><div class="modal-header"><h2>调整 ${escape(member.name)} 的余额</h2><button type="button" class="modal-close" aria-label="关闭">×</button></div><div class="modal-body"><p>当前余额：${member.currency_balance} RBC</p><label>调整金额（正数增加，负数扣除，可扣至负余额）<input name="amount" type="number" min="-100000" max="100000" required></label><label>调整说明<input name="description" maxlength="200" value="管理员调整" required></label><p role="status"></p></div><div class="modal-footer"><button class="primary-button" type="submit">确认调整</button></div></form>`;
    document.body.append(modal);modal.querySelector('.modal-close').onclick=()=>modal.remove();
    modal.querySelector('form').onsubmit=async event=>{
      event.preventDefault();const form=event.target, button=event.submitter;button.disabled=true;
      try {
        const response=await window.clubApi.request('/api/currency/admin/adjust',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({member_id:member.id,amount:Number(form.elements.amount.value),description:form.elements.description.value})});
        const result=await response.json();if(!response.ok)throw new Error(result.error || '调整失败');
        modal.remove();await loadMembersLive();await window.CurrencyModule.init();showToast(`余额已更新为 ${result.new_balance} RBC`);
      } catch(error){modal.querySelector('[role="status"]').textContent=error.message;} finally{button.disabled=false;}
    };
    modal.querySelector('[name="amount"]').focus();
  }

  // Public API
  return {
    loadConfig,
    saveConfig,
    adjustBalance,
    showBalanceAdjustment,
    renderConfigPanel,
    renderShopManagementPanel,
  };
})();

// Export for use in other modules
if (typeof window !== "undefined") {
  window.CurrencyAdminModule = CurrencyAdminModule;
}
