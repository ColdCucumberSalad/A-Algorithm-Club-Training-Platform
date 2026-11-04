"""Team-specific honorifics with a deliberately small, safe style vocabulary."""
import re

STYLES = {'plain':'简约','chroma':'炫彩','wings':'羽翼','captain':'先锋徽章','president':'冠冕徽章','deputy':'星盾徽章','neon':'霓虹描边','metal':'金属徽章','shimmer':'流光','orbit':'星环'}

FONTS = {'system':'默认黑体','serif':'典雅宋体','kai':'手写楷体','mono':'等宽字体','rounded':'圆润字体'}


def validate_title(value):
    if not isinstance(value,dict) or set(value)-{'text','color','font','style'}:
        raise ValueError('称号格式无效')
    text = value.get('text','')
    if not isinstance(text,str) or len(text.strip()) > 20 or re.search(r'[\x00-\x1f\x7f]',text):
        raise ValueError('称号最多 20 字，不能包含换行或控制字符')
    if not text.strip():
        return {}
    color, font = value.get('color','#c96c7a'), value.get('font','system')
    if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):
        raise ValueError('请选择有效的称号颜色')
    if not isinstance(font,str) or font not in FONTS:
        raise ValueError('请选择支持的称号字体')
    style=value.get('style','plain')
    if not isinstance(style,str) or style not in STYLES: raise ValueError('请选择支持的称号样式')
    result={'text':text.strip(),'color':color.lower(),'font':font}
    if style!='plain': result['style']=style
    return result


def title_data(member):
    titles = titles_data(member)
    return titles[0] if titles else {}


def validate_titles(value):
    if not isinstance(value,list) or len(value)>8:
        raise ValueError('最多可授予 8 个称号')
    result = []
    for entry in value:
        title = validate_title(entry)
        if not title: raise ValueError('请填写称号文字，或移除该称号')
        if any(item['text']==title['text'] for item in result):
            raise ValueError('称号文字不能重复')
        result.append(title)
    return result


def awarded_titles_data(member):
    try:
        value = member.member_title
        if isinstance(value,dict):
            title = validate_title(value)
            return [title] if title else []
        return validate_titles(value)
    except ValueError:
        return []


def titles_data(member):
    worn=getattr(member,'worn_titles',None)
    if worn is None:
        return awarded_titles_data(member)
    if not worn:
        return []
    return [title for title in available_titles_data(member) if title['text'] in worn]


def available_titles_data(member):
    """Team awards plus globally owned, active shop titles; no automatic wear."""
    from .models import OwnedTitle
    result = awarded_titles_data(member)
    seen = {title['text'] for title in result}
    from .cosmetic_terms import active_term
    owned = OwnedTitle.objects.filter(active_term(),user_id=member.user_id, inventory__quantity__gt=0).order_by('acquired_at','pk')
    for entry in owned:
        try:
            title = validate_title(entry.definition)
        except ValueError:
            continue
        if title and title['text'] not in seen:
            result.append({**title,**({'expires_at':entry.expires_at.isoformat()} if entry.expires_at else {})})
            seen.add(title['text'])
    return result
