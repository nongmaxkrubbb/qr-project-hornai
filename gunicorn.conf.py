import os

bind = '0.0.0.0:' + os.getenv('PORT', '8000')
workers = int(os.getenv('WEB_CONCURRENCY', '2'))
threads = 4
timeout = 45
accesslog = '-'
errorlog = '-'
# U is the path WITHOUT query parameters: order access tokens must stay out of logs.
access_log_format = '%(t)s %(m)s %(U)s %(s)s %(L)s request_id=%({x-request-id}o)s'
