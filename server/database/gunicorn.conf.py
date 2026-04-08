import os


bind = f"0.0.0.0:{os.getenv('PORT', '8386')}"
workers = int(os.getenv('WEB_CONCURRENCY', '2'))
threads = int(os.getenv('GUNICORN_THREADS', '4'))
worker_class = 'gthread'
timeout = int(os.getenv('GUNICORN_TIMEOUT', '30'))
graceful_timeout = 30
keepalive = 30
max_requests = 1000
max_requests_jitter = 100
accesslog = '-'
errorlog = '-'
capture_output = True
