# wx/services/client.py
import os
from wechatpy import WeChatClient
from wechatpy.session.redisstorage import RedisStorage
from django_redis import get_redis_connection # 如果你用了 django-redis

WX_APPID = os.getenv("WX_APPID")
WX_APPSECRET = os.getenv("WX_APPSECRET")

# 获取 Django 配置好的 Redis 连接
# 假设你在 settings.py 里配置了 CACHES
redis_conn = get_redis_connection("default") 
session_storage = RedisStorage(redis_conn)

# 传入 session_storage，让大家公用一个 Redis 存 token
wechat_client = WeChatClient(
    WX_APPID, 
    WX_APPSECRET, 
    session=session_storage
)