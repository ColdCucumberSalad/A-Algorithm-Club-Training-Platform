import re
from django.core.files.storage import default_storage
from django.db import transaction,IntegrityError
from django.http import JsonResponse,FileResponse,Http404
from django.views.decorators.http import require_http_methods
from .views import api_login_required,api_error,body
from .models import CosmeticAsset
from .cosmetic_assets import serialize,save_asset,read_package,store_image,validate_components

def private(data):
    response=JsonResponse(data);response['Cache-Control']='private, no-store';return response

@api_login_required
@require_http_methods(['GET','POST'])
def assets(request):
    if not request.user.is_superuser:return api_error('需要系统管理员权限',403)
    if request.method=='GET':return private({'assets':[serialize(a) for a in CosmeticAsset.objects.order_by('kind','name')]})
    try:return private({'asset':save_asset(body(request))})
    except ValueError as exc:return api_error(str(exc),400)
    except IntegrityError:return api_error('资源标识已被其他操作创建，请刷新后重试',409)

@api_login_required
@require_http_methods(['POST'])
def upload(request):
    if not request.user.is_superuser:return api_error('需要系统管理员权限',403)
    image=request.FILES.get('file')
    if not image:return api_error('请选择图片')
    if image.size>8*1024*1024:return api_error('图片最多8MB')
    try:return private({'url':store_image(image.read())})
    except ValueError as exc:return api_error(str(exc))

@api_login_required
@require_http_methods(['POST'])
def package(request):
    if not request.user.is_superuser:return api_error('需要系统管理员权限',403)
    file=request.FILES.get('file')
    if not file:return api_error('请选择主题包ZIP')
    try:return private(read_package(file))
    except ValueError as exc:return api_error(str(exc))

@api_login_required
@require_http_methods(['POST'])
@transaction.atomic
def import_package(request):
    if not request.user.is_superuser:return api_error('需要系统管理员权限',403)
    data=body(request);definitions=data.get('assets')
    if not isinstance(definitions,list) or not 1<=len(definitions)<=12:return api_error('需提供1–12项资源')
    try:
        # Savepoint ensures a duplicate/invalid later item cannot leave a partial import.
        with transaction.atomic():
            saved=[save_asset(d,create_only=True) for d in definitions]
            components=validate_components(data.get('components'),{(d['kind'],d['key']):d for d in saved})
    except ValueError as exc:return api_error(str(exc),400)
    except IntegrityError:return api_error('资源标识已被其他操作创建，请刷新后重试',409)
    return private({'assets':saved,'components':components})

@require_http_methods(['GET'])
def media(request,filename):
    if not re.fullmatch(r'[a-f0-9]{64}\.png',filename):raise Http404
    name='cosmetics/'+filename
    if not default_storage.exists(name):raise Http404
    response=FileResponse(default_storage.open(name,'rb'),content_type='image/png')
    response['Cache-Control']='public, max-age=31536000, immutable'
    response['X-Content-Type-Options']='nosniff'
    response['Content-Security-Policy']="default-src 'none'; sandbox"
    return response
