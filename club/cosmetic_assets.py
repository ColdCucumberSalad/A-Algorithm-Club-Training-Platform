"""Declarative cosmetics: no executable package content or remote image URLs."""
import hashlib
import io
import json
import re
import stat
import warnings
import zipfile
from pathlib import Path,PurePosixPath
from PIL import Image,ImageOps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from .models import CosmeticAsset

ROLES=('pageBackground','surface','surfaceElevated','separator','labelPrimary','labelSecondary','labelTertiary','fill','accent','overlayDim')
PALETTES={
 'light':dict(zip(ROLES,('#fff3f7','#fff9fb','#fffafd','#e8cdd8','#513d46','#92717e','#a98a97','#f9eaf0','#b96c88','#36252e99'))),
 'dark':dict(zip(ROLES,('#24151f','#2c1d26','#30212a','#60424f','#f3e6ec','#bca1af','#a68a99','#3d2834','#dfa0b7','#160c12bd'))),
}
KEY=re.compile(r'^[a-z][a-z0-9-]{0,39}$')
IMAGE=re.compile(r'^/api/cosmetic-assets/media/[a-f0-9]{64}\.png$')
STATIC=re.compile(r'^/static/cosmetics/[a-zA-Z0-9_-]+\.(?:png|jpg|jpeg|webp|svg)$')

def image_url(value):
    if value in ('',None):return ''
    if not isinstance(value,str) or not (IMAGE.fullmatch(value) or STATIC.fullmatch(value)):
        raise ValueError('图片必须由素材上传接口提供')
    if STATIC.fullmatch(value) and not (Path(settings.BASE_DIR)/value.removeprefix('/')).is_file():
        raise ValueError('静态素材不存在')
    if IMAGE.fullmatch(value) and not default_storage.exists('cosmetics/'+value.rsplit('/',1)[1]):
        raise ValueError('上传素材不存在，请重新上传')
    return value

def days(value):
    if type(value) is not int or not 0<=value<=36500:raise ValueError('时长必须为 0（永久）或 1–36500 天')
    return value

def validate_asset(data):
    if not isinstance(data,dict):raise ValueError('资源应为对象')
    allowed={'key','kind','name','icon','poster','background','palettes','geometry','description','duration_days','revision','is_active'}
    if set(data)-allowed:raise ValueError('存在不支持的资源字段：'+', '.join(sorted(set(data)-allowed)))
    key=data.get('key');kind=data.get('kind');name=data.get('name')
    if not isinstance(key,str) or not KEY.fullmatch(key):raise ValueError('标识需为小写字母开头的英文、数字或连字符，最多40字')
    if kind not in ('theme','badge','frame'):raise ValueError('资源类型仅支持 theme、badge、frame')
    if not isinstance(name,str) or not 1<=len(name.strip())<=100:raise ValueError('资源名称需为1–100字')
    description=data.get('description','')
    if not isinstance(description,str) or len(description)>1000:raise ValueError('资源说明最多1000字')
    result={'key':key,'kind':kind,'name':name.strip(),'description':description,'duration_days':days(data.get('duration_days',0))}
    for field in ('icon','poster','background'):result[field]=image_url(data.get(field,''))
    if kind in ('badge','frame') and not result['icon']:raise ValueError('徽章和头像框需要图片')
    if kind=='theme':
        palettes=data.get('palettes',{})
        if not isinstance(palettes,dict) or set(palettes)-{'light','dark'}:raise ValueError('色板需要 light、dark 两种模式')
        result['palettes']={}
        for mode in ('light','dark'):
            colors=palettes.get(mode,{})
            if not isinstance(colors,dict) or set(colors)-set(ROLES):raise ValueError(mode+' 色板存在未知颜色角色')
            palette={**PALETTES[mode],**colors}
            if any(not isinstance(v,str) or not re.fullmatch(r'#[a-fA-F0-9]{6}(?:[a-fA-F0-9]{2})?',v) for v in palette.values()):raise ValueError('颜色应为 #RRGGBB 或 #RRGGBBAA')
            result['palettes'][mode]=palette
    if kind=='frame':
        geometry=data.get('geometry',{})
        if not isinstance(geometry,dict) or set(geometry)-{'scale','x','y'}:raise ValueError('头像框定位参数无效')
        result['geometry']={**{'scale':1.25,'x':-.125,'y':-.225},**geometry}
        for k,v in result['geometry'].items():
            if type(v) not in (int,float) or not (1<=v<=2 if k=='scale' else -1<=v<=1):raise ValueError('头像框尺寸或偏移超出范围')
    return result

def serialize(asset):
    return {**asset.definition,'key':asset.key,'kind':asset.kind,'name':asset.name,'revision':asset.revision,'is_active':asset.is_active}

