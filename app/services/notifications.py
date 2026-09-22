"""Web Push delivery from a durable outbox. No HTTP requests run in a checkout."""
import base64
import json
import time
from urllib.parse import urlsplit

import click
from flask import current_app

from app.database import get_supabase
from app.services.errors import UserError


def _decode(value, expected):
    if not isinstance(value, str) or len(value) > 150:
        raise ValueError
    decoded = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    if len(decoded) != expected:
        raise ValueError
    return decoded


def validate_subscription(subscription):
    if not isinstance(subscription, dict):
        raise UserError('ข้อมูลการแจ้งเตือนไม่ถูกต้อง')
    endpoint = subscription.get('endpoint')
    try:
        if not isinstance(endpoint, str) or len(endpoint) > 2048:
            raise ValueError
        url = urlsplit(endpoint)
        allowed = {host.strip().lower() for host in current_app.config['PUSH_ALLOWED_HOSTS'] if host.strip()}
        if url.scheme != 'https' or url.hostname not in allowed or url.port not in (None, 443) or url.username or url.password or url.fragment:
            raise ValueError
        keys = subscription['keys']
        if _decode(keys['p256dh'], 65)[0] != 4:
            raise ValueError
        _decode(keys['auth'], 16)
    except (ValueError, KeyError, TypeError):
        raise UserError('ข้อมูลการแจ้งเตือนไม่ถูกต้องหรือบริการ push นี้ยังไม่รองรับ')
    return {'endpoint': endpoint, 'keys': {'p256dh': keys['p256dh'], 'auth': keys['auth']}}


def push_enabled():
    return all(current_app.config.get(key) for key in ('VAPID_PRIVATE_KEY', 'VAPID_PUBLIC_KEY', 'VAPID_SUBJECT'))


def deliver_batch(limit=20, sender=None):
    config = current_app.config
    if not push_enabled():
        raise RuntimeError('Configure VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY and VAPID_SUBJECT before running the push worker.')
    if sender is None:
        from pywebpush import webpush
        sender = webpush
    db = get_supabase()
    jobs = db.rpc('claim_notification_outbox', {'p_limit': limit}).execute().data or []
    delivered = failed = 0
    for job in jobs:
        success, error_type = True, ''
        try:
            order_response = db.table('orders').select('id,status,order_code').eq('id', job['order_id']).limit(1).execute()
            order = order_response.data[0] if order_response.data else None
            subscriptions = db.table('push_subscriptions').select('*').eq('order_id', job['order_id']).execute().data if job['event'] == 'ready' and order and order['status'] == 'ready' else []
            for entry in subscriptions or []:
                try:
                    subscription = validate_subscription(entry)
                    # Capabilities and personal data do not belong in push payloads.
                    sender(subscription_info=subscription,
                           data=json.dumps({'title': 'อาหารพร้อมรับแล้ว', 'body': f"ออเดอร์ {order['order_code']} พร้อมรับที่ร้าน", 'url': '/history', 'tag': f"order-{order['id']}-ready"}, ensure_ascii=False),
                           vapid_private_key=config['VAPID_PRIVATE_KEY'],
                           vapid_claims={'sub': config['VAPID_SUBJECT']}, ttl=900, timeout=10)
                except Exception as exc:
                    status = getattr(getattr(exc, 'response', None), 'status_code', None)
                    if status in (404, 410) or isinstance(exc, UserError):
                        db.table('push_subscriptions').delete().eq('id', entry['id']).execute()
                    else:
                        success, error_type = False, type(exc).__name__
        except Exception as exc:
            success, error_type = False, type(exc).__name__
        try:
            db.rpc('finish_notification_outbox', {'p_id': job['id'], 'p_success': success, 'p_error': error_type}).execute()
        except Exception as exc:
            # A temporary DB failure leaves the lease to expire for a later retry.
            success = False
            current_app.logger.warning('notification_finish_failed job_id=%s type=%s', job['id'], type(exc).__name__)
        delivered += int(success)
        failed += int(not success)
    return {'processed': len(jobs), 'delivered': delivered, 'failed': failed}


def register_commands(app):
    def run_loop(loop_forever, limit, interval, require_push=False):
        if require_push and not push_enabled():
            raise click.ClickException('Configure all VAPID values first, or use run-worker for expiration without push.')
        failures = 0
        while True:
            try:
                expired = get_supabase().rpc('expire_unpaid_orders', {}).execute().data
                result = deliver_batch(limit) if push_enabled() else {'processed': 0, 'delivered': 0, 'failed': 0}
                result.update(expired=expired, push_enabled=push_enabled())
                click.echo(json.dumps(result))
                failures = 0
            except Exception as exc:
                failures += 1
                current_app.logger.error('worker_cycle_failed type=%s', type(exc).__name__)
                if not loop_forever:
                    raise click.ClickException('Worker could not complete this cycle. Check database access and migration.') from None
            if not loop_forever:
                break
            time.sleep(min(60, interval * 2 ** min(failures, 3)))

    @app.cli.command('run-worker')
    @click.option('--loop', 'loop_forever', is_flag=True, help='Keep expiring payments and delivering configured push alerts.')
    @click.option('--limit', default=20, type=click.IntRange(1, 100))
    @click.option('--interval', default=10, type=click.IntRange(5, 60))
    def run_worker(loop_forever, limit, interval):
        """Run background order maintenance, with or without Web Push configured."""
        run_loop(loop_forever, limit, interval)

    @app.cli.command('process-notifications')
    @click.option('--loop', 'loop_forever', is_flag=True, help='Run a dedicated worker, checking every 10 seconds.')
    @click.option('--limit', default=20, type=click.IntRange(1, 100))
    def process_notifications(loop_forever, limit):
        """Deliver ready notifications with retry and expire abandoned payments."""
        run_loop(loop_forever, limit, 10, require_push=True)

    @app.cli.command('expire-unpaid')
    def expire_unpaid():
        """Expire abandoned transfer orders (safe to run periodically)."""
        result = get_supabase().rpc('expire_unpaid_orders', {}).execute().data
        click.echo(json.dumps(result))
