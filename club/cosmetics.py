"""Account-owned cosmetic entitlements with per-team badge/frame choices."""
from django.utils import timezone
from .models import CosmeticGrant,UserInventory
from .cosmetic_terms import active_term,purchase_terms

BADGES={'taffy':{'key':'taffy','name':'小塔菲 · 原版','icon':'/static/cosmetics/taffy-original-head.svg'}}
FRAMES={'taffy-goggles':{'key':'taffy-goggles','name':'塔菲护目镜','icon':'/static/cosmetics/taffy-goggles-frame.svg'}}
THEMES={'taffy':{'key':'taffy','name':'塔菲 · 小菲滚轴','poster':'/static/cosmetics/taffy-scroll.jpg','gift_badges':['taffy'],'gift_frames':['taffy-goggles']}}
CATALOG={'badge':BADGES,'theme':THEMES,'frame':FRAMES}


def owned_details(user_id,kind):
    result={}
    for key,end in CosmeticGrant.objects.filter(active_term(),user_id=user_id,kind=kind,key__in=CATALOG[kind],inventory__quantity__gt=0).values_list('key','expires_at'):
        if key not in result or result[key] is not None and (end is None or end>result[key]):result[key]=end
    return result


def owned_keys(user_id,kind):
    return set(owned_details(user_id,kind))


def available(user_id,kind):
    details=owned_details(user_id,kind)
    return [{**value,'expires_at':details[key].isoformat() if details[key] else None} for key,value in CATALOG[kind].items() if key in details]


def equipped(member,kind,field):
    key=getattr(member,field,'')
    if not key or key not in CATALOG[kind]:return None
    cache=getattr(member,'_cosmetic_owned',None)
    details={k[1]:end for k,end in cache.items() if k[0]==kind} if cache is not None else owned_details(member.user_id,kind)
    return {**CATALOG[kind][key],'expires_at':details[key].isoformat() if details[key] else None} if key in details else None


def badge_data(member):
    return equipped(member,'badge','worn_badge')


def frame_data(member):
    return equipped(member,'frame','worn_avatar_frame')


def state(user):
    from .models import UserProfile,OwnedTitle
    profile=UserProfile.objects.filter(user_id=user.pk).first()
    themes=available(user.pk,'theme');selected=getattr(profile,'active_theme','')
    return {'themes':themes,'active_theme':selected if any(t['key']==selected for t in themes) else '',
            'badges':available(user.pk,'badge'),'frames':available(user.pk,'frame'),'title_expirations':[end.isoformat() for end in OwnedTitle.objects.filter(active_term(),user=user,inventory__quantity__gt=0,expires_at__isnull=False).values_list('expires_at',flat=True)],'server_time':timezone.now().isoformat()}


def ensure_available(user_id,item,quantity):
    if quantity!=1:raise ValueError('外观每次只能获得一件')
    if item.cosmetic_key not in CATALOG.get(item.item_type,{}):raise ValueError('请选择已配置的外观商品')
    if item.cosmetic_key in owned_keys(user_id,item.item_type):raise ValueError('已拥有该外观，无需重复购买或发放')


def award(member,item,quantity,purchase=None):
    ensure_available(member.user_id,item,quantity)
    inventory,_=UserInventory.objects.get_or_create(team=item.team,member=member,item=item)
    inventory.quantity=1;inventory.save(update_fields=['quantity'])
    end=purchase.cosmetic_expires_at if purchase else purchase_terms(item)['cosmetic_expires_at']
    def grant(kind,key):
        CosmeticGrant.objects.update_or_create(user_id=member.user_id,inventory=inventory,kind=kind,key=key,defaults={'expires_at':end})
    grant(item.item_type,item.cosmetic_key)
    if item.item_type=='theme':
        for key in THEMES[item.cosmetic_key].get('gift_badges',[]):grant('badge',key)
        for key in THEMES[item.cosmetic_key].get('gift_frames',[]):grant('frame',key)


def product_data(item):
    return CATALOG.get(item.item_type,{}).get(item.cosmetic_key,{})