def save_asset(data,*,create_only=False):
    from django.db import transaction
    definition=validate_asset({k:v for k,v in data.items() if k not in ('revision','is_active')})
    with transaction.atomic():
        asset=CosmeticAsset.objects.select_for_update().filter(key=definition['key'],kind=definition['kind']).first()
        if asset:
            if create_only:raise ValueError('资源标识已存在：'+asset.key)
            if data.get('revision')!=asset.revision:raise ValueError('资源已被其他操作更新，请重新读取')
            if asset.kind!=definition['kind']:raise ValueError('已有资源不能改变类型')
            asset.revision+=1
        else:asset=CosmeticAsset(key=definition['key'],kind=definition['kind'])
        active=data.get('is_active',True)
        if type(active) is not bool:raise ValueError('资源状态无效')
        asset.name=definition['name'];asset.definition=definition;asset.is_active=active;asset.save()
        return serialize(asset)

def store_image(raw):
    if len(raw)>8*1024*1024:raise ValueError('单张图片最多8MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('PNG','JPEG','WEBP') or source.width*source.height>16000000 or max(source.size)>8192:raise ValueError('仅支持不超过1600万像素的PNG/JPG/WebP静态图片')
                if getattr(source,'is_animated',False):raise ValueError('暂不支持动图')
                image=ImageOps.exif_transpose(source).convert('RGBA');image.load()
                stream=io.BytesIO();image.save(stream,format='PNG');content=stream.getvalue()
    except (OSError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:raise ValueError('无法读取图片') from exc
    if len(content)>8*1024*1024:raise ValueError('图片转换后超过8MB，请先压缩素材')
    digest=hashlib.sha256(content).hexdigest();name='cosmetics/'+digest+'.png'
    if not default_storage.exists(name):
        stored=default_storage.save(name,ContentFile(content))
        if stored!=name:default_storage.delete(stored)
    return '/api/cosmetic-assets/media/'+digest+'.png'

def read_package(upload):
    if upload.size>20*1024*1024:raise ValueError('主题包最多20MB')
    try:
        with zipfile.ZipFile(upload) as archive:
            infos=archive.infolist();names=[info.filename for info in infos]
            if len(infos)>40 or len(names)!=len(set(names)) or sum(i.file_size for i in infos)>64*1024*1024:raise ValueError('主题包文件数量、重复文件或解压大小不符合规范')
            for info in infos:
                path=PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename or info.flag_bits&1 or stat.S_ISLNK(info.external_attr>>16):raise ValueError('主题包含无效路径、加密文件或链接')
                if not info.is_dir() and info.filename!='theme.json' and path.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):raise ValueError('主题包只允许theme.json和PNG/JPG/WebP素材：'+info.filename)
            if 'theme.json' not in names:raise ValueError('根目录缺少theme.json')
            info=archive.getinfo('theme.json')
            if info.file_size>128*1024:raise ValueError('theme.json过大')
            manifest=json.loads(archive.read(info).decode('utf-8-sig'))
            if not isinstance(manifest,dict) or set(manifest)-{'schema_version','name','assets','components'} or type(manifest.get('schema_version')) is not int or manifest.get('schema_version')!=1:raise ValueError('不支持的主题包版本或字段')
            definitions=manifest.get('assets')
            if not isinstance(definitions,list) or not 1<=len(definitions)<=12:raise ValueError('主题包需含1–12项装扮资源')
            prepared=[];image_urls={}
            for definition in definitions:
                if not isinstance(definition,dict):raise ValueError('资源配置无效')
                definition=dict(definition)
                for field in ('icon','poster','background'):
                    ref=definition.get(field)
                    if ref:
                        if not isinstance(ref,str) or ref not in names or ref=='theme.json':raise ValueError(field+'引用的素材不存在')
                        imageinfo=archive.getinfo(ref)
                        if imageinfo.file_size>8*1024*1024:raise ValueError(ref+'超过8MB')
                        if ref not in image_urls:image_urls[ref]=store_image(archive.read(ref))
                        definition[field]=image_urls[ref]
                prepared.append(validate_asset(definition))
            if len({(a['kind'],a['key']) for a in prepared})!=len(prepared):raise ValueError('资源标识重复')
            components=manifest.get('components',[{'kind':a['kind'],'key':a['key'],'days':a['duration_days']} for a in prepared])
            validate_components(components,{(a['kind'],a['key']):a for a in prepared})
            return {'schema_version':1,'name':str(manifest.get('name','主题套装'))[:100],'assets':prepared,'components':components}
    except (zipfile.BadZipFile,UnicodeDecodeError,json.JSONDecodeError,RuntimeError,KeyError,NotImplementedError) as exc:raise ValueError('主题包无法读取：'+str(exc)[:120]) from exc

def validate_components(value,catalog=None):
    if not isinstance(value,list) or not 1<=len(value)<=12:raise ValueError('装扮商品需选择1–12项资源')
    if catalog is None:catalog={(a.kind,a.key):serialize(a) for a in CosmeticAsset.objects.filter(is_active=True)}
    seen=set();result=[]
    for component in value:
        if not isinstance(component,dict) or set(component)!={'kind','key','days'} or not isinstance(component.get('key'),str):raise ValueError('套装内容格式无效')
        if component.get('kind') not in ('theme','badge','frame'):raise ValueError('装扮类型无效')
        key=(component['kind'],component['key'])
        if key not in catalog or key in seen:raise ValueError('资源不存在、已停用或重复：'+str(key))
        seen.add(key);result.append({'kind':key[0],'key':key[1],'days':days(component['days'])})
    return result
