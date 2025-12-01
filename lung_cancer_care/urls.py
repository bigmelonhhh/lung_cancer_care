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
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.http import HttpResponse
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from devices.views.callback import smartwatch_data_callback
import os

def wechat_verify_view(request):
    # 文件名必须与微信后台提供的一致
    filename = "MP_verify_CHZvy99Xmr1t237O.txt"
    # 拼接文件的完整路径 (假设文件在项目根目录，即 BASE_DIR)
    file_path = os.path.join(settings.BASE_DIR, filename)
    
    
    with open(file_path, 'r') as f:
        content = f.read()
    # 微信要求返回纯文本内容
    return HttpResponse(content, content_type="text/plain")
    

# 2. 修改 Admin 站点的文案配置
admin.site.site_header = '肺部康复管理系统后台'  # 登录页的大标题 / 每一页顶部的标题
admin.site.site_title = '肺部康复管理系统'     # 浏览器标签页的 Title
admin.site.index_title = '后台管理首页'         # 登录进去后，面包屑导航后面的文字
admin.site.logout = LogoutView.as_view(next_page='/admin/')



urlpatterns = [

    path('MP_verify_CHZvy99Xmr1t237O.txt', wechat_verify_view),

    path('admin/', admin.site.urls),
    
    path('users/', include('users.urls')),
    path('wx/', include('wx.urls', namespace='wx')),
    path('regions/', include('regions.urls', namespace='regions')),
    path('', include('web_doctor.urls')),
    path('', include('web_sales.urls')),
    path('p/', include('web_patient.urls', namespace='web_patient')),
    path('deviceupload/', smartwatch_data_callback, name='device_upload_root'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
