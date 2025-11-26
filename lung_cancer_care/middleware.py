# lung_cancer_care/middleware.py
import time
import uuid
import logging

logger = logging.getLogger("lung_cancer_care.request")

class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. 记录开始时间
        start_time = time.time()
        
        # 2. 生成或获取 Request ID (方便追踪链路)
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.request_id = request_id  # 绑定到 request 对象供 view 使用

        # 3. 执行视图处理
        response = self.get_response(request)

        # 4. 计算耗时
        duration = time.time() - start_time
        duration_str = f"{duration:.3f}"

        # 5. 获取真实 IP
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            real_ip = x_forwarded_for.split(',')[0]
        else:
            real_ip = request.META.get('REMOTE_ADDR')

        # 6. 获取用户信息
        user_info = "-"
        if hasattr(request, "user") and request.user.is_authenticated:
            # 格式示例: "1:ericliu"
            user_info = f"{request.user.id}:{getattr(request.user, 'username', 'unknown')}"

        # 7. 计算响应体大小 (仅针对非流式响应)
        try:
            body_bytes = len(response.content)
        except AttributeError:
            body_bytes = 0  # StreamingHttpResponse 没有 content 属性

        # 8. 组装日志字典 (完全匹配你的格式要求)
        log_data = {
            
            "remote_addr": request.META.get('REMOTE_ADDR', '-'),
            "real_ip": real_ip,
            "request": f"{request.method} {request.get_full_path()}",
            "body_bytes_sent": str(body_bytes),
            "upstream_response_time": duration_str, # 应用处理时间
            "http_user_agent": request.META.get('HTTP_USER_AGENT', '-'),
            "request_id": request_id,
            "user": user_info,
            "status": str(response.status_code),
            "request_time": duration_str,
            
            # 'level', 'logger', 'time_local' 会由 JsonFormatter 自动补充
        }

        # 9. 打印日志
        logger.info(log_data)

        return response