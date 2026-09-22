import json
import logging
import secrets
import sys
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, render_template, request, send_from_directory, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
from postgrest.exceptions import APIError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.services.errors import UserError, database_error

limiter = Limiter(key_func=get_remote_address)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({'time': self.formatTime(record), 'level': record.levelname, 'message': record.getMessage()}, ensure_ascii=False)


def session_rate_key():
    return session.get('visitor_id') or get_remote_address()


def staff_rate_key():
    return str(session.get('staff_id') or get_remote_address())


def create_app(config=None):
    from config import Config
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.update(Config.values())
    if config:
        app.config.update(config)
    for key in ('SECRET_KEY', 'SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY'):
        if not app.config.get(key):
            raise RuntimeError(f'Missing required environment variable: {key}. See .env.example.')
    if app.config['APP_ENV'] == 'production':
        if len(app.config['SECRET_KEY']) < 32:
            raise RuntimeError('Production SECRET_KEY must contain at least 32 characters.')
        if app.config['RATELIMIT_STORAGE_URI'].startswith('memory:'):
            raise RuntimeError('Production requires shared RATELIMIT_STORAGE_URI, e.g. Redis.')
        public = urlsplit(app.config.get('PUBLIC_BASE_URL', ''))
        if public.scheme != 'https' or not public.hostname or public.username or public.password or public.path not in ('', '/') or public.query or public.fragment:
            raise RuntimeError('Production requires PUBLIC_BASE_URL as an HTTPS origin.')
    proxies = app.config['TRUSTED_PROXY_COUNT']
    if proxies < 0 or proxies > 3:
        raise RuntimeError('TRUSTED_PROXY_COUNT must be between 0 and 3.')
    if proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)

    from app.services.sessions import init_sessions
    init_sessions(app)

    @app.before_request
    def request_context():
        g.request_id = secrets.token_hex(8)
        g.started = time.monotonic()
        if request.endpoint not in ('healthz', 'readyz', 'static', 'service_worker', 'manifest') and 'visitor_id' not in session:
            session['visitor_id'] = secrets.token_urlsafe(18)
        if app.config.get('PUBLIC_BASE_URL') and request.endpoint not in ('healthz', 'readyz'):
            allowed_host = urlsplit(app.config['PUBLIC_BASE_URL']).netloc.lower()
            if request.host.lower() != allowed_host:
                raise UserError('โดเมนไม่ตรงกับที่ระบบตั้งค่าไว้', 400)

    CSRFProtect(app)
    limiter = Limiter(key_func=get_remote_address)
    limiter.init_app(app)
    from app.database import init_app
    init_app(app)
    from app.routes.user_routes import user_bp
    from app.routes.admin_routes import admin_bp
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)

    # Read-only pages are not charged to tiny shared university Wi-Fi quotas.
    limits = {
        'admin.admin_login': ('10 per minute', get_remote_address),
        'user.cart_add': ('120 per minute', session_rate_key),
        'user.cart_update': ('120 per minute', session_rate_key),
        'user.checkout': ('10 per minute', session_rate_key),
        'user.upload_slip': ('6 per minute', session_rate_key),
        'user.customer_action': ('20 per minute', session_rate_key),
        'user.push_subscribe': ('6 per minute', session_rate_key),
        'user.api_order_status': ('60 per minute', session_rate_key),
    }
    for endpoint, (limit, key) in limits.items():
        limiter.limit(limit, key_func=key, methods=['POST'] if endpoint != 'user.api_order_status' else ['GET'])(app.view_functions[endpoint])
    # Generous IP backstop for write abuse; normal sessions carry the tighter limits.
    for endpoint in ('user.checkout', 'user.upload_slip'):
        limiter.limit('600 per minute', key_func=get_remote_address, methods=['POST'])(app.view_functions[endpoint])

    @app.after_request
    def response_headers(response):
        response.headers['X-Request-ID'] = g.get('request_id', '')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store, private'
        if app.config['SESSION_COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if response.status_code >= 400:
            app.logger.warning('request_failed endpoint=%s status=%s request_id=%s', request.endpoint, response.status_code, g.get('request_id'))
        return response

    @app.context_processor
    def shared_context():
        return {'current_staff': g.get('staff'), 'app_name': 'คิวอิ่ม', 'public_base_url': app.config.get('PUBLIC_BASE_URL', '')}

    @app.template_filter('money')
    def money_filter(value):
        return f'{float(value or 0):,.2f}'

    @app.template_filter('local_datetime')
    def local_datetime_filter(value, timezone='Asia/Bangkok'):
        from app.services.orders import parse_datetime
        if not value:
            return '—'
        return parse_datetime(value).astimezone(ZoneInfo(timezone or 'Asia/Bangkok')).strftime('%d/%m/%Y %H:%M')

    @app.route('/healthz')
    def healthz():
        return jsonify(status='ok')

    @app.route('/readyz')
    def readyz():
        from app.database import get_supabase
        try:
            get_supabase().table('branches').select('id,is_accepting_orders').limit(1).execute()
            if app.extensions.get('session_redis') is not None:
                app.extensions['session_redis'].ping()
        except Exception:
            return jsonify(status='unavailable'), 503
        return jsonify(status='ready')

    @app.route('/sw.js')
    def service_worker():
        response = send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
        response.headers['Service-Worker-Allowed'] = '/'
        return response

    @app.route('/manifest.webmanifest')
    def manifest():
        return send_from_directory(app.static_folder, 'manifest.webmanifest', mimetype='application/manifest+json')

    def render_error(message, status):
        if request.path.startswith('/api/') or request.is_json or request.accept_mimetypes.best == 'application/json':
            return jsonify(error=message, request_id=g.get('request_id')), status
        return render_template('errors.html', message=message, status=status, request_id=g.get('request_id')), status

    @app.errorhandler(UserError)
    def user_error(error):
        return render_error(error.message, error.status)

    @app.errorhandler(APIError)
    def api_error(error):
        known = database_error(error)
        if known:
            return render_error(known.message, known.status)
        app.logger.error('database_error code=%s request_id=%s', getattr(error, 'code', 'unknown'), g.get('request_id'))
        return render_error('ระบบขัดข้องชั่วคราว กรุณาลองอีกครั้ง หากยืนยันสั่งแล้วให้เปิดประวัติก่อนสั่งซ้ำ', 503)

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {400: 'ข้อมูลคำขอไม่ถูกต้องหรือแบบฟอร์มหมดอายุ กรุณาเปิดหน้าใหม่', 403: 'คุณไม่มีสิทธิ์เข้าถึงหน้านี้', 404: 'ไม่พบหน้าหรือรายการนี้',
                    405: 'ไม่รองรับวิธีเรียกหน้านี้', 413: 'ไฟล์มีขนาดใหญ่เกินกำหนด', 429: 'ทำรายการถี่เกินไป กรุณารอสักครู่แล้วลองอีกครั้ง'}
        return render_error(messages.get(error.code, 'ไม่สามารถทำรายการนี้ได้'), error.code)

    @app.errorhandler(Exception)
    def unexpected(error):
        # Avoid recording SQL parameters, tokens, uploaded content or customer data.
        app.logger.error('unhandled_error type=%s request_id=%s', type(error).__name__, g.get('request_id'))
        return render_error('ระบบขัดข้องชั่วคราว กรุณาติดต่อร้านพร้อมรหัสเหตุการณ์ด้านล่าง', 500)

    from app.services.notifications import register_commands
    register_commands(app)
    return app
