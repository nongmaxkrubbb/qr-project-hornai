"""Push delivery, endpoint validation, and production startup fail-closed checks."""
import base64
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from app.services.errors import UserError
from app.services.notifications import deliver_batch, validate_subscription


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def subscription(endpoint="https://fcm.googleapis.com/fcm/send/example"):
    return {"id": 7, "order_id": 1, "endpoint": endpoint,
            "keys": {"p256dh": encoded(b"\x04" + b"\x01" * 64), "auth": encoded(b"\x02" * 16)}}


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.remove = db, table, [], False

    def select(self, *args, **kwargs):
        return self

    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self

    def limit(self, *args):
        return self

    def delete(self):
        self.remove = True
        return self

    def execute(self):
        rows = [row for row in self.db.rows.get(self.table, []) if all(test(row) for test in self.filters)]
        if self.remove:
            self.db.removed.extend(row["id"] for row in rows)
            self.db.rows[self.table] = [row for row in self.db.rows[self.table] if row not in rows]
        return SimpleNamespace(data=copy.deepcopy(rows))


class PushDB:
    def __init__(self, status="ready", events=None):
        self.jobs = [{"id": index + 10, "order_id": 1, "event": event} for index, event in enumerate(events or ["ready"])]
        self.rows = {"orders": [{"id": 1, "status": status, "order_code": "Q001"}],
                     "push_subscriptions": [subscription()]}
        self.finished, self.removed = [], []

    def table(self, table):
        return Query(self, table)

    def rpc(self, name, params):
        if name == "claim_notification_outbox":
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=copy.deepcopy(self.jobs)))
        if name == "finish_notification_outbox":
            self.finished.append(copy.deepcopy(params))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=None))
        raise AssertionError(f"Unexpected RPC: {name}")


