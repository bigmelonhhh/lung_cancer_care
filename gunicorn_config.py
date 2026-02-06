# gunicorn_config.py
import multiprocessing

# 监听地址和端口
bind = "0.0.0.0:8000"

# 工作进程数：公式通常为 (2 * CPU核心数) + 1
workers = multiprocessing.cpu_count() * 2 + 1

# 运行模式：建议使用 gevent (需安装) 或默认的 sync
worker_class = 'sync'

# 最大并发连接数
worker_connections = 1000

# 日志配置
accesslog = "/data/projects/lung_cancer_care/logs/gunicorn_access.log"
errorlog = "/data/projects/lung_cancer_care/logs/gunicorn_error.log"
loglevel = "info"

# 进程名
proc_name = 'gunicorn_lung_cancer_care'

# 设置超时时间，防止某些长请求导致进程死掉
timeout = 30