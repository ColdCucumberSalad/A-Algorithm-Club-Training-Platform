window.CosmeticMedia={safe:value=>typeof value==='string'&&/^\/(?:static\/cosmetics\/[a-zA-Z0-9_-]+\.(?:png|jpg|jpeg|webp|svg)|api\/cosmetic-assets\/media\/[a-f0-9]{64}\.png)$/.test(value)};
/* Shared read-only badge renderer; no arbitrary CSS or remote font loading. */
window.MemberTitles = (() => {
  const styles = {plain:'简约',chroma:'炫彩',wings:'羽翼',captain:'先锋徽章',president:'冠冕徽章',deputy:'星盾徽章',neon:'霓虹描边',metal:'金属徽章',shimmer:'流光',orbit:'星环'};
  let clockOffset=0;
  const frameAssets={'taffy-goggles':'taffy-goggles-frame.svg'},memberFrames=new Map();
  const endOf=item=>item?.expires_at?Date.parse(item.expires_at):NaN;
  const expired=item=>Number.isFinite(endOf(item))&&endOf(item)<=Date.now()+clockOffset;
  function until(item){
    const end=endOf(item);
    if(!Number.isFinite(end))return '';
    window.SpecialThemes?.registerExpiry?.(end);
    return ` data-cosmetic-until="${end}"`;
  }
  function syncClock(now){if(Number.isFinite(now))clockOffset=now-Date.now();}
  function frameImage(frame){
    if(!frame||expired(frame))return '';
    const source=window.CosmeticMedia.safe(frame.icon)?frame.icon:Object.hasOwn(frameAssets,frame.key)?'/static/cosmetics/'+frameAssets[frame.key]:'';
    if(!source)return '';
    const g=frame.geometry||{},scale=Number.isFinite(g.scale)&&g.scale>=1&&g.scale<=2?g.scale:1.25,x=Number.isFinite(g.x)&&Math.abs(g.x)<=1?g.x:-.125,y=Number.isFinite(g.y)&&Math.abs(g.y)<=1?g.y:-.225;
    return `<img class="avatar-frame-art" src="${source}" alt="" aria-hidden="true" style="--frame-size:${scale*100}%;--frame-x:${x*100}%;--frame-y:${y*100}%"${until(frame)}>`;
  }
  function frameAvatar(markup,frame){const image=frameImage(frame);return image?`<span class="avatar-frame-wrap">${markup}${image}</span>`:markup;}
  function frameElement(element,frame){
    if(!element)return;let wrap=element.parentElement?.classList.contains('avatar-frame-wrap')?element.parentElement:null;
    if(!frameImage(frame)){if(wrap)wrap.replaceWith(element);return;}
    if(!wrap){wrap=document.createElement('span');wrap.className='avatar-frame-wrap';element.before(wrap);wrap.append(element);}
    wrap.querySelector(':scope > .avatar-frame-art')?.remove();wrap.insertAdjacentHTML('beforeend',frameImage(frame));
  }
  function rememberFrames(rows){for(const row of rows)if(Object.hasOwn(row,'avatar_frame'))memberFrames.set(Number(row.memberId||row.id),row.avatar_frame);}
  function pruneExpired(now){
    syncClock(now);
    document.querySelectorAll('[data-cosmetic-until]').forEach(el=>{if(Number(el.dataset.cosmeticUntil)<=Date.now()+clockOffset)el.remove();});
  }
  const fonts = new Set(['system','serif','kai','mono','rounded']);
  const escape = text => String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function markup(title) {
    if (expired(title) || !title || typeof title.text !== 'string' || !title.text.trim()) return '';
    const color = /^#[0-9a-f]{6}$/i.test(title.color || '') ? title.color : '#c96c7a';
    const font = fonts.has(title.font) ? title.font : 'system';
    const style = Object.hasOwn(styles,title.style)?title.style:'plain';
    const channels = color.slice(1).match(/../g).map(c=>parseInt(c,16)/255).map(c=>c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4));
    const luminance = channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
    const tone = luminance>.4?'light':luminance<.15?'dark':'normal';
    return `<span class="member-title-badge"${until(title)} data-title-style="${style}" data-title-tone="${tone}" data-title-font="${font}" style="--member-title-color:${color}">${escape(title.text.trim().slice(0,20))}</span>`;
  }
  const badgeAssets={taffy:{name:'小塔菲 · 原版',icon:'taffy-original-head.svg'},'rbc-pendant':{name:'RBC 挂坠纪念',icon:'rbc-pendant-badge.png'}};
  function badgeMarkup(badge){
    if(!badge||expired(badge))return '';
    const known=Object.hasOwn(badgeAssets,badge.key)?badgeAssets[badge.key]:null;
    const source=window.CosmeticMedia.safe(badge.icon)?badge.icon:known?'/static/cosmetics/'+known.icon:'';
    const name=String(badge.name||known?.name||'电子徽章');
    return source?`<img class="member-icon-badge"${until(badge)} src="${source}" alt="${escape(name)}" title="${escape(name)}" width="26" height="26">`:'';
  }

  function list(titles,badge) {return badgeMarkup(badge)+ (Array.isArray(titles)?titles:titles?[titles]:[]).slice(0,8).map(markup).join('');}
  function cohort(value,compact=false) {
    const label=compact?value?.squad_short:value?.squad_label;
    return typeof label==='string'&&label?`<span class="squad-badge">${escape(label.slice(0,40))}</span>`:'';
  }
  function matchesMember(member,query) {
    const squad=member.cohort;
    const haystack=[member.name,squad?.squad_short,squad?.squad_label,squad?.admission_year,
      squad?`${squad.squad_number}分队 第${squad.squad_number}分队 ${squad.admission_year}级`:'未分队 未设置'].join(' ').toLowerCase();
    return String(query||'').trim().toLowerCase().split(/\s+/).every(token=>haystack.includes(token));
  }
  return {markup,list,badgeMarkup,badgeAssets,frameAvatar,frameElement,rememberFrames,frameFor:id=>memberFrames.get(Number(id)),syncClock,pruneExpired,cohort,matchesMember,styles};
})();
