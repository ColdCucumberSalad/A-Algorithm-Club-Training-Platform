"""Account-owned cosmetic entitlements with per-team badge/frame choices."""
from django.utils import timezone
from .models import CosmeticGrant,UserInventory,PurchaseBadgeGrant
from .cosmetic_terms import active_term,purchase_terms
from contextvars import ContextVar
from functools import wraps

_read_cache=ContextVar('cosmetic_read_cache',default=None)

def catalog_scope(view):
    """Cache read-only catalog/entitlements within a single GET, never across users or writes."""
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        token=_read_cache.set({})
        try:return view(request,*args,**kwargs)
        finally:_read_cache.reset(token)
    return wrapped

BADGES={'taffy':{'key':'taffy','name':'小塔菲 · 原版','icon':'/static/cosmetics/taffy-original-head.svg'},
        'rbc-pendant':{'key':'rbc-pendant','name':'RBC 挂坠纪念徽章','icon':'/static/cosmetics/rbc-pendant-badge.png'}}
FRAMES={'taffy-goggles':{'key':'taffy-goggles','name':'塔菲护目镜','icon':'/static/cosmetics/taffy-goggles-frame.svg'}}
THEMES={'taffy':{'key':'taffy','name':'塔菲 · 小菲滚轴','poster':'/static/cosmetics/taffy-scroll.jpg','gift_badges':['taffy'],'gift_frames':['taffy-goggles']}}
CATALOG={'badge':BADGES,'theme':THEMES,'frame':FRAMES}


def catalog(kind,include_inactive=False):
    from .models import CosmeticAsset
    cache=_read_cache.get();slot=('catalog',kind,include_inactive)
    if cache is not None and slot in cache:return cache[slot]
    result={key:{**value,'kind':kind} for key,value in CATALOG[kind].items()}
    for asset in CosmeticAsset.objects.filter(kind=kind):
        if not asset.is_active and not include_inactive:result.pop(asset.key,None)
        else:result[asset.key]={**asset.definition,'key':asset.key,'kind':kind,'name':asset.name,'revision':asset.revision}
    if cache is not None:cache[slot]=result
    return result


def owned_records(user_id,kind):
    cache=_read_cache.get();slot=('owned',user_id,kind)
    if cache is not None and slot in cache:return cache[slot]
    result={};fallback=None
    for grant in CosmeticGrant.objects.filter(active_term(),user_id=user_id,kind=kind,inventory__quantity__gt=0).order_by('created_at','pk'):
        key,end=grant.key,grant.expires_at
        if not grant.definition:
            if fallback is None:fallback=catalog(kind,True)
            definition=fallback.get(key)
        else:definition=grant.definition
        if not definition:continue
        if key not in result or result[key][0] is not None and (end is None or end>=result[key][0]) or result[key][0] is None and end is None:
            result[key]=(end,definition)
    if kind=='badge':
        for key,definition in PurchaseBadgeGrant.objects.filter(user_id=user_id).values_list('key','definition'):
            if fallback is None:fallback=catalog(kind,True)
            if definition or key in fallback:result[key]=(None,definition or fallback[key])
    if cache is not None:cache[slot]=result
    return result


def owned_details(user_id,kind):return {key:row[0] for key,row in owned_records(user_id,kind).items()}
def owned_keys(user_id,kind):return set(owned_details(user_id,kind))
def available(user_id,kind):
    return [{**definition,'expires_at':end.isoformat() if end else None} for end,definition in owned_records(user_id,kind).values()]


def cache_equipped(members,kinds=('badge','frame')):
    from collections import defaultdict
    fields={'badge':'worn_badge','frame':'worn_avatar_frame'}
    selected=[m for m in members if any(getattr(m,fields[k],'') for k in kinds)]
    if not selected:return
    ends=defaultdict(dict);definitions=defaultdict(dict)
    fallback={kind:{key:{**d,'kind':kind} for key,d in CATALOG[kind].items()} for kind in kinds}
    from .models import CosmeticAsset
    for asset in CosmeticAsset.objects.filter(kind__in=kinds):fallback[asset.kind][asset.key]={**asset.definition,'revision':asset.revision}
    for grant in CosmeticGrant.objects.filter(active_term(),user_id__in=[m.user_id for m in selected],kind__in=kinds,inventory__quantity__gt=0).order_by('created_at','pk'):
        slot=(grant.kind,grant.key);cache=ends[grant.user_id];end=grant.expires_at
        if slot not in cache or cache[slot] is not None and (end is None or end>=cache[slot]) or cache[slot] is None and end is None:
            if not grant.definition and grant.kind not in fallback:fallback[grant.kind]=catalog(grant.kind,True)
            cache[slot]=end;definitions[grant.user_id][slot]=grant.definition or fallback[grant.kind].get(grant.key,{})
    if 'badge' in kinds:
        for uid,key,definition in PurchaseBadgeGrant.objects.filter(user_id__in=[m.user_id for m in selected]).values_list('user_id','key','definition'):
            if 'badge' not in fallback:fallback['badge']=catalog('badge',True)
            if definition or key in fallback['badge']:ends[uid][('badge',key)]=None;definitions[uid][('badge',key)]=definition or fallback['badge'][key]
    for m in selected:m._cosmetic_owned=ends[m.user_id];m._cosmetic_definitions=definitions[m.user_id]


