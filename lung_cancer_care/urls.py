"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404, HttpResponse
from django.urls import include, path

from business_support.views import smartwatch_data_callback

def wechat_verify_view(request):
    # 文件名必须与微信后台提供的一致
    filename = getattr(settings, "WECHAT_VERIFY_FILENAME", "")
    if not filename:
        raise Http404("WeChat verify filename not configured.")
    # 拼接文件的完整路径 (假设文件在项目根目录，即 BASE_DIR)
    file_path = os.path.join(settings.BASE_DIR, filename)
    if not os.path.exists(file_path):
        raise Http404("WeChat verify file not found.")

    with open(file_path, "r") as f:
        content = f.read()
    # 微信要求返回纯文本内容
    return HttpResponse(content, content_type="text/plain")
    

urlpatterns = []

if getattr(settings, "WECHAT_VERIFY_FILENAME", ""):
    urlpatterns.append(path(settings.WECHAT_VERIFY_FILENAME, wechat_verify_view))

urlpatterns += [

    path('admin/', admin.site.urls),
    
    path('users/', include('users.urls')),
    path('wx/', include('wx.urls', namespace='wx')),
    path('regions/', include('regions.urls', namespace='regions')),
    path('', include('web_doctor.urls')),
    path('', include('web_sales.urls')),
    path('p/', include('web_patient.urls', namespace='web_patient')),
    path('market/', include('market.urls', namespace='market')),
    path('deviceupload', smartwatch_data_callback, name='device_upload_root'),
    path('deviceupload/', smartwatch_data_callback),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
