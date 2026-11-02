/* Shared read-only badge renderer; no arbitrary CSS or remote font loading. */
window.MemberTitles = (() => {
  const fonts = new Set(['system','serif','kai','mono','rounded']);
  const escape = text => String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function markup(title) {
    if (!title || typeof title.text !== 'string' || !title.text.trim()) return '';
    const color = /^#[0-9a-f]{6}$/i.test(title.color || '') ? title.color : '#c96c7a';
    const font = fonts.has(title.font) ? title.font : 'system';
    const style = ['plain','chroma','wings','captain','president','deputy'].includes(title.style)?title.style:'plain';
    const channels = color.slice(1).match(/../g).map(c=>parseInt(c,16)/255).map(c=>c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4));
    const luminance = channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
    const tone = luminance>.4?'light':luminance<.15?'dark':'normal';
    return `<span class="member-title-badge" data-title-style="${style}" data-title-tone="${tone}" data-title-font="${font}" style="--member-title-color:${color}">${escape(title.text.trim().slice(0,20))}</span>`;
  }
  function list(titles) {return (Array.isArray(titles)?titles:titles?[titles]:[]).slice(0,8).map(markup).join('');}
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
  return {markup,list,cohort,matchesMember};
})();
