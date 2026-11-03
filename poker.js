/* Multiplayer and practice Hold'em. All deals, actions and balances are server-owned. */
(() => {
  const root = document.getElementById('pokerView');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const count = value => Number(value || 0).toLocaleString('zh-CN');
  const handRankHelp = '<p>牌型大小（从大到小）：皇家同花顺 ＞ 同花顺 ＞ 四条 ＞ 葫芦 ＞ 同花 ＞ 顺子 ＞ 三条 ＞ 两对 ＞ 一对 ＞ 高牌。</p>';
  const streets = {waiting:'等待准备', preflop:'翻牌前', flop:'翻牌', turn:'转牌', river:'河牌', finished:'本手结束'};
  let enabled = false, generation = 0, timer, clockTimer, roomId = null, state = null, lobby = null;
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
  function heading(subtitle, chips) {
    return `<div class="poker-extension-nav"><button class="secondary-button" type="button" data-extensions>← 返回拓展</button></div><section class="page-heading"><div><h1>德州扑克</h1><p>${esc(subtitle)}</p></div><div class="poker-wallet"><div class="poker-wallet-value"><small>剩余筹码</small><strong>${count(chips)}</strong></div><div class="poker-wallet-actions"><button class="pk-btn secondary-button" type="button" data-exchange="buy" ${!lobby?.enabled ? 'disabled' : ''}>买入</button><button class="pk-btn secondary-button" type="button" data-exchange="withdraw" ${chips < 1000 ? 'disabled' : ''}>提现</button></div></div></section>`;
  }
  function alertMarkup() {
    return `<p class="poker-notice" role="status" aria-live="polite">${esc(notice)}</p>`;
  }
  function drawLobby() {
    if (fullscreen) exitGameFullscreen();
    const capacityFull = lobby.capacity?.available === 0;
    root.innerHTML = heading('与队友同桌，或用赠送筹码练习。', lobby.chips) + alertMarkup() + `
      ${lobby.capacity ? `<p class="poker-capacity" role="status">全站已入座 <strong>${count(lobby.capacity.players)} / ${count(lobby.capacity.limit)} 人</strong><span>${capacityFull ? '人数已满，请等待玩家离桌后再加入。' : '各团队和练习模式共用席位，机器人不占真人席位。'}</span></p>` : ''}
      ${lobby.current_room ? '<div class="poker-resume"><span>你仍在一张牌桌中，筹码会保留至离桌结算。</span><button class="primary-button" data-resume>返回当前牌桌</button></div>' : ''}
      ${lobby.seated_elsewhere ? '<p class="poker-notice">你在其他团队仍有座位，请切回对应团队离桌后再加入。</p>' : ''}
      <div class="poker-modes">
        <article class="panel poker-mode"><span class="poker-mode-icon" aria-hidden="true">♠</span><div><p class="kicker">MULTIPLAYER</p><h2>多人联机</h2><p>2–9 人同桌 · 多房间 · 无限注</p><small>使用筹码入桌，离桌返还剩余筹码。</small></div><button class="primary-button" data-create="coins" ${!lobby.enabled || lobby.current_room || lobby.seated_elsewhere || capacityFull ? 'disabled' : ''}>创建房间</button>${!lobby.enabled ? '<small>当前团队尚未启用 RBC Coins</small>' : ''}</article>
        <article class="panel poker-mode poker-mode-friendly"><span class="poker-mode-icon" aria-hidden="true">♣</span><div><p class="kicker">PLAY WITH FRIENDS</p><h2>多人练习</h2><p>2–9 人同桌 · 每人赠送 1,000 筹码</p><small>免费和队友联机，不使用真实 Coins，不计收入。</small></div><button class="primary-button" data-create="friendly" ${lobby.current_room || lobby.seated_elsewhere || capacityFull ? 'disabled' : ''}>创建练习房间</button></article>
        <article class="panel poker-mode poker-mode-practice"><span class="poker-mode-icon" aria-hidden="true">♧</span><div><p class="kicker">PRACTICE</p><h2>人机练习</h2><p>1–5 个机器人 · 赠送 1,000 筹码</p><small>练习筹码不可兑换，不计收入，不影响钱包。</small></div><button class="secondary-button" data-create="practice" ${lobby.current_room || lobby.seated_elsewhere || capacityFull ? 'disabled' : ''}>开始练习</button></article>
      </div>
      <div class="poker-list-heading"><h2>房间大厅</h2><button class="secondary-button" data-refresh>刷新</button></div>
      <div class="poker-rooms">${lobby.rooms.length ? lobby.rooms.map(room => `<article class="panel poker-room-card"><div class="poker-room-title"><h3>${esc(room.name)}</h3><span class="poker-badge">${room.mode === 'practice' ? '人机练习' : room.mode === 'friendly' ? '多人练习' : room.playing ? '对局中' : '等待中'}</span></div><p>${room.players} / ${room.max_players} 人 · 盲注 ${room.big_blind / 2} / ${room.big_blind}</p><strong>${count(room.buy_in)} <small>${room.mode !== 'coins' ? '赠送筹码' : '筹码底注'}</small></strong><button class="secondary-button" data-room="${esc(room.id)}">${room.id === lobby.current_room ? '返回牌桌' : '查看房间'}</button></article>`).join('') : '<div class="panel poker-empty"><span aria-hidden="true">♠ ♥ ♣ ♦</span><h3>还没有房间</h3><p>邀请队友创建第一张牌桌，或先来一局人机练习。</p></div>'}</div>
      <details class="panel poker-rules"><summary>玩法与结算说明</summary><p>每人两张底牌，搭配五张公共牌组成最好的五张牌。所有玩家准备后开局，依次完成翻牌前、翻牌、转牌、河牌下注。支持过牌、跟注、加注、弃牌和全下，自动处理边池与平局分池。</p>${handRankHelp}<p>每次行动限时 45 秒，超时自动过牌或弃牌。进行中的对局可以排队离桌，本手结束后结算；全下后仍参加本手比牌。断开页面超过 5 分钟将自动离桌，重新进入可恢复仍在的座位。1 Coin 可买入 1000 筹码；每满 1000 筹码可提现 1 Coin，不足部分保留。联机入桌扣除底注，离桌返还剩余筹码；买入和提现会生成钱包流水。多人练习与人机局仅使用赠送筹码，退出时不计入钱包。</p></details>`;
    root.querySelectorAll('[data-create]').forEach(button => button.onclick = () => createDialog(button.dataset.create));
    root.querySelectorAll('[data-room]').forEach(button => button.onclick = () => enter(button.dataset.room));
    root.querySelector('[data-resume]')?.addEventListener('click', () => enter(lobby.current_room));
    root.querySelector('[data-refresh]').onclick = () => refresh(true);
  }
  const suitSymbols = {s:'♠', h:'♥', d:'♦', c:'♣'};
  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  let fullscreen = false, nativeFullscreen = false, fullscreenMobile = false, fullscreenEpoch = 0;
  let drawerOpen = true, fullscreenScroll = 0, orientationOwned = false;
  function syncMobileRailWidth() {
    const numbers = [...root.querySelectorAll('[data-raise],.poker-action-amount')].map(element =>
      String(element.value ?? element.textContent).trim().length);
    root.style.setProperty('--poker-number-chars', Math.max(2, ...numbers));
  }
  function syncFullscreen() {
    syncMobileRailWidth();
    root.classList.toggle('poker-fullscreen', fullscreen);
    root.classList.toggle('poker-fullscreen-mobile', fullscreen && fullscreenMobile);
    root.classList.toggle('poker-fullscreen-portrait', fullscreen && fullscreenMobile && innerHeight > innerWidth);
    root.classList.toggle('poker-drawer-open', drawerOpen);
    document.body.classList.toggle('poker-fullscreen-page', fullscreen);
    const rotated = fullscreenMobile && innerHeight > innerWidth;
    root.style.setProperty('--poker-game-width', `${rotated ? innerHeight : innerWidth}px`);
    root.style.setProperty('--poker-game-height', `${rotated ? innerWidth : innerHeight}px`);
    const drawer = root.querySelector('.poker-controls');
    if (drawer) drawer.inert = fullscreen && fullscreenMobile && !drawerOpen;
    const tools = root.querySelector('.poker-room-tools');
    if (tools) {
      const overlay = fullscreen && fullscreenMobile;
      tools.classList.toggle('poker-mobile-tools', overlay);
      const parent = root.querySelector(overlay ? '.poker-table' : '.poker-toolbar');
      if (tools.parentElement !== parent) parent.append(tools);
    }
    const info = root.querySelector('.poker-control-info');
    if (info && drawer) {
      const overlay = fullscreen && fullscreenMobile;
      info.classList.toggle('poker-mobile-status', overlay);
      const parent = overlay ? root.querySelector('.poker-room-screen') : drawer;
      if (info.parentElement !== parent) parent.prepend(info);
    }
    const presets = root.querySelector('.poker-raise-presets');
    if (presets) {
      const overlay = fullscreen && fullscreenMobile;
      presets.classList.toggle('poker-mobile-presets', overlay);
      const parent = root.querySelector(overlay ? '.poker-room-screen' : '.poker-raise-control');
      if (parent && presets.parentElement !== parent) parent.append(presets);
    }
    root.querySelectorAll('[data-fullscreen]').forEach(button => {
      button.setAttribute('aria-pressed', String(fullscreen));
      button.title = fullscreen ? '退出全屏' : '切换全屏';
      button.querySelector('span').textContent = fullscreen ? '退出全屏' : '全屏';
    });
    const toggle = root.querySelector('[data-drawer-toggle]');
    if (toggle) {
      toggle.setAttribute('aria-expanded', String(drawerOpen));
      toggle.setAttribute('aria-label', drawerOpen ? '收起操作台' : '展开操作台');
    }
  }
  function resetFullscreen() {
    if (!fullscreen) return;
    fullscreen = false; nativeFullscreen = false; fullscreenEpoch++;
    if (orientationOwned) { try { screen.orientation.unlock(); } catch {} }
    orientationOwned = false;
    syncFullscreen();
    window.scrollTo({top:fullscreenScroll, behavior:'instant'});
    root.querySelector('[data-fullscreen]')?.focus({preventScroll:true});
  }
  async function exitGameFullscreen() {
    resetFullscreen();
    if (document.fullscreenElement === root) {
      try { await document.exitFullscreen(); } catch {}
    }
  }
  async function toggleFullscreen() {
    if (fullscreen) { await exitGameFullscreen(); return; }
    fullscreenScroll = window.scrollY;
    fullscreenMobile = innerWidth <= 700 || (matchMedia('(pointer: coarse)').matches && Math.min(screen.width, screen.height) <= 1024);
    fullscreen = true; drawerOpen = true;
    const token = ++fullscreenEpoch;
    syncFullscreen();
    // The persistent root contains both the table and controls; room polls replace only its children.
    try { await root.requestFullscreen({navigationUI:'hide'}); }
    catch { /* Retain the viewport-sized layout when native fullscreen is unavailable. */ }
    if (!fullscreen || token !== fullscreenEpoch) {
      if (document.fullscreenElement === root) await document.exitFullscreen().catch(()=>{});
      return;
    }
    nativeFullscreen = document.fullscreenElement === root;
    if (fullscreenMobile && nativeFullscreen && screen.orientation?.lock) {
      try {
        await screen.orientation.lock('landscape');
        if (fullscreen && token === fullscreenEpoch) orientationOwned = true;
        else screen.orientation.unlock();
      } catch { /* CSS rotates the game if orientation locking is unavailable. */ }
    }
    syncFullscreen();
  }
  let presentedRoom = null, raiseDraft = null, raiseContext = '', raisePresetsOpen = false, soundOn = false, audioContext;
  const visualAnimations = new Set();
  try { soundOn = localStorage.getItem('poker-sound') === 'on'; } catch {}
  const icon = name => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${name === 'sound' ? '<path d="M11 5 6 9H3v6h3l5 4V5Z"/><path d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>' : name === 'expand' ? '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>' : '<path d="m10 5-7 7 7 7M3 12h18"/>'}</svg>`;
  function cards(values, hiddenCount = 0) {
    return [...values.map(value => {
      const rank = value.slice(0, -1), suit = value.slice(-1), symbol = suitSymbols[suit];
      const label = {11:'J',12:'Q',13:'K',14:'A'}[rank] || rank;
      return `<span class="poker-card ${suit === 'h' || suit === 'd' ? 'poker-card-red' : ''}" data-card="${esc(value)}" aria-label="${esc(label + symbol)}"><span class="poker-card-corner"><b>${esc(label)}</b><i>${symbol}</i></span><span class="poker-card-pip" aria-hidden="true">${symbol}</span><span class="poker-card-corner poker-card-corner-bottom" aria-hidden="true"><b>${esc(label)}</b><i>${symbol}</i></span></span>`;
    }), ...Array.from({length:hiddenCount}, () => '<span class="poker-card poker-card-back" aria-label="隐藏底牌"><span class="poker-card-seal" aria-hidden="true"></span></span>')].join('');
  }
  function chips(amount, extra = '') {
    if (!amount) return '';
    const tier = amount >= 500 ? 'gold' : amount >= 100 ? 'blue' : amount >= 25 ? 'red' : 'ivory';
    const height = Math.min(5, Math.max(1, Math.ceil(Math.log2(amount + 1) / 2)));
    return `<span class="poker-chips ${extra}" aria-hidden="true">${Array.from({length:height}, (_,i) => `<i class="poker-chip poker-chip-${tier}" style="--chip-layer:${i}"></i>`).join('')}</span>`;
  }
  function secondsLeft() {
    return state?.room.deadline ? Math.max(0, Math.ceil((state.room.deadline * 1000 - Date.now() - serverOffset) / 1000)) : 0;
  }
  function updateClock() {
    if (document.hidden || !enabled || !roomId) return;
    const remaining = secondsLeft();
    root.querySelectorAll('[data-clock]').forEach(el => { el.textContent = `${remaining} 秒`; });
    const ring = root.querySelector('.poker-seat-turn .poker-timer-progress');
    if (ring) {
      ring.style.strokeDashoffset = String(138.23 * (1 - Math.min(1, remaining / 45)));
      ring.closest('.poker-seat').classList.toggle('poker-seat-urgent', remaining <= 10);
    }
  }
  function seatCoordinates(number, anchor, capacity) {
    const index = (number - anchor + capacity) % capacity;
    const angle = index * Math.PI * 2 / capacity;
    const desktop = [50 + 39 * Math.sin(angle), 50 + 36 * Math.cos(angle)];
    const compact = {
      2:[[50,85],[50,15]],
      3:[[50,85],[82,27],[18,27]],
      4:[[50,85],[84,50],[50,15],[16,50]],
      5:[[50,86],[84,65],[76,17],[24,17],[16,65]],
      6:[[50,86],[84,68],[84,28],[50,13],[16,28],[16,68]],
      7:[[50,86],[84,72],[86,40],[70,13],[30,13],[14,40],[16,72]],
      8:[[50,87],[84,76],[86,50],[84,24],[50,12],[16,24],[14,50],[16,76]],
      9:[[50,87],[84,79],[86,56],[84,32],[74,12],[26,12],[16,32],[14,56],[16,79]],
    }[capacity][index];
    return {desktop, compact};
  }
  function seatPosition(number, anchor, capacity, fraction = 1) {
    const {desktop, compact} = seatCoordinates(number, anchor, capacity);
    const coords = [desktop,compact].map(pair => pair.map(n => (50 + (n - 50) * fraction).toFixed(3)));
    return `--seat-x:${coords[0][0]}%;--seat-y:${coords[0][1]}%;--seat-mobile-x:${coords[1][0]}%;--seat-mobile-y:${coords[1][1]}%`;
  }
  function cue(type) {
    if (!soundOn || document.hidden) return;
    try {
      audioContext ||= new (window.AudioContext || window.webkitAudioContext)();
      if (audioContext.state !== 'running') return;
      const start = audioContext.currentTime, oscillator = audioContext.createOscillator(), gain = audioContext.createGain();
      oscillator.type = type === 'chip' ? 'triangle' : 'sine';
      oscillator.frequency.setValueAtTime(type === 'win' ? 660 : type === 'chip' ? 330 : 920, start);
      oscillator.frequency.exponentialRampToValueAtTime(type === 'win' ? 880 : 180, start + .07);
      gain.gain.setValueAtTime(.035, start); gain.gain.exponentialRampToValueAtTime(.001, start + .1);
      oscillator.connect(gain); gain.connect(audioContext.destination); oscillator.start(start); oscillator.stop(start + .11);
    } catch { /* Sound is optional; the game always remains playable. */ }
  }
  function stopVisuals() {
    visualAnimations.forEach(animation => animation.cancel()); visualAnimations.clear();
    root.querySelectorAll('.poker-flying-token').forEach(el => el.remove());
  }
  function animate(element, frames, options, remove = false) {
    if (!element?.animate || motionQuery.matches || document.hidden) { if (remove) element?.remove(); return; }
    const animation = element.animate(frames, {duration:420, fill:'backwards', easing:'cubic-bezier(.16,1,.3,1)', ...options});
    visualAnimations.add(animation);
    const finish = () => { visualAnimations.delete(animation); if (remove) element.remove(); };
    animation.onfinish = finish; animation.oncancel = finish;
  }
  function fly(fromElement, toElement, amount, delay = 0) {
    const layer = root.querySelector('.poker-motion-layer');
    if (!layer || !fromElement || !toElement || motionQuery.matches || document.hidden) return;
    const bounds = layer.getBoundingClientRect(), a = fromElement.getBoundingClientRect(), b = toElement.getBoundingClientRect();
    const point = rect => root.classList.contains('poker-fullscreen-portrait')
      ? {x:rect.top + rect.height/2 - bounds.top, y:bounds.right - rect.left - rect.width/2}
      : {x:rect.left + rect.width/2 - bounds.left, y:rect.top + rect.height/2 - bounds.top};
    const from = point(a), to = point(b);
    const token = document.createElement('span'); token.className = 'poker-flying-token'; token.innerHTML = chips(amount);
    token.style.left = `${from.x}px`; token.style.top = `${from.y}px`; layer.append(token);
    const dx = to.x-from.x, dy = to.y-from.y;
    animate(token, [{transform:'translate(-50%,-50%)',opacity:1},{transform:`translate(calc(-50% + ${dx*.55}px),calc(-50% + ${dy*.55-24}px))`,opacity:1,offset:.5},{transform:`translate(calc(-50% + ${dx}px),calc(-50% + ${dy}px))`,opacity:0}], {duration:560,delay}, true);
  }
  function animateTable(previous, room) {
    if (!previous || previous.id !== room.id || previous.version === room.version || motionQuery.matches || document.hidden) return;
    const newHand = room.hand_number !== previous.hand_number;
    const pot = root.querySelector('.poker-pot-chips'), deck = root.querySelector('.poker-deck');
    if (newHand) {
      const deckBounds = deck?.getBoundingClientRect();
      room.seats.forEach((seat, index) => {
        const hole = root.querySelector(`[data-seat="${seat.number}"] .poker-hole`);
        hole?.querySelectorAll('.poker-card').forEach((card,i) => {
          const bounds = card.getBoundingClientRect();
          const screenDx = deckBounds ? deckBounds.left-bounds.left : 0, screenDy = deckBounds ? deckBounds.top-bounds.top : -80;
          const rotated = root.classList.contains('poker-fullscreen-portrait');
          const dx = rotated ? screenDy : screenDx, dy = rotated ? -screenDx : screenDy;
          animate(card,[{transform:`translate(${dx}px,${dy}px) rotate(-18deg) scale(.7)`,opacity:0},{transform:getComputedStyle(card).transform,opacity:1}], {duration:450,delay:index*45+i*140});
        });
      });
      cue('deal');
    }
    const beforeBoard = newHand ? 0 : previous.board.length;
    if (room.board.length > beforeBoard) {
      root.querySelectorAll('.poker-board .poker-card[data-card]').forEach((card,i) => {
        if (i < beforeBoard) return;
        animate(card,[{transform:'perspective(600px) rotateY(-90deg) translateY(-10px)',opacity:0},{transform:'perspective(600px) rotateY(0) translateY(0)',opacity:1}],{duration:430,delay:(i-beforeBoard)*110});
      });
      cue('deal');
    }
    if (!newHand) {
      room.seats.forEach(seat => {
        const before = previous.seats.find(s => s.user_id === seat.user_id);
        if (!before) return;
        const target = root.querySelector(`[data-seat="${seat.number}"]`);
        const bet = root.querySelector(`[data-bet-seat="${seat.number}"]`);
        if (seat.bet > before.bet) { fly(target, bet, seat.bet-before.bet); cue('chip'); }
        if (before.bet > 0 && (seat.bet < before.bet || room.street !== previous.street)) fly(bet || target, pot, before.bet);
        if (!before.folded && seat.folded) target?.querySelectorAll('.poker-hole .poker-card').forEach(card => animate(card,[{transform:'translateY(0)',opacity:1},{transform:'translateY(-18px)',opacity:.2}],{duration:240}));
        if (before.cards.length === 0 && seat.cards.length > 0 && !newHand) target?.querySelectorAll('.poker-hole .poker-card').forEach(card => animate(card,[{transform:'rotateY(90deg)',opacity:.2},{transform:'rotateY(0)',opacity:1}],{duration:400}));
      });
      // A player can cash out and disappear in the very same settlement response.
      if (room.result && !previous.result) {
        Object.entries(room.result.payouts).forEach(([id,amount],i) => {
          const seat = room.seats.find(s => s.user_id === id);
          if (amount > 0 && seat) fly(pot,root.querySelector(`[data-seat="${seat.number}"]`),amount,350+i*80);
        });
        cue('win');
      }
    }
    if (room.actor === String(state.user_id) && previous.actor !== room.actor) cue('turn');
  }
  function setRaisePresets(value) {
    raisePresetsOpen = value;
    const presets = root.querySelector('.poker-raise-presets');
    if (presets) presets.hidden = !value;
    root.querySelector('[data-raise-toggle]')?.setAttribute('aria-expanded', String(value));
  }
  function drawRoom() {
    const drawerScroll = root.querySelector('.poker-controls')?.scrollTop || 0;
    const focusedRaise = root.contains(document.activeElement) && document.activeElement.matches('[data-raise]') ? '[data-raise]' : null;
    const helpOpen = !!root.querySelector('.poker-room-help:not([hidden])');
    const historyOpen = !!root.querySelector('.poker-history[open]');
    const {room, user_id:userId, balance} = state;
    const uid = String(userId), me = room.seats.find(s => s.user_id === uid), practice = room.mode === 'practice', gifted = room.mode !== 'coins';
    const playing = !['waiting','finished'].includes(room.street), actions = room.actions;
    const actor = room.seats.find(s => s.user_id === room.actor), currency = gifted ? '练习筹码' : 'RBC Coins';
    const previous = presentedRoom;
    const context = `${room.id}:${room.hand_number}:${room.actor}:${room.street}`;
    if (raiseContext !== context) { raiseDraft = null; raiseContext = context; raisePresetsOpen = false; }
    const minRaise = actions ? Math.min(actions.min_raise_to,actions.max_raise_to) : 0;
    stopVisuals();
    const anchor = me?.number ?? 0;
    const participants = (playing ? room.seats : previous?.hand_number === room.hand_number ? previous.seats : []).filter(s => s.in_hand).sort((a,b)=>a.number-b.number);
    const clockwise = participants.filter(s=>s.number>room.dealer).concat(participants.filter(s=>s.number<=room.dealer));
    const smallBlind = participants.length === 2 ? room.dealer : clockwise[0]?.number;
    const bigBlind = participants.length === 2 ? participants.find(s=>s.number!==room.dealer)?.number : clockwise[1]?.number;
    const payouts = room.result ? Object.entries(room.result.payouts).filter(([,amount]) => amount > 0).map(([id,amount]) => `${room.seats.find(s => s.user_id === id)?.name || '已离桌玩家'} +${count(amount)}`).join(' · ') : '';
    root.innerHTML = `<div class="poker-room-screen"><header class="poker-toolbar"><button class="pk-btn poker-quiet" data-lobby>${icon('back')}<span>房间大厅</span></button><div class="poker-room-heading"><h2>${esc(room.name)}</h2><small>${practice ? '人机练习' : gifted ? '多人练习' : 'Coins 多人局'} · 第 ${room.hand_number} 手 · 盲注 ${room.big_blind/2} / ${room.big_blind}</small></div><div class="poker-room-tools"><button class="pk-btn poker-quiet poker-sound" data-sound aria-pressed="${soundOn}" title="${soundOn ? '关闭音效' : '开启音效'}">${icon('sound')}<span>音效${soundOn ? '开' : '关'}</span></button><button class="pk-btn poker-quiet" data-fullscreen title="切换全屏">${icon('expand')}<span>全屏</span></button><button class="pk-btn poker-quiet" data-help aria-expanded="false">玩法</button></div></header>${alertMarkup()}
      <div class="poker-table ${room.max_players >= 8 ? 'poker-table-crowded' : ''}" style="--seat-count:${room.max_players}" role="group" aria-label="${room.max_players} 人德州扑克牌桌"><div class="poker-felt"></div><div class="poker-felt-line"></div><div class="poker-deck" aria-label="牌堆"><i></i><i></i><i></i></div><div class="poker-community"><div class="poker-street">${streets[room.street]}</div><div class="poker-board" aria-label="公共牌">${cards(room.board)}${Array.from({length:5-room.board.length},()=>'<span class="poker-card poker-card-slot" aria-hidden="true"></span>').join('')}</div><div class="poker-pot"><span class="poker-pot-chips">${chips(room.pot)}</span><div><small>${room.street === 'finished' ? '本手底池 · 已分配' : '底池'}</small><strong>${count(room.pot)}</strong></div></div><p class="poker-turn" role="status">${playing ? `${esc(actor?.name || '')} 操作中 <strong data-clock></strong>` : room.result ? '本手结束，请准备下一手' : '入座后准备，至少两人开局'}</p></div>
      <div class="poker-bets">${room.seats.map(seat=>`<div class="poker-bet ${seat.bet ? '' : 'poker-bet-empty'}" style="${seatPosition(seat.number,anchor,room.max_players,.56)}" data-bet-seat="${seat.number}">${chips(seat.bet)}<strong>${seat.bet ? count(seat.bet) : ''}</strong></div>`).join('')}</div>
      <div class="poker-seats">${Array.from({length:room.max_players},(_,number)=>{
        const seat=room.seats.find(s=>s.number===number), position=seatPosition(number,anchor,room.max_players);
        if (!seat) return `<div class="poker-seat poker-seat-empty" style="${position}" data-seat="${number}"><span class="poker-empty-seat-number">${number+1}</span><small>空位</small></div>`;
        const own=seat.user_id===uid, active=seat.user_id===room.actor;
        const winner=!!(room.result?.payouts[seat.user_id]>0);
        const status=seat.leaving?'待离桌':playing&&seat.in_hand?seat.folded?'已弃牌':seat.stack===0?'全下':active?'思考中':seat.bet?`下注 ${count(seat.bet)}`:'在局中':seat.ready?'已准备':seat.stack?'等待准备':'筹码不足';
        const before=previous?.hand_number===room.hand_number?previous.seats.find(s=>s.user_id===seat.user_id):null;
        const action=before&&seat.stack<before.stack&&seat.bet>before.bet?(before.bet?'加注':'下注'):'';
        return `<article class="poker-seat ${active?'poker-seat-turn':''} ${seat.folded&&playing?'poker-seat-folded':''} ${own?'poker-seat-own':''} ${winner?'poker-seat-winner':''}" style="${position}" data-seat="${number}"><div class="poker-hole">${cards(seat.cards,Math.max(0,seat.card_count-seat.cards.length))}</div><div class="poker-avatar-wrap"><svg class="poker-timer" viewBox="0 0 50 50" aria-hidden="true"><circle cx="25" cy="25" r="22"/><circle class="poker-timer-progress" cx="25" cy="25" r="22"/></svg><span class="poker-avatar ${seat.is_bot?'poker-avatar-bot':''}" aria-hidden="true">${esc(seat.is_bot?'机':Array.from(seat.name)[0]||'玩')}</span>${room.dealer===number?'<b class="poker-dealer" title="庄家">D</b>':''}${number===smallBlind?'<b class="poker-blind" title="小盲注">SB</b>':number===bigBlind?'<b class="poker-blind poker-big-blind" title="大盲注">BB</b>':''}</div><div class="poker-seat-plate"><strong class="poker-seat-name" title="${esc(seat.name)}">${esc(seat.name)}${own?'<span>你</span>':''}</strong><strong class="poker-stack">${count(seat.stack)}</strong></div><span class="poker-seat-status ${action?'poker-seat-action':''}">${winner?`+${count(room.result.payouts[seat.user_id])}`:action||status}</span></article>`;
      }).join('')}</div><div class="poker-motion-layer" aria-hidden="true"></div><div class="poker-table-caption" aria-hidden="true">${gifted?'练习筹码 · 不影响钱包':'RBC Coins · 无限注'}</div></div>
      <button class="pk-btn poker-fullscreen-exit" data-exit-fullscreen type="button" aria-label="退出全屏">${icon('back')}<span>退出全屏</span></button><button class="pk-btn poker-drawer-toggle" data-drawer-toggle type="button" aria-controls="pokerControls" aria-expanded="${drawerOpen}" aria-label="收起操作台"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg></button>
      <section id="pokerControls" class="poker-controls" aria-label="牌局操作"><div class="poker-control-info"><strong>${room.closed?'房间已关闭':actions?'轮到你了':me?.leaving?'已申请离桌':playing?`等待${esc(actor?.name||'其他玩家')}`:me?'准备开始下一手':'选择入座，加入下一手'}</strong><small>${me?`在桌 ${count(me.stack)} ${currency}`:gifted?'免费领取练习筹码':'买入后入座'}${actions?' · 行动剩余 <span data-clock></span>':''}</small></div>
      <div class="poker-action-buttons">${room.closed?'<p>剩余筹码已按模式结算。</p>':me?actions&&!me.leaving?`<button class="pk-btn poker-fold" data-action="fold">弃牌</button><button class="pk-btn poker-call" data-action="${actions.check?'check':'call'}">${actions.check?'过牌':`跟注 <span class="poker-action-amount">${count(actions.call)}</span>`}</button>${actions.raise?`<div class="poker-raise-control"><button class="pk-btn poker-raise" data-action="raise" type="button" aria-label="加注">加注</button><div class="poker-raise-field"><input id="pokerRaise" data-raise type="number" inputmode="numeric" step="1" min="${minRaise}" max="${actions.max_raise_to}" value="${raiseDraft ?? minRaise}" placeholder="加注" aria-label="本轮加注至总额"><button class="pk-btn poker-raise-toggle" data-raise-toggle type="button" aria-label="选择快捷加注金额" aria-controls="pokerRaisePresets" aria-expanded="${raisePresetsOpen}"><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true"><path d="m6 9 6 6 6-6Z"/></svg></button></div><div id="pokerRaisePresets" class="poker-raise-presets" ${raisePresetsOpen?'':'hidden'}><div class="poker-quick-bets">${[['最小',minRaise],['½ 底池',Math.max(minRaise,(me?.bet||0)+actions.call+Math.round((room.pot+actions.call)/2))],['满池',Math.max(minRaise,(me?.bet||0)+actions.call+room.pot+actions.call)],['最大',actions.max_raise_to]].map(([label,value])=>`<button class="pk-btn poker-quick" data-quick="${Math.min(actions.max_raise_to,value)}">${label}</button>`).join('')}</div></div></div>`:''}${actions.all_in?'<button class="pk-btn poker-allin" data-action="all_in">全下</button>':''}`:!playing&&!me.leaving?me.stack>0?`<button class="pk-btn poker-call" data-action="ready">${me.ready?'取消准备':'准备开局'}</button>`:gifted?'<button class="pk-btn poker-call" data-action="refill">领取练习筹码</button>':'<span>筹码用完，请离桌后重新买入</span>':'':!practice?`<button class="pk-btn poker-call" data-action="join" ${room.seats.length>=room.max_players?'disabled':''}>${room.seats.length>=room.max_players?'房间已满':gifted?'免费入座':`入桌 ${count(room.buy_in)} 筹码`}</button>`:'<p>这是个人练习房间。</p>'}</div>${me&&(!me.leaving||!playing)&&!room.closed?`<button class="pk-btn poker-leave poker-quiet" data-leave>${me.leaving?'重试结算':playing&&me.in_hand?'申请离桌':'离桌'}</button>`:''}</section>
      ${room.result?`<div class="poker-result" role="status"><div><strong>本手结算</strong><span>${esc(payouts)}</span></div><small>${room.result.showdown?Object.entries(room.result.hands).map(([id,hand])=>esc((room.seats.find(s=>s.user_id===id)?.name||'已离桌玩家')+'：'+hand)).join(' · '):'其余玩家弃牌'}</small></div>`:''}
      <details class="poker-history"><summary>本手行动记录 <span>${room.log.length} 条</span></summary><ol>${room.log.map(line=>`<li>${esc(line)}</li>`).join('')||'<li>等待开局</li>'}</ol></details><div class="poker-room-help" hidden><p>两张底牌搭配五张公共牌，选出最好的五张牌。依次进行翻牌前、翻牌、转牌、河牌下注；其他玩家全部弃牌也可获胜。</p>${handRankHelp}<p>每次行动 45 秒。超时自动过牌或弃牌；断线 5 分钟自动申请离桌。全下后离桌仍参与本手比牌，结束后结算。</p><p>${gifted?'赠送筹码不计入钱包、收入或排行榜。':'离桌返还剩余筹码，可在大厅按 1000:1 提现。'} 钱包余额 ${count(balance)} RBC Coins。</p></div></div>`;
    root.querySelector('[data-lobby]').onclick=()=>{ exitGameFullscreen(); stopVisuals(); roomId=null; state=null; presentedRoom=null; notice=''; refresh(true); };
    root.querySelector('[data-sound]').onclick=async event=>{
      const button=event.currentTarget;
      soundOn=!soundOn; try{localStorage.setItem('poker-sound',soundOn?'on':'off');}catch{}
      if(soundOn){try{audioContext ||= new (window.AudioContext||window.webkitAudioContext)();await audioContext.resume();cue('chip');}catch{}}
      if(button.isConnected){button.setAttribute('aria-pressed',String(soundOn));button.title=soundOn?'关闭音效':'开启音效';button.querySelector('span').textContent=`音效${soundOn?'开':'关'}`;}
    };
    root.querySelector('[data-fullscreen]').onclick=toggleFullscreen;
    root.querySelector('[data-exit-fullscreen]').onclick=exitGameFullscreen;
    root.querySelector('[data-drawer-toggle]').onclick=()=>{drawerOpen=!drawerOpen;syncFullscreen();if(drawerOpen)root.querySelector('.poker-controls').scrollTop=0;};
    root.querySelector('[data-help]').onclick=event=>{const help=root.querySelector('.poker-room-help');help.hidden=!help.hidden;event.currentTarget.setAttribute('aria-expanded',String(!help.hidden));if(!help.hidden&&!fullscreen)help.scrollIntoView({block:'nearest'});};
    const syncRaise=value=>{
      const number=Number(value);if(!Number.isFinite(number))return;
      raiseDraft=Math.max(minRaise,Math.min(actions.max_raise_to,Math.round(number)));
      root.querySelector('[data-raise]').value=raiseDraft;
      syncMobileRailWidth();
    };
    root.querySelector('[data-raise]')?.addEventListener('input',event=>{const value=Number(event.target.value);raiseDraft=event.target.value===''?'':Number.isFinite(value)?value:null;syncMobileRailWidth();});
    root.querySelector('[data-raise-toggle]')?.addEventListener('click',()=>setRaisePresets(!raisePresetsOpen));
    root.querySelectorAll('[data-quick]').forEach(button=>button.onclick=()=>{syncRaise(button.dataset.quick);setRaisePresets(false);root.querySelector('[data-raise]').focus({preventScroll:true});});
    root.querySelector('[data-raise]')?.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();root.querySelector('[data-action=raise]').click();}});
    root.querySelectorAll('[data-action]').forEach(button=>button.onclick=()=>{
      const action=button.dataset.action,amount=action==='raise'?Number(root.querySelector('[data-raise]').value):undefined;
      if(action==='raise'&&(!Number.isInteger(amount)||amount<minRaise||amount>actions.max_raise_to)){notice='请填写有效的加注总额';root.querySelector('.poker-notice').textContent=notice;root.querySelector('[data-raise]').focus();return;}
      run(action,amount);
    });
    root.querySelector('[data-leave]')?.addEventListener('click',leaveDialog);
    if(helpOpen){root.querySelector('.poker-room-help').hidden=false;root.querySelector('[data-help]').setAttribute('aria-expanded','true');}
    if(historyOpen)root.querySelector('.poker-history').open=true;
    if(focusedRaise)root.querySelector(focusedRaise)?.focus({preventScroll:true});
    if (fullscreen && fullscreenMobile && actions && previous?.actor !== room.actor) drawerOpen = true;
    syncFullscreen();
    if (fullscreen && fullscreenMobile) root.querySelector('.poker-controls').scrollTop = drawerScroll;
    updateClock();animateTable(previous,room);presentedRoom=structuredClone(room);
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
        await refresh();
      }
    }
  }
  let dialogNumber = 0;
  function dialog(content, description = '') {
    const element = document.createElement('dialog'); element.className = 'extension-dialog poker-dialog';
    element.id = `pokerDialog${++dialogNumber}`;
    element.innerHTML = `<div class="poker-dialog-content">${content}</div>`;
    const title = element.querySelector('h2');
    title.id = `${element.id}Title`; element.setAttribute('aria-labelledby', title.id);
    const header = document.createElement('header'); header.className = 'poker-dialog-header';
    header.innerHTML = `<div class="poker-dialog-title"></div><button class="pk-btn poker-dialog-close" type="button" aria-label="关闭弹窗"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg></button>`;
    header.querySelector('.poker-dialog-title').append(title);
    if (description) {
      const subtitle = document.createElement('p'); subtitle.textContent = description;
      subtitle.id = `${element.id}Description`; header.querySelector('.poker-dialog-title').append(subtitle);
      element.setAttribute('aria-describedby', subtitle.id);
    }
    element.prepend(header);
    element.querySelectorAll('form').forEach(form => form.classList.add('poker-form'));
    element.querySelectorAll('button').forEach(button => button.classList.add('pk-btn'));
    element.querySelectorAll('input').forEach(input => input.classList.add('pk-input'));
    element.querySelectorAll('select').forEach(select => select.classList.add('pk-select'));
    element.querySelector('input')?.setAttribute('autofocus', '');
    document.body.append(element);
    element.addEventListener('close', () => element.remove()); element.showModal();
    element.querySelector('[data-cancel]').onclick = () => element.close();
    element.querySelector('.poker-dialog-close').onclick = () => element.close();
    return element;
  }
  function dialogBusy(element, value) {
    element.setAttribute('aria-busy', String(value));
    element.querySelectorAll('button').forEach(button => button.disabled = value);
    const submit = element.querySelector('[type=submit]');
    if (submit) {
      submit.dataset.idleText ||= submit.textContent;
      submit.textContent = value ? '正在处理…' : submit.dataset.idleText;
    }
  }
  function leaveDialog() {
    if (state.room.mode === 'practice') { run('leave'); return; }
    const gifted = state.room.mode !== 'coins';
    const element = dialog(`<h2>${gifted ? '离开练习桌' : '结算离桌'}</h2><div class="poker-dialog-note"><strong>${gifted ? '练习筹码仅限本桌使用' : '剩余筹码将返还余额'}</strong><p>${gifted ? '退出后作废，不进入可兑换筹码余额，也不计入 Coin 钱包或收入。' : '离桌后可在大厅按 1,000 筹码 = 1 Coin 提现。'}</p></div><p>若你正在本手中，将在本手结束后离桌；全下仍参加比牌。</p><div class="extension-actions"><button class="secondary-button" data-cancel>继续留桌</button><button class="primary-button" data-confirm>确认离桌</button></div>`, '确认本桌筹码的结算方式。');
    element.querySelector('[data-confirm]').onclick = () => { element.close(); run('leave'); };
  }
  function createDialog(mode) {
    const practice = mode === 'practice', gifted = mode !== 'coins';
    const capacity = '<label>房间人数<select name="max_players"><option>2</option><option>3</option><option>4</option><option>5</option><option selected>6</option><option>7</option><option>8</option><option>9</option></select></label>';
    const bots = '<label>机器人数量<select name="bot_count"><option value="1">1 个</option><option value="2">2 个</option><option value="3" selected>3 个</option><option value="4">4 个</option><option value="5">5 个</option></select></label>';
    const giftNotice = '<div class="poker-dialog-note"><strong>每人赠送 1,000 练习筹码</strong><p>盲注 5 / 10，筹码用完可重新领取。仅限本桌使用，退出即作废，不进入可兑换筹码余额或 Coin 钱包。</p></div>';
    const coinFields = '<label>盲注（小盲 / 大盲）<select name="big_blind"><option value="2">1 / 2</option><option value="4">2 / 4</option><option value="10">5 / 10</option><option value="20">10 / 20</option><option value="50">25 / 50</option><option value="100">50 / 100</option></select></label><label>底注（筹码）<input name="buy_in" type="number" min="2" max="100000" step="1" value="1000" required><small>每人入桌扣除的筹码，默认 1000，最低为大盲注；请先在大厅买入筹码。</small></label>';
    const element = dialog(`<form class="extension-form"><h2>${practice ? '创建人机练习' : gifted ? '创建多人练习' : '创建多人联机房间'}</h2><label>房间名称<input name="name" maxlength="40" required value="${practice ? '我的练习桌' : ''}" placeholder="给牌桌起个名字"></label><div class="poker-dialog-fields">${practice ? bots : capacity}${gifted ? '' : coinFields}</div>${gifted ? giftNotice : ''}<p role="alert"></p><div class="extension-actions"><button class="secondary-button" type="button" data-cancel>取消</button><button class="primary-button" type="submit">${gifted ? '免费领取筹码并创建' : '确认入桌并创建'}</button></div></form>`, practice ? '与机器人同桌，轻松熟悉牌局。' : gifted ? '邀请队友练习，使用独立的赠送筹码。' : '设置牌桌规则，邀请队友入座。');
    const form = element.querySelector('form');
    form.elements.big_blind?.addEventListener('change', () => {
      const blind = Number(form.elements.big_blind.value);
      form.elements.buy_in.min = blind;
    });
    let submitting = false;
    element.addEventListener('cancel', event => { if (submitting) event.preventDefault(); });
    form.onsubmit = async event => {
      event.preventDefault(); if (submitting) return;
      submitting = true; const token = generation;
      dialogBusy(element, true);
      const data = {name:form.elements.name.value, mode};
      for (const key of ['bot_count','max_players','big_blind','buy_in']) if (form.elements[key]) data[key] = Number(form.elements[key].value);
      try {
        const payload = await api('', data); element.close();
        if (token !== generation || !enabled) return;
        roomId = payload.room.id; apply(payload); notice = ''; drawRoom();
      } catch (error) { form.querySelector('[role=alert]').textContent = error.message; }
      finally { submitting = false; dialogBusy(element, false); }
    };
  }
  function exchangeDialog(action) {
    if (!lobby || document.querySelector('.poker-dialog[open]')) return;
    const buying = action === 'buy';
    const max = buying ? Math.max(0, lobby.balance) : Math.floor((lobby.chips || 0) / 1000);
    const element = dialog(`<form class="extension-form"><h2>${buying ? '买入筹码' : '筹码提现'}</h2><dl class="poker-dialog-balances"><div><dt>Coin 钱包</dt><dd>${count(lobby.balance)} <small>Coins</small></dd></div><div><dt>可用筹码</dt><dd>${count(lobby.chips)} <small>筹码</small></dd></div></dl><label>${buying ? '买入金额' : '提现金额'}（Coins）<input name="coins" type="number" inputmode="numeric" min="1" max="${max}" step="1" value="1" required><small>本次最多${buying ? '买入' : '提现'} ${count(max)} Coins</small></label><output class="poker-exchange-preview" data-preview aria-live="polite"></output><p class="poker-dialog-hint">每满 1,000 筹码可提现 1 Coin，余数保留。桌上筹码需先离桌；练习筹码不可兑换。</p><p role="alert"></p><div class="extension-actions"><button class="secondary-button" type="button" data-cancel>取消</button><button class="primary-button" type="submit" ${max < 1 ? 'disabled' : ''}>确认${buying ? '买入' : '提现'}</button></div></form>`, '1 Coin = 1,000 筹码');
    const form = element.querySelector('form');
    const preview = () => {
      const coins = Number(form.elements.coins.value), valid = Number.isSafeInteger(coins) && coins > 0 && coins <= max;
      form.querySelector('[data-preview]').innerHTML = valid ? `<span>${buying ? '将获得' : '将扣除'}</span><strong>${count(coins * 1000)} <small>筹码</small></strong>` : '<span>请输入可兑换范围内的整数金额</span>';
    };
    form.elements.coins.addEventListener('input', preview); preview();
    let submitting = false;
    element.addEventListener('cancel', event => { if (submitting) event.preventDefault(); });
    form.onsubmit = async event => {
      event.preventDefault(); if (submitting) return;
      submitting = true; const token = generation;
      dialogBusy(element, true);
      try {
        const payload = await api('/chips', {action, coins:Number(form.elements.coins.value)});
        element.close();
        window.CurrencyModule?.syncBalance(payload.balance);
        if (token !== generation || !enabled) return;
        generation++; // Discard any poll started before the exchange completed.
        Object.assign(lobby, payload);
        notice = buying ? '筹码买入成功' : '提现成功，不足 1000 的筹码已保留'; drawLobby();
      } catch (error) { form.querySelector('[role=alert]').textContent = error.message; }
      finally { submitting = false; dialogBusy(element, false); form.querySelector('[type=submit]').disabled = max < 1; }
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
        const changed = force || !state || state.room.version !== payload.room.version || state.balance !== payload.balance || state.chips !== payload.chips;
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
    enabled = value; generation++; clearInterval(timer); clearInterval(clockTimer); stopVisuals(); presentedRoom = null;
    if (!value) { exitGameFullscreen(); return; }
    roomId = null; state = null; lobby = null; notice = '';
    root.innerHTML = '<p role="status">正在连接牌桌…</p>';
    refresh(true, true);
    timer = setInterval(() => refresh(), 1500);
    clockTimer = setInterval(updateClock, 250);
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
    const exchange = event.target.closest('[data-exchange]');
    if (exchange && !exchange.disabled) exchangeDialog(exchange.dataset.exchange);
  });
  document.addEventListener('click', event => { if (raisePresetsOpen && !event.target.closest('.poker-raise-control')) setRaisePresets(false); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopVisuals(); });
  document.addEventListener('fullscreenchange', () => {
    if (document.fullscreenElement === root) { nativeFullscreen = true; syncFullscreen(); }
    else if (nativeFullscreen) resetFullscreen();
  });
  window.addEventListener('resize', () => { if (fullscreen) syncFullscreen(); });
  document.addEventListener('keydown', event => {
    if (!enabled || !state || document.querySelector('.poker-dialog[open]')) return;
    if (event.key === 'Escape' && raisePresetsOpen) { event.preventDefault();setRaisePresets(false);root.querySelector('[data-raise-toggle]')?.focus({preventScroll:true}); }
    else if (event.key === 'Escape' && fullscreen) { event.preventDefault(); exitGameFullscreen(); }
    else if (!event.target.closest('input,textarea,select,[contenteditable=true]') && event.key.toLowerCase() === 'f' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.repeat) { event.preventDefault(); toggleFullscreen(); }
  });
  motionQuery.addEventListener('change', () => { if (motionQuery.matches) stopVisuals(); });
  window.render_game_to_text = () => JSON.stringify(enabled && state ? {mode:state.room.mode,room:state.room.name,street:state.room.street,hand:state.room.hand_number,board:state.room.board,pot:state.room.pot,actor:state.room.actor,seconds:secondsLeft(),actions:state.room.actions,seats:state.room.seats.map(s=>({number:s.number,name:s.name,stack:s.stack,bet:s.bet,folded:s.folded,cards:s.cards})),animations:visualAnimations.size,fullscreen:{active:fullscreen,mobile:fullscreen&&fullscreenMobile,rotated:root.classList.contains('poker-fullscreen-portrait'),drawerOpen:fullscreen&&fullscreenMobile?drawerOpen:null,raisePresetsOpen},coordinates:'Seats around the rail; your seat at bottom; x right, y down. Portrait fullscreen rotates the landscape surface clockwise.'} : {mode:enabled?'lobby':'closed'});
  window.PokerModule = {open, close};
})();
