/* Multiplayer and practice Hold'em. All deals, actions and balances are server-owned. */
(() => {
  const root = document.getElementById('pokerView');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const count = value => Number(value || 0).toLocaleString('zh-CN');
  const streets = {waiting:'等待准备', preflop:'翻牌前', flop:'翻牌', turn:'转牌', river:'河牌', finished:'本手结束'};
  let enabled = false, generation = 0, timer, roomId = null, state = null, lobby = null;
  let busy = false, loading = false, notice = '', serverOffset = 0;
  async function api(path, data) {
    const response = await clubApi.request('/api/poker/rooms' + path, data ? {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data),
    } : {cache:'no-store'});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || '连接失败，请重试');
    return payload;
  }
  function apply(payload) {
    state = payload;
    if (window.CurrencyModule?.getCurrencyData().balance !== payload.balance) window.CurrencyModule?.syncBalance(payload.balance);
    if (payload.server_time) serverOffset = payload.server_time * 1000 - Date.now();
  }
  function heading(subtitle, balance) {
    return `<div class="poker-extension-nav"><button class="secondary-button" type="button" data-extensions>← 返回拓展</button></div><section class="page-heading"><div><p class="kicker">RBC POKER CLUB</p><h1>德州扑克</h1><p>${esc(subtitle)}</p></div><div class="poker-wallet"><small>RBC Coins 钱包</small><strong>${count(balance)}</strong></div></section>`;
  }
  function alertMarkup() {
    return `<p class="poker-notice" role="status" aria-live="polite">${esc(notice)}</p>`;
  }
  function drawLobby() {
    root.innerHTML = heading('与队友同桌，或用赠送筹码练习。', lobby.balance) + alertMarkup() + `
      ${lobby.current_room ? '<div class="poker-resume"><span>你仍在一张牌桌中，筹码会保留至离桌结算。</span><button class="primary-button" data-resume>返回当前牌桌</button></div>' : ''}
      ${lobby.seated_elsewhere ? '<p class="poker-notice">你在其他团队仍有座位，请切回对应团队离桌后再加入。</p>' : ''}
      <div class="poker-modes">
        <article class="panel poker-mode"><span class="poker-mode-icon" aria-hidden="true">♠</span><div><p class="kicker">MULTIPLAYER</p><h2>多人联机</h2><p>2–9 人同桌 · 多房间 · 无限注</p><small>使用 RBC Coins 买入，离桌按剩余筹码结算。</small></div><button class="primary-button" data-create="coins" ${!lobby.enabled || lobby.current_room || lobby.seated_elsewhere ? 'disabled' : ''}>创建房间</button>${!lobby.enabled ? '<small>当前团队尚未启用 RBC Coins</small>' : ''}</article>
        <article class="panel poker-mode poker-mode-friendly"><span class="poker-mode-icon" aria-hidden="true">♣</span><div><p class="kicker">PLAY WITH FRIENDS</p><h2>多人练习</h2><p>2–9 人同桌 · 每人赠送 1,000 筹码</p><small>免费和队友联机，不使用真实 Coins，不计收入。</small></div><button class="primary-button" data-create="friendly" ${lobby.current_room || lobby.seated_elsewhere ? 'disabled' : ''}>创建练习房间</button></article>
        <article class="panel poker-mode poker-mode-practice"><span class="poker-mode-icon" aria-hidden="true">♧</span><div><p class="kicker">PRACTICE</p><h2>人机练习</h2><p>1–5 个机器人 · 赠送 1,000 筹码</p><small>练习筹码不可兑换，不计收入，不影响钱包。</small></div><button class="secondary-button" data-create="practice" ${lobby.current_room || lobby.seated_elsewhere ? 'disabled' : ''}>开始练习</button></article>
      </div>
      <div class="poker-list-heading"><h2>房间大厅</h2><button class="secondary-button" data-refresh>刷新</button></div>
      <div class="poker-rooms">${lobby.rooms.length ? lobby.rooms.map(room => `<article class="panel poker-room-card"><div class="poker-room-title"><h3>${esc(room.name)}</h3><span class="poker-badge">${room.mode === 'practice' ? '人机练习' : room.mode === 'friendly' ? '多人练习' : room.playing ? '对局中' : '等待中'}</span></div><p>${room.players} / ${room.max_players} 人 · 盲注 ${room.big_blind / 2} / ${room.big_blind}</p><strong>${count(room.buy_in)} <small>${room.mode !== 'coins' ? '赠送筹码' : 'RBC Coins 买入'}</small></strong><button class="secondary-button" data-room="${esc(room.id)}">${room.id === lobby.current_room ? '返回牌桌' : '查看房间'}</button></article>`).join('') : '<div class="panel poker-empty"><span aria-hidden="true">♠ ♥ ♣ ♦</span><h3>还没有房间</h3><p>邀请队友创建第一张牌桌，或先来一局人机练习。</p></div>'}</div>
      <details class="panel poker-rules"><summary>玩法与结算说明</summary><p>每人两张底牌，搭配五张公共牌组成最好的五张牌。所有玩家准备后开局，依次完成翻牌前、翻牌、转牌、河牌下注。支持过牌、跟注、加注、弃牌和全下，自动处理边池与平局分池。</p><p>每次行动限时 45 秒，超时自动过牌或弃牌。进行中的对局可以排队离桌，本手结束后结算；全下后仍参加本手比牌。断开页面超过 5 分钟将自动离桌，重新进入可恢复仍在的座位。Coins 多人局买入和离桌会生成钱包流水；多人练习与人机局仅使用赠送筹码，退出时不计入钱包。</p></details>`;
    root.querySelectorAll('[data-create]').forEach(button => button.onclick = () => createDialog(button.dataset.create));
    root.querySelectorAll('[data-room]').forEach(button => button.onclick = () => enter(button.dataset.room));
    root.querySelector('[data-resume]')?.addEventListener('click', () => enter(lobby.current_room));
    root.querySelector('[data-refresh]').onclick = () => refresh(true);
  }
  function cards(values, hiddenCount = 0) {
    return [...values.map(value => {
      const rank = value.slice(0, -1), suit = value.slice(-1), symbol = {s:'♠',h:'♥',d:'♦',c:'♣'}[suit];
      const label = {11:'J',12:'Q',13:'K',14:'A'}[rank] || rank;
      return `<span class="poker-card ${suit === 'h' || suit === 'd' ? 'poker-card-red' : ''}" aria-label="${esc(label + symbol)}"><b>${esc(label)}</b><span>${symbol}</span></span>`;
    }), ...Array.from({length:hiddenCount}, () => '<span class="poker-card poker-card-back" aria-label="隐藏底牌">♠</span>')].join('');
  }
  function updateClock() {
    const element = root.querySelector('[data-clock]');
    if (element && state?.room.deadline) element.textContent = Math.max(0, Math.ceil((state.room.deadline * 1000 - Date.now() - serverOffset) / 1000)) + ' 秒';
  }
  function seatPosition(number, anchor, capacity) {
    const index = (number - anchor + capacity) % capacity;
    const angle = index * Math.PI * 2 / capacity;
    const x = (50 + 36 * Math.sin(angle)).toFixed(3), y = (50 + 38 * Math.cos(angle)).toFixed(3);
    const compact = {
      8: [[50,88],[85,76],[86,50],[85,24],[50,12],[15,24],[14,50],[15,76]],
      9: [[50,88],[84,80],[86,58],[86,34],[76,12],[24,12],[14,34],[14,58],[16,80]],
    }[capacity]?.[index] || [x,y];
    return `--seat-x:${x}%;--seat-y:${y}%;--seat-mobile-x:${compact[0]}%;--seat-mobile-y:${compact[1]}%`;
  }
  function drawRoom() {
    const {room, user_id:userId, balance} = state;
    const uid = String(userId), me = room.seats.find(s => s.user_id === uid), practice = room.mode === 'practice', gifted = room.mode !== 'coins';
    const playing = !['waiting','finished'].includes(room.street), actions = room.actions;
    const actor = room.seats.find(s => s.user_id === room.actor);
    const currency = gifted ? '练习筹码' : 'RBC Coins';
    const payouts = room.result ? Object.entries(room.result.payouts).filter(([,amount]) => amount > 0).map(([id, amount]) => `${room.seats.find(s => s.user_id === id)?.name || '已离桌玩家'} +${count(amount)}`).join(' · ') : '';
    root.innerHTML = heading(practice ? '人机练习 · 赠送筹码不计收入、不影响钱包' : gifted ? '多人练习 · 赠送筹码不计收入、不影响钱包' : '多人联机 · RBC Coins 买入与结算', balance) + alertMarkup() + `
      <div class="poker-toolbar"><button class="secondary-button" data-lobby>← 房间大厅</button><div><h2>${esc(room.name)}</h2><small>第 ${room.hand_number} 手 · 盲注 ${room.big_blind / 2} / ${room.big_blind} · ${room.seats.length}/${room.max_players} 人</small></div><span class="poker-badge">${gifted ? practice ? '人机练习' : '多人练习' : 'RBC Coins 多人局'}</span></div>
      <div class="poker-table" style="--seat-count:${room.max_players}" role="group" aria-label="玩家环绕牌桌"><div class="poker-felt"><div class="poker-community"><p class="poker-table-brand">RBC POKER</p><span class="poker-street">${streets[room.street]}</span><div class="poker-board">${cards(room.board)}${Array.from({length:5-room.board.length}, () => '<span class="poker-card poker-card-slot" aria-hidden="true"></span>').join('')}</div><div class="poker-pot"><small>${room.street === 'finished' ? '本手底池（已分配）' : '底池'}</small><strong>${count(room.pot)}</strong><span>${currency}</span></div>${playing ? `<p class="poker-turn">${esc(actor?.name || '')} 操作中 <strong data-clock></strong></p>` : '<p class="poker-turn">准备就绪，开始下一手</p>'}</div></div>
      <div class="poker-seats">${Array.from({length:room.max_players}, (_,number) => {
        const seat = room.seats.find(s => s.number === number);
        const position = seatPosition(number, me?.number ?? 0, room.max_players);
        if (!seat) return `<div class="poker-seat poker-seat-empty" style="${position}" data-seat="${number}"><small>座位 ${number+1}</small><span>等待入座</span></div>`;
        const own = seat.user_id === uid;
        return `<article class="poker-seat ${seat.user_id === room.actor ? 'poker-seat-turn' : ''} ${seat.folded && playing ? 'poker-seat-folded' : ''} ${own ? 'poker-seat-own' : ''}" style="${position}" data-seat="${number}"><div class="poker-seat-name"><strong>${esc(seat.name)}${own ? '（你）' : ''}</strong><span>${room.dealer === number ? '<b class="poker-dealer" title="庄家">D</b>' : ''}${seat.is_bot ? '🤖' : ''}</span></div><div class="poker-hole">${cards(seat.cards, Math.max(0, seat.card_count - seat.cards.length))}</div><strong>${count(seat.stack)} <small>筹码</small></strong><small>${seat.leaving ? '本手结束后离桌' : playing && seat.in_hand ? seat.folded ? '已弃牌' : seat.stack === 0 ? '已全下' : seat.bet ? `本轮下注 ${count(seat.bet)}` : '在局中' : seat.ready ? '已准备' : seat.stack ? '等待准备' : '筹码不足'}</small></article>`;
      }).join('')}</div></div>
      ${room.result ? `<div class="poker-result" role="status"><strong>本手已结算</strong><span>${esc(payouts)}</span>${room.result.showdown ? `<small>${Object.entries(room.result.hands).map(([id, hand]) => esc((room.seats.find(s => s.user_id === id)?.name || '已离桌玩家') + '：' + hand)).join(' · ')}</small>` : '<small>其余玩家弃牌</small>'}</div>` : ''}
      <section class="panel poker-controls" aria-label="牌局操作">${room.closed ? '<p>房间已关闭，剩余筹码已按模式结算。</p>' : me ? `
        <div class="poker-control-info"><strong>${actions ? '轮到你了' : me.leaving ? playing ? '已申请离桌' : '钱包余额接近上限，请腾出余额后重试结算' : playing ? '等待其他玩家操作' : '准备开始下一手'}</strong><small>${gifted ? '仅限练习，输赢均不计收入' : `在桌筹码 ${count(me.stack)} RBC Coins`}</small></div><div class="poker-action-buttons">
        ${actions && !me.leaving ? `<button class="secondary-button" data-action="fold">弃牌</button><button class="primary-button" data-action="${actions.check ? 'check' : 'call'}">${actions.check ? '过牌' : `跟注 ${count(actions.call)}`}</button>${actions.raise ? `<label class="poker-raise-label">加注至<input data-raise type="number" step="1" min="${Math.min(actions.min_raise_to, actions.max_raise_to)}" max="${actions.max_raise_to}" value="${Math.min(actions.min_raise_to, actions.max_raise_to)}" aria-label="本轮加注至总额"></label><button class="primary-button" data-action="raise">加注</button>` : ''}${actions.all_in ? '<button class="secondary-button poker-allin" data-action="all_in">全下</button>' : ''}` : !playing && !me.leaving ? (me.stack > 0 ? `<button class="primary-button" data-action="ready">${me.ready ? '取消准备' : '准备'}</button>` : gifted ? '<button class="primary-button" data-action="refill">领取 1,000 练习筹码</button>' : '<span>筹码用完，请离桌后重新买入</span>') : ''}
        ${!me.leaving || !playing ? `<button class="secondary-button" data-leave>${me.leaving ? '重试结算' : playing && me.in_hand ? '申请离桌' : gifted ? '离开练习桌' : '结算离桌'}</button>` : ''}</div>` : `<p>${practice ? '这是个人练习房间' : gifted ? '免费领取 1,000 练习筹码入座，下一手开始参加对局。' : `买入 ${count(room.buy_in)} RBC Coins 加入，进行中的牌局将在下一手为你发牌。`}</p>${!practice ? `<button class="primary-button" data-action="join" ${room.seats.length >= room.max_players ? 'disabled' : ''}>${room.seats.length >= room.max_players ? '房间已满' : gifted ? '免费领取筹码并入座' : `买入 ${count(room.buy_in)} 并入座`}</button>` : ''}`}</section>
      <div class="poker-footnote"><span>行动限时 45 秒，超时自动过牌或弃牌。断线 5 分钟自动申请离桌。</span>${gifted ? '<span>赠送筹码不会计入余额、收入或排行榜。</span>' : '<span>全下后申请离桌仍保留本手比牌资格，手牌结束后退回剩余筹码。</span>'}</div>
      <details class="panel poker-history"><summary>本手行动记录</summary><ol>${room.log.map(line => `<li>${esc(line)}</li>`).join('') || '<li>等待开局</li>'}</ol></details>`;
    root.querySelector('[data-lobby]').onclick = () => { roomId = null; state = null; notice = ''; refresh(true); };
    root.querySelectorAll('[data-action]').forEach(button => button.onclick = () => {
      const action = button.dataset.action;
      const amount = action === 'raise' ? Number(root.querySelector('[data-raise]').value) : undefined;
      if (action === 'raise' && (!Number.isInteger(amount) || amount < Math.min(actions.min_raise_to, actions.max_raise_to) || amount > actions.max_raise_to)) {
        notice = '请填写有效的加注总额'; root.querySelector('.poker-notice').textContent = notice; return;
      }
      run(action, amount);
    });
    root.querySelector('[data-leave]')?.addEventListener('click', leaveDialog);
    updateClock();
  }
  async function run(action, amount) {
    if (busy || !state) return;
    busy = true; const token = generation, id = roomId;
    root.querySelectorAll('.poker-controls button').forEach(button => button.disabled = true);
    try {
      const ready = action === 'ready' ? !state.room.seats.find(s => s.user_id === String(state.user_id))?.ready : undefined;
      const payload = await api('/' + id, {action, amount, ready, hand_number:state.room.hand_number, version:state.room.version});
      if (token !== generation || id !== roomId) return;
      apply(payload); notice = action === 'leave' ? (state.room.seats.some(s => s.user_id === String(state.user_id)) ? '离桌申请已提交，将在本手结束后结算。' : '已离桌结算。') : '';
      if (action === 'leave' && !state.room.seats.some(s => s.user_id === String(state.user_id))) { roomId = null; state = null; }
    } catch (error) { if (token === generation) notice = error.message; }
    finally {
      busy = false;
      if (token === generation && enabled) {
        if (state && roomId) drawRoom();
        await refresh(true);
      }
    }
  }
  function dialog(content) {
    const element = document.createElement('dialog'); element.className = 'extension-dialog poker-dialog';
    element.innerHTML = content; document.body.append(element);
    element.addEventListener('close', () => element.remove()); element.showModal();
    element.querySelector('[data-cancel]').onclick = () => element.close();
    return element;
  }
  function leaveDialog() {
    const gifted = state.room.mode !== 'coins';
    const element = dialog(`<h2>${gifted ? '离开练习桌' : '结算离桌'}</h2><p>${gifted ? '赠送筹码在退出后作废，不计收入。' : '剩余筹码将返还到 RBC Coins 钱包。'} 若你正在本手中，将在本手结束后离桌；全下仍参加比牌。</p><div class="extension-actions"><button class="secondary-button" data-cancel>取消</button><button class="primary-button" data-confirm>确认离桌</button></div>`);
    element.querySelector('[data-confirm]').onclick = () => { element.close(); run('leave'); };
  }
  function createDialog(mode) {
    const practice = mode === 'practice', gifted = mode !== 'coins';
    const capacity = '<label>房间人数<select name="max_players"><option>2</option><option>3</option><option>4</option><option>5</option><option selected>6</option><option>7</option><option>8</option><option>9</option></select></label>';
    const bots = '<label>机器人数量<select name="bot_count"><option value="1">1 个</option><option value="2">2 个</option><option value="3" selected>3 个</option><option value="4">4 个</option><option value="5">5 个</option></select></label>';
    const giftNotice = '<p>每人赠送 1,000 练习筹码，盲注 5 / 10；筹码用完可重新领取，不计收入，不影响 RBC Coins 钱包。</p>';
    const coinFields = '<label>盲注（小盲 / 大盲）<select name="big_blind"><option value="2">1 / 2</option><option value="4">2 / 4</option><option value="10">5 / 10</option><option value="20">10 / 20</option><option value="50">25 / 50</option><option value="100">50 / 100</option></select></label><label>每人买入（RBC Coins）<input name="buy_in" type="number" min="2" max="200" step="1" value="10" required><small>默认买入仅 10 Coins；最低 1 倍大盲注。确认后扣除买入金额并入座。</small></label>';
    const element = dialog(`<form class="extension-form"><h2>${practice ? '创建人机练习' : gifted ? '创建多人练习' : '创建 Coins 房间'}</h2><label>房间名称<input name="name" maxlength="40" required value="${practice ? '我的练习桌' : ''}" placeholder="给牌桌起个名字"></label>${practice ? bots : capacity}${gifted ? giftNotice : coinFields}<p role="alert"></p><div class="extension-actions"><button class="secondary-button" type="button" data-cancel>取消</button><button class="primary-button" type="submit">${gifted ? '免费领取筹码并创建' : '确认买入并创建'}</button></div></form>`);
    const form = element.querySelector('form');
    form.elements.big_blind?.addEventListener('change', () => {
      const blind = Number(form.elements.big_blind.value);
      form.elements.buy_in.min = blind; form.elements.buy_in.max = blind * 100; form.elements.buy_in.value = blind * 5;
    });
    let submitting = false;
    element.addEventListener('cancel', event => { if (submitting) event.preventDefault(); });
    form.onsubmit = async event => {
      event.preventDefault(); if (submitting) return;
      submitting = true; const token = generation;
      form.querySelectorAll('button').forEach(button => button.disabled = true);
      const data = {name:form.elements.name.value, mode};
      for (const key of ['bot_count','max_players','big_blind','buy_in']) if (form.elements[key]) data[key] = Number(form.elements[key].value);
      try {
        const payload = await api('', data); element.close();
        if (token !== generation || !enabled) return;
        roomId = payload.room.id; apply(payload); notice = ''; drawRoom();
      } catch (error) { form.querySelector('[role=alert]').textContent = error.message; }
      finally { submitting = false; form.querySelectorAll('button').forEach(button => button.disabled = false); }
    };
  }
  async function enter(id) {
    roomId = id; state = null; notice = ''; generation++;
    await refresh(true);
  }
  async function refresh(force = false, resume = false) {
    if (!enabled || busy || loading) return;
    loading = true; const token = generation, id = roomId;
    try {
      if (id) {
        const payload = await api('/' + id);
        if (token !== generation || !enabled) return;
        const changed = force || !state || state.room.version !== payload.room.version || state.balance !== payload.balance;
        apply(payload);
        if (changed) drawRoom(); else updateClock();
      } else {
        const payload = await api('');
        if (token !== generation || !enabled) return;
        const changed = force || JSON.stringify(lobby) !== JSON.stringify(payload);
        lobby = payload;
        if (resume && lobby.current_room) { roomId = lobby.current_room; state = null; }
        else if (changed) drawLobby();
      }
    } catch (error) {
      if (token !== generation || !enabled) return;
      notice = error.message;
      const alert = root.querySelector('.poker-notice');
      if (alert) alert.textContent = notice;
      else {
        root.innerHTML = heading('连接牌桌', 0) + alertMarkup() + '<button class="secondary-button" data-retry>重试</button>';
        root.querySelector('[data-retry]').onclick = () => refresh(true);
      }
    } finally { loading = false; }
  }
  function activate(value) {
    enabled = value; generation++; clearInterval(timer);
    if (!value) return;
    roomId = null; state = null; lobby = null; notice = '';
    root.innerHTML = '<p role="status">正在连接牌桌…</p>';
    refresh(true, true);
    timer = setInterval(() => refresh(), 1500);
  }
  function close() {
    activate(false);
    root.hidden = true;
    document.getElementById('extensionResources').hidden = false;
  }
  function open() {
    document.getElementById('extensionResources').hidden = true;
    root.hidden = false;
    const url = new URL(location.href);
    url.searchParams.set('view', 'extensions');
    history.replaceState(null, '', url);
    activate(true);
    window.scrollTo({top:0, behavior:'smooth'});
  }
  root.addEventListener('click', event => {
    if (event.target.closest('[data-extensions]')) close();
  });
  window.PokerModule = {open, close};
})();