class PushFailure(Exception):
    def __init__(self, status):
        self.response = SimpleNamespace(status_code=status)
        super().__init__("Sensitive provider details must not be stored")


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(VAPID_PRIVATE_KEY="private-test", VAPID_PUBLIC_KEY="public-test",
                               VAPID_SUBJECT="mailto:operator@example.test",
                               PUSH_ALLOWED_HOSTS=["fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"])

    def test_official_https_endpoint_and_keys_accepted(self):
        with self.app.app_context():
            value = validate_subscription(subscription())
        self.assertEqual(value["endpoint"], subscription()["endpoint"])
        self.assertEqual(set(value), {"endpoint", "keys"})

    def test_endpoint_allowlist_rejects_ssrf_and_ambiguous_urls(self):
        invalid = ["http://fcm.googleapis.com/push", "https://127.0.0.1/push", "https://169.254.169.254/latest/meta-data",
                   "https://[::1]/", "https://evil.test/", "https://fcm.googleapis.com.evil.test/push",
                   "https://user:password@fcm.googleapis.com/push", "https://fcm.googleapis.com:444/push",
                   "https://fcm.googleapis.com:invalid/push", "https://fcm.googleapis.com/push#fragment",
                   "file:///etc/passwd", "/relative/push"]
        with self.app.app_context():
            for endpoint in invalid:
                with self.subTest(endpoint=endpoint), self.assertRaises(UserError):
                    validate_subscription(subscription(endpoint))

    def test_malformed_key_material_is_rejected(self):
        malformed = [None, [], {}, {"endpoint": subscription()["endpoint"], "keys": None}]
        for key, value in (("p256dh", "not@base64"), ("auth", "wrong"), ("auth", "A" * 151),
                           ("p256dh", encoded(b"\x03" + b"\x01" * 64)), ("p256dh", encoded(b"\x04" * 64)),
                           ("auth", encoded(b"\x02" * 15))):
            entry = subscription()
            entry["keys"][key] = value
            malformed.append(entry)
        with self.app.app_context():
            for entry in malformed:
                with self.subTest(entry=entry), self.assertRaises(UserError):
                    validate_subscription(entry)

    def test_missing_any_vapid_setting_stops_before_database_or_sender(self):
        with self.app.app_context(), patch("app.services.notifications.get_supabase") as database:
            sender = Mock()
            for key in ("VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT"):
                original = self.app.config[key]
                self.app.config[key] = ""
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    deliver_batch(sender=sender)
                self.app.config[key] = original
            database.assert_not_called()
            sender.assert_not_called()

    def test_only_ready_event_sends_once_among_queued_state_events(self):
        db = PushDB(events=["waiting", "payment_paid", "preparing", "ready"])
        sender = Mock()
        with self.app.app_context(), patch("app.services.notifications.get_supabase", return_value=db):
            result = deliver_batch(sender=sender)
        sender.assert_called_once()
        notification = json.loads(sender.call_args.kwargs["data"])
        self.assertEqual(notification["url"], "/history")
        self.assertNotIn("token", sender.call_args.kwargs["data"])
        self.assertEqual(result["processed"], 4)
        self.assertTrue(all(entry["p_success"] for entry in db.finished))

    def test_completed_or_cancelled_order_suppresses_stale_ready_job(self):
        for status in ("completed", "cancelled", "preparing"):
            db, sender = PushDB(status=status), Mock()
            with self.subTest(status=status), self.app.app_context(), patch("app.services.notifications.get_supabase", return_value=db):
                deliver_batch(sender=sender)
            sender.assert_not_called()
            self.assertTrue(db.finished[0]["p_success"])

    def test_expired_subscription_is_deleted_without_retry(self):
        for status in (404, 410):
            db = PushDB()
            with self.subTest(status=status), self.app.app_context(), patch("app.services.notifications.get_supabase", return_value=db):
                result = deliver_batch(sender=Mock(side_effect=PushFailure(status)))
            self.assertEqual(db.removed, [7])
            self.assertTrue(db.finished[0]["p_success"])
            self.assertEqual(result["failed"], 0)

    def test_transient_provider_failure_is_retried_without_private_error_details(self):
        db = PushDB()
        with self.app.app_context(), patch("app.services.notifications.get_supabase", return_value=db):
            result = deliver_batch(sender=Mock(side_effect=PushFailure(503)))
        self.assertEqual(db.removed, [])
        self.assertFalse(db.finished[0]["p_success"])
        self.assertEqual(db.finished[0]["p_error"], "PushFailure")
        self.assertNotIn("Sensitive", str(db.finished))
        self.assertEqual(result["failed"], 1)

    def test_invalid_stored_endpoint_never_reaches_sender(self):
        db, sender = PushDB(), Mock()
        db.rows["push_subscriptions"][0]["endpoint"] = "http://169.254.169.254/secret"
        with self.app.app_context(), patch("app.services.notifications.get_supabase", return_value=db):
            deliver_batch(sender=sender)
        sender.assert_not_called()
        self.assertEqual(db.removed, [7])


class ProductionConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = {"APP_ENV": "production", "SECRET_KEY": "x" * 40,
                       "SUPABASE_URL": "https://example.invalid", "SUPABASE_ANON_KEY": "anon-test",
                       "SUPABASE_SERVICE_ROLE_KEY": "service-test", "PUBLIC_BASE_URL": "https://shop.example.test",
                       "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0", "RATELIMIT_ENABLED": False,
                       "TRUSTED_PROXY_COUNT": 0, "SESSION_COOKIE_SECURE": True}

    def test_production_rejects_short_secret_and_process_local_limits(self):
        from app import create_app
        with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
            create_app({**self.config, "SECRET_KEY": "short"})
        with self.assertRaisesRegex(RuntimeError, "shared RATELIMIT"):
            create_app({**self.config, "RATELIMIT_STORAGE_URI": "memory://"})

    def test_production_requires_real_https_origin(self):
        from app import create_app
        for origin in ("", "http://shop.example.test", "https://user:secret@shop.example.test", "https://shop.example.test/nested"):
            with self.subTest(origin=origin), self.assertRaisesRegex(RuntimeError, "HTTPS origin"):
                create_app({**self.config, "PUBLIC_BASE_URL": origin})

    def test_missing_required_service_credentials_fail_startup(self):
        from app import create_app
        for key in ("SECRET_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, key):
                create_app({**self.config, key: ""})


if __name__ == "__main__":
    unittest.main()