def equipped(member,kind,field):
    key=getattr(member,field,'')
    if not key:return None
    cache=getattr(member,'_cosmetic_owned',None)
    if cache is not None:
        slot=(kind,key)
        if slot not in cache:return None
        end=cache[slot];definition=getattr(member,'_cosmetic_definitions',{}).get(slot)
        if not definition:definition=catalog(kind,True).get(key)
    else:
        row=owned_records(member.user_id,kind).get(key)
        if row is None:return None
        end,definition=row
    return {**definition,'expires_at':end.isoformat() if end else None} if definition else None


def badge_data(member):return equipped(member,'badge','worn_badge')
def frame_data(member):return equipped(member,'frame','worn_avatar_frame')


def state(user):
    from .models import UserProfile,OwnedTitle
    profile=UserProfile.objects.filter(user_id=user.pk).first()
    themes=available(user.pk,'theme');selected=getattr(profile,'active_theme','')
    return {'themes':themes,'active_theme':selected if any(t['key']==selected for t in themes) else '',
            'badges':available(user.pk,'badge'),'frames':available(user.pk,'frame'),'title_expirations':[end.isoformat() for end in OwnedTitle.objects.filter(active_term(),user=user,inventory__quantity__gt=0,expires_at__isnull=False).values_list('expires_at',flat=True)],'server_time':timezone.now().isoformat()}


def components(item):
    from .cosmetic_assets import validate_components
    assets={(kind,key):value for kind in CATALOG for key,value in catalog(kind).items()}
    if item.cosmetic_bundle:
        return [{**assets[(c['kind'],c['key'])],'duration_days':c['days']} for c in validate_components(item.cosmetic_bundle,assets)]
    if item.item_type not in ('theme','badge','frame') or (item.item_type,item.cosmetic_key) not in assets:raise ValueError('请选择已配置的装扮资源')
    primary=assets[(item.item_type,item.cosmetic_key)]
    if primary['kind']!=item.item_type:raise ValueError('资源类型与商品不符')
    result=[{**primary,'duration_days':item.cosmetic_duration_days}]
    if item.item_type=='theme':
        legacy=THEMES.get(item.cosmetic_key,{})
        for kind,field in [('badge','gift_badges'),('frame','gift_frames')]:
            for key in legacy.get(field,[]):
                if (kind,key) in assets:result.append({**assets[(kind,key)],'duration_days':item.cosmetic_duration_days})
    return result


def ensure_available(user_id,item,quantity):
    if quantity!=1:raise ValueError('装扮每次只能购买或发放一套')
    entries=components(item)
    owned={kind:owned_details(user_id,kind) for kind in {c['kind'] for c in entries}}
    if all(c['key'] in owned[c['kind']] and owned[c['kind']][c['key']] is None for c in entries):raise ValueError('已永久拥有全部装扮，无需重复购买')
    return entries


def award(member,item,quantity,purchase=None):
    from datetime import timedelta
    entries=ensure_available(member.user_id,item,quantity)
    prior={kind:owned_records(member.user_id,kind) for kind in {c['kind'] for c in entries}}
    inventory,_=UserInventory.objects.get_or_create(team=item.team,member=member,item=item)
    now=timezone.now()
    source_prior={(g.kind,g.key):(g.expires_at,g.definition) for g in CosmeticGrant.objects.filter(active_term(now),inventory=inventory)} if inventory.quantity>0 else {}
    if inventory.quantity<=0:
        CosmeticGrant.objects.filter(active_term(now),inventory=inventory).update(expires_at=now)
    inventory.quantity=1;inventory.save(update_fields=['quantity'])
    snapshots=[]
    for definition in entries:
        key,kind=definition['key'],definition['kind'];days=definition['duration_days']
        previous=prior[kind].get(key)
        if previous and previous[0] is None:
            # A permanent entitlement from another purchase must not become a
            # permanent grant on this independently revocable source.
            previous=source_prior.get((kind,key))
        if previous and previous[0] is None:
            CosmeticGrant.objects.update_or_create(user_id=member.user_id,inventory=inventory,kind=kind,key=key,defaults={'expires_at':None,'definition':previous[1]})
            snapshots.append({**previous[1],'duration_days':days,'expires_at':None,'already_permanent':True});continue
        end=max(now,previous[0] if previous else now)+timedelta(days=days) if days else None
        CosmeticGrant.objects.update_or_create(user_id=member.user_id,inventory=inventory,kind=kind,key=key,defaults={'expires_at':end,'definition':definition})
        snapshots.append({**definition,'expires_at':end.isoformat() if end else None})
    if purchase:
        purchase.cosmetic_snapshot=snapshots;purchase.save(update_fields=['cosmetic_snapshot'])


def product_data(item):
    if item.item_type not in ('theme','badge','frame','cosmetic'):return {}
    try:return components(item)[0]
    except ValueError:return {}


def gift_badge_data(item):return catalog('badge').get(item.gift_badge_key) if item.item_type=='physical' else None


def award_purchase_badge(purchase):
    badge=gift_badge_data(purchase.item)
    if badge:PurchaseBadgeGrant.objects.get_or_create(user_id=purchase.member.user_id,key=badge['key'],defaults={'purchase':purchase,'definition':badge})
