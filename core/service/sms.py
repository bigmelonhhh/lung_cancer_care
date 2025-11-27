import time
import random
import requests
import logging
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# 常量定义
CACHE_KEY_CODE = "sms:code:{}"       # 存储验证码
CACHE_KEY_LIMIT = "sms:limit:{}"     # 存储60s发送限制
CODE_EXPIRE_SECONDS = 300            # 验证码有效期 5分钟
LIMIT_SECONDS = 60                   # 发送间隔 60秒

class SMSService:
    
    @staticmethod
    def _send_api_request(phone, message):
        """
        内部方法：实际调用第三方 HTTP 接口
        [cite_start]参考文档: SendMessageStr 接口 [cite: 56]
        """
        config = settings.SMS_CONFIG

        # [cite_start]参数构造 [cite: 54]
        params = {
            'Id': config['ORG_ID'],
            'Name': config['USERNAME'],
            'Psw': config['PASSWORD'],
            'Message': message, # requests 会自动处理 UTF-8 URL 转码 [cite: 55]
            'Phone': phone,
            'Timestamp': int(time.time())
        }

        try:
            # 使用 requests 调用 API_URL
            response = requests.get(config['API_URL'], params=params, timeout=5)
            
            # [cite_start]解析返回字符串，格式如: State:1, Id:35, FailPhone:... [cite: 59]
            # 我们只需要简单的解析
            res_text = response.text
            res_data = {}
            for item in res_text.split(','):
                if ':' in item:
                    k, v = item.split(':', 1)
                    res_data[k.strip()] = v.strip()
            
            # [cite_start]State:1 代表成功 [cite: 59]
            if res_data.get('State') == '1':
                return True, None
            else:
                return False, f"供应商错误码: {res_data.get('State')}"
                
        except Exception as e:
            logger.error(f"短信接口调用异常: {str(e)}")
            return False, "网络请求失败"

    @classmethod
    def send_verification_code(cls, phone):
        """
        业务方法 1: 发送验证码（包含频率限制、生成、存储、发送）
        """
        # 1. 检查频率限制 (60秒内是否发过)
        limit_key = CACHE_KEY_LIMIT.format(phone)
        ttl = cache.ttl(limit_key) # 获取剩余时间(django-redis特性)
        if ttl and ttl > 0:
            return False, f"发送太频繁，请 {ttl} 秒后再试"
        
        # 2. 生成4位验证码
        code = str(random.randint(1000, 9999))
        
        # 3. 构造短信内容
        # [cite_start]文档提到可能需要签名，且长短信不超过300字 [cite: 46]
        signature = settings.SMS_CONFIG.get('SIGNATURE', '')
        message = f"{signature}您的验证码是：{code}，5分钟内有效。如非本人操作请忽略。"

        # 4. 调用发送接口
        success, error_msg = cls._send_api_request(phone, message)
        
        if success:
            # 5. 发送成功后：
            # A. 存验证码 (5分钟过期)
            cache.set(CACHE_KEY_CODE.format(phone), code, CODE_EXPIRE_SECONDS)
            # B. 存频率限制 (60秒过期)
            cache.set(limit_key, "1", LIMIT_SECONDS)
            
            # 开发环境为了方便调试，打印出来
            if settings.DEBUG:
                print(f"====== [DEV] 手机号: {phone} 验证码: {code} ======")
                
            return True, "发送成功"
        else:
            return False, error_msg

    @classmethod
    def verify_code(cls, phone, code):
        """
        业务方法 2: 校验验证码
        """
        cache_key = CACHE_KEY_CODE.format(phone)
        cached_code = cache.get(cache_key)

        if not cached_code:
            return False, "验证码已过期或未发送"
        
        if str(cached_code) == str(code):
            # 验证成功后，立即删除验证码，防止二次使用（防重放）
            cache.delete(cache_key)
            return True, "验证成功"
        else:
            return False, "验证码错误"