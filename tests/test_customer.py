"""Customer boundaries and end-to-end request retries with an in-memory DB double."""
import copy
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from flask import Flask, jsonify
from PIL import Image, PngImagePlugin

from app.routes.user_routes import user_bp
from app.services.errors import UserError
from app.services.orders import token_hash


BRANCH_A = "00000000-0000-0000-0000-000000000011"
BRANCH_B = "00000000-0000-0000-0000-000000000012"
ITEM_A = "00000000-0000-0000-0000-000000000031"
ITEM_B = "00000000-0000-0000-0000-000000000032"
MISSING_ITEM = "00000000-0000-0000-0000-000000000039"
TOKEN = "A" * 43
WRONG_TOKEN = "B" * 43


class DomainFailure(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


class Query:
    def __init__(self, db, table):
        self.db, self.name, self.predicates, self.maximum = db, table, [], None

    def select(self, *args, **kwargs):
        return self

    def eq(self, key, value):
        self.predicates.append(lambda row: row.get(key) == value)
        return self

    def in_(self, key, values):
        self.predicates.append(lambda row: row.get(key) in values)
        return self

    def lt(self, key, value):
        self.predicates.append(lambda row: row.get(key, value) < value)
        return self

    def or_(self, expression):
        from app.services.orders import parse_datetime
        horizon = parse_datetime(expression.split("requested_for.lte.", 1)[1])
        self.predicates.append(lambda row: not row.get("requested_for") or parse_datetime(row["requested_for"]) <= horizon)
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self

    def execute(self):
        self.db.reads.append(self.name)
        rows = [row for row in self.db.rows.get(self.name, []) if all(rule(row) for rule in self.predicates)]
        return SimpleNamespace(data=copy.deepcopy(rows[:self.maximum]), count=len(rows))


class FakeDB:
    def __init__(self):
        self.reads, self.rpcs, self.uploads, self.removals = [], [], [], []
        self.fail_attachment = False
        self.created = {}
        self.storage = self
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        branch = {"id": BRANCH_A, "name": "Shop A", "is_active": True, "is_accepting_orders": True,
                  "timezone": "Asia/Bangkok", "opening_time": "00:00", "closing_time": "00:00",
                  "campus": "Campus", "pickup_point": "Counter 1", "prep_minutes": 10,
                  "kitchen_capacity": 2, "slot_minutes": 15, "slot_capacity": 0, "preorder_days": 0,
                  "promptpay_id": "0812345678", "promptpay_name": "Shop owner"}
        item = {"id": ITEM_A, "branch_id": BRANCH_A, "name": "Rice", "price": "50.00", "category": "Food",
                "is_available": True, "options": [{"id": "egg", "name": "Egg", "price": "5.00"}]}
        order = {"id": 1, "branch_id": BRANCH_A, "order_code": "Q001", "status": "pending_payment",
                 "payment_method": "promptpay", "payment_status": "pending", "total_price": "55.00",
                 "token_hash": token_hash(TOKEN), "expires_at": future, "student_name": "Private Student Name",
                 "room_no": "PRIVATE-ROOM-42", "created_at": "2026-09-21T01:00:00+00:00",
                 "slip_path": "orders/1/private.jpg", "order_items": [{"menu_item_id": ITEM_A,
                    "item_name": "Rice", "quantity": 1, "unit_price": "55.00", "options": [], "note": ""}]}
        self.rows = {"branches": [branch, dict(branch, id=BRANCH_B, name="Shop B")],
                     "menu_items": [item, dict(item, id=ITEM_B, branch_id=BRANCH_B, name="Foreign Rice")],
                     "orders": [order]}

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params):
        def execute():
            self.rpcs.append((name, copy.deepcopy(params)))
            if name == "create_order":
                key = params["p_idempotency_key"]
                fingerprint = json.dumps(params, sort_keys=True)
                if key in self.created:
                    old_fingerprint, order = self.created[key]
                    if fingerprint != old_fingerprint:
                        raise DomainFailure("idempotency_conflict")
                else:
                    order = {"id": 100 + len(self.created), "order_code": "Q100", "branch_id": params["p_branch_id"],
                             "status": "pending_payment" if params["p_payment_method"] == "promptpay" else "waiting",
                             "token_hash": params["p_token_hash"]}
                    self.created[key] = fingerprint, order
                return SimpleNamespace(data=copy.deepcopy(order))
            if name == "attach_order_slip":
                if self.fail_attachment:
                    raise DomainFailure("invalid_transition")
                self.rows["orders"][0]["slip_path"] = params["p_slip_path"]
                self.rows["orders"][0]["payment_status"] = "verifying"
            elif name == "expire_unpaid_orders":
                self.rows["orders"][0]["status"] = "cancelled"
                self.rows["orders"][0]["cancellation_reason"] = "payment_timeout"
            return SimpleNamespace(data={})
        return SimpleNamespace(execute=execute)

    def from_(self, bucket):
        self.bucket = bucket
        return self

    def upload(self, path, content, options):
        self.uploads.append((self.bucket, path, content, options))

    def remove(self, paths):
        self.removals.extend(paths)


def image_file(size=(20, 20), mode="RGBA", image_format="PNG"):
    content = io.BytesIO()
    image = Image.new(mode, size, "red")
    if image_format == "PNG":
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("private", "metadata-must-be-removed")
        image.save(content, format=image_format, pnginfo=metadata)
    else:
        image.save(content, format=image_format)
    content.seek(0)
    return content


class CustomerTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY="a-long-fixed-secret-for-business-tests", TESTING=True,
                               MAX_SLIP_BYTES=5 * 1024 * 1024, MAX_CONTENT_LENGTH=6 * 1024 * 1024)
        self.app.register_blueprint(user_bp)
        self.app.register_error_handler(UserError, lambda error: (jsonify(error=error.message), error.status))
        self.db = FakeDB()
        self.patches = [patch("app.routes.user_routes.get_supabase", return_value=self.db),
                        patch("app.services.orders.get_supabase", return_value=self.db),
                        patch("app.routes.user_routes.render_template", return_value="rendered")]
        for target in self.patches:
            target.start()
            self.addCleanup(target.stop)
        self.client = self.app.test_client()

    def add_item(self, **extra):
        return self.client.post("/cart/add", data={"branch_id": BRANCH_A, "menu_item_id": ITEM_A,
                                "quantity": "1", **extra}, headers={"Accept": "application/json"})

    def snapshot_session(self):
        with self.client.session_transaction() as session:
            return copy.deepcopy(dict(session))

    def checkout_form(self):
        session = self.snapshot_session()
        return {"idempotency_key": session["checkout_key"], "branch_id": BRANCH_A,
                "student_name": "Student", "payment_method": "cash"}

    def upload(self, content, *, token=TOKEN, filename="slip.png"):
        return self.client.post("/payment/1/upload", data={"token": token, "slip": (content, filename)},
                                content_type="multipart/form-data")

    def test_private_routes_require_matching_capability(self):
        paths = ("/order/1", "/payment/1", "/api/order_status/1")
        for token in ("", WRONG_TOKEN):
            for path in paths:
                with self.subTest(path=path, token=token):
                    self.assertEqual(self.client.get(path, query_string={"token": token}).status_code, 404)
            self.assertEqual(self.upload(image_file(), token=token).status_code, 404)
        self.assertEqual(self.db.uploads, [])
        self.assertEqual(self.db.rpcs, [])

    def test_status_response_has_no_student_identity_or_storage_credentials(self):
        response = self.client.get("/api/order_status/1", query_string={"token": TOKEN})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        serialized = json.dumps(payload)
        for secret in ("Private Student Name", "PRIVATE-ROOM-42", "orders/1/private.jpg", token_hash(TOKEN), TOKEN):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("student_name", payload)
        self.assertNotIn("room_no", payload)
        self.assertEqual(payload["branch"]["pickup_point"], "Counter 1")

    def test_terminal_order_cannot_upload_or_touch_storage(self):
        for state in ("waiting", "preparing", "ready", "completed", "cancelled"):
            self.db.rows["orders"][0]["status"] = state
            self.assertEqual(self.upload(image_file()).status_code, 409)
        self.assertEqual(self.db.uploads, [])
        self.assertEqual(self.db.rpcs, [])

    def test_expired_unsubmitted_slip_rejected_before_storage(self):
        self.db.rows["orders"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.assertEqual(self.upload(image_file()).status_code, 409)
        self.assertEqual(self.db.uploads, [])

    def test_invalid_text_gif_and_overlimit_slips_rejected(self):
        self.assertEqual(self.upload(io.BytesIO(b"not an image"), filename="looks-real.jpg").status_code, 400)
        self.assertEqual(self.upload(image_file(mode="RGB", image_format="GIF"), filename="image.gif").status_code, 400)
        self.app.config["MAX_SLIP_BYTES"] = 100
        self.assertEqual(self.upload(io.BytesIO(b"x" * 101)).status_code, 413)
        self.assertEqual(self.db.uploads, [])

    def test_compressed_image_over_pixel_limit_is_rejected(self):
        # A uniform PNG is small on disk but expands beyond the 20MP decode limit.
        response = self.upload(image_file(size=(5000, 4001), mode="RGB"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.uploads, [])

    def test_slip_is_reencoded_to_small_private_jpeg_without_metadata(self):
        response = self.upload(image_file(size=(3000, 1200)))
        self.assertEqual(response.status_code, 303)
        bucket, path, payload, options = self.db.uploads[0]
        self.assertEqual(bucket, "slips")
        self.assertRegex(path, r"^orders/1/[a-f0-9]{32}\.jpg$")
        self.assertEqual(options["content-type"], "image/jpeg")
        self.assertEqual(options["upsert"], "false")
        with Image.open(io.BytesIO(payload)) as result:
            self.assertEqual(result.format, "JPEG")
            self.assertEqual(result.mode, "RGB")
            self.assertLessEqual(max(result.size), 2400)
            self.assertNotIn("private", result.info)
        self.assertNotIn(b"metadata-must-be-removed", payload)
        self.assertEqual(self.db.rows["orders"][0]["payment_status"], "verifying")
        self.assertEqual(self.db.rows["orders"][0]["status"], "pending_payment")

    def test_state_race_removes_uploaded_orphan(self):
        self.db.fail_attachment = True
        response = self.upload(image_file())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.db.uploads), 1)
        self.assertEqual(self.db.removals, [self.db.uploads[0][1]])
        self.assertEqual(self.db.rows["orders"][0]["status"], "pending_payment")

    def test_cart_rejects_cross_branch_item_and_cross_branch_cart(self):
        self.assertEqual(self.add_item(menu_item_id=ITEM_B).status_code, 409)
        self.assertEqual(self.add_item().status_code, 200)
        before = self.snapshot_session()["cart_v2"]
        self.assertEqual(self.add_item(branch_id=BRANCH_B, menu_item_id=ITEM_B).status_code, 409)
        self.assertEqual(self.snapshot_session()["cart_v2"], before)

    def test_cart_ignores_client_prices_and_rejects_bad_options_and_quantities(self):
        self.assertEqual(self.add_item(option_ids="egg", price="0.01", unit_price="0.01").status_code, 200)
        line = next(iter(self.snapshot_session()["cart_v2"]["lines"].values()))
        self.assertEqual(line["unit_price"], "55.00")
        self.assertEqual(self.add_item(option_ids="unknown").status_code, 409)
        for quantity in ("-1", "0", "21", "NaN", "1.5"):
            self.assertEqual(self.add_item(quantity=quantity).status_code, 400)
        self.db.rows["menu_items"][0]["options"][0]["price"] = "NaN"
        self.assertEqual(self.add_item(option_ids="egg").status_code, 400)

    def test_cart_mutation_invalidates_old_checkout_key(self):
        self.add_item()
        old_form = self.checkout_form()
        self.add_item()
        self.assertNotEqual(old_form["idempotency_key"], self.snapshot_session()["checkout_key"])
        self.assertEqual(self.client.post("/checkout", data=old_form).status_code, 409)
        self.assertEqual(self.db.rpcs, [])

    def test_checkout_success_and_lost_response_retry_resolve_same_order(self):
        self.add_item(option_ids="egg")
        form = self.checkout_form()
        pending_session = self.snapshot_session()
        first = self.client.post("/checkout", data=form)
        self.assertEqual(first.status_code, 303)
        token = parse_qs(urlsplit(first.location).query)["token"][0]
        self.assertEqual(len(token), 43)
        self.assertEqual(self.db.rpcs[-1][1]["p_items"][0]["expected_unit_price"], "55.00")
        self.assertEqual(self.db.rpcs[-1][1]["p_token_hash"], token_hash(token))
        # Browser replay after a response uses its recorded history, with no mutation.
        replay = self.client.post("/checkout", data=form)
        self.assertEqual(replay.location, first.location)
        self.assertEqual(len(self.db.rpcs), 1)
        # A lost Set-Cookie means the old pending session returns. The DB idempotency
        # key and derived access capability must still be identical.
        with self.client.session_transaction() as session:
            session.clear()
            session.update(pending_session)
        retry = self.client.post("/checkout", data=form)
        self.assertEqual(retry.location, first.location)
        self.assertEqual(len(self.db.created), 1)
        self.assertEqual(self.db.rpcs[0], self.db.rpcs[1])

    def test_status_expiration_refetches_cancelled_order(self):
        self.db.rows["orders"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        response = self.client.get("/api/order_status/1", query_string={"token": TOKEN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "cancelled")
        self.assertEqual(self.db.rpcs, [("expire_unpaid_orders", {"p_branch_id": BRANCH_A})])
        self.assertFalse(response.json["can_cancel"])

    def test_history_revalidates_each_capability_and_skips_missing_orders(self):
        with self.client.session_transaction() as session:
            session["order_history"] = [{"id": 1, "token": WRONG_TOKEN}, {"id": 999, "token": TOKEN},
                                        {"id": 1, "token": TOKEN}]
        with patch("app.routes.user_routes.render_template", return_value="history") as render:
            self.assertEqual(self.client.get("/history").status_code, 200)
            orders = render.call_args.kwargs["orders"]
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]["id"], 1)
            self.assertEqual(orders[0]["token"], TOKEN)

    def test_reorder_prices_current_menu_and_skips_missing_or_changed_options(self):
        self.db.rows["orders"][0]["order_items"] = [
            {"menu_item_id": ITEM_A, "quantity": 2, "unit_price": "1.00", "options": [{"id": "egg", "price": "0.01"}]},
            {"menu_item_id": MISSING_ITEM, "quantity": 1, "options": []},
            {"menu_item_id": ITEM_A, "quantity": 1, "options": [{"id": "removed"}]},
        ]
        self.assertEqual(self.client.post("/order/1/reorder", data={"token": WRONG_TOKEN}).status_code, 404)
        self.assertEqual(self.client.post("/order/1/reorder", data={"token": TOKEN}).status_code, 302)
        lines = list(self.snapshot_session()["cart_v2"]["lines"].values())
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["unit_price"], "55.00")
        self.assertEqual(lines[0]["quantity"], 2)
        self.assertEqual(lines[0]["option_ids"], ["egg"])
        self.assertEqual(self.client.post("/order/1/reorder", data={"token": TOKEN}).status_code, 409)


class AppIntegrationTests(unittest.TestCase):
    def make_app(self, *, rate_limits=False):
        from app import create_app
        self.db = FakeDB()
        return create_app({"SECRET_KEY": "a-long-fixed-secret-for-integration-tests", "TESTING": True,
                           "APP_ENV": "development", "SUPABASE_URL": "https://example.invalid",
                           "SUPABASE_ANON_KEY": "test-anon", "SUPABASE_SERVICE_ROLE_KEY": "test-service",
                           "SUPABASE_CLIENT": self.db, "PUBLIC_BASE_URL": "", "SESSION_COOKIE_SECURE": False,
                           "TRUSTED_PROXY_COUNT": 0, "RATELIMIT_ENABLED": rate_limits,
                           "RATELIMIT_STORAGE_URI": "memory://", "WTF_CSRF_ENABLED": True})

    def test_real_csrf_rejects_write_before_database_and_accepts_session_token(self):
        from flask_wtf.csrf import generate_csrf
        app = self.make_app()
        # Expose CSRF generation only on this isolated test application.
        app.add_url_rule("/test-csrf", view_func=lambda: jsonify(token=generate_csrf()))
        client = app.test_client()
        data = {"branch_id": BRANCH_A, "menu_item_id": ITEM_A, "quantity": "1"}
        missing = client.post("/cart/add", data=data, headers={"Accept": "application/json"})
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(self.db.reads, [])
        token = client.get("/test-csrf").json["token"]
        accepted = client.post("/cart/add", data={**data, "csrf_token": token}, headers={"Accept": "application/json"})
        self.assertEqual(accepted.status_code, 200)
        # A valid token from another browser session grants no authority.
        other_client = app.test_client()
        rejected = other_client.post("/cart/add", data={**data, "csrf_token": token}, headers={"Accept": "application/json"})
        self.assertEqual(rejected.status_code, 400)

    def test_shared_wifi_menu_reads_and_private_response_headers(self):
        app = self.make_app(rate_limits=True)
        client = app.test_client()
        with patch("app.routes.user_routes.render_template", return_value="menu"):
            for _ in range(30):
                response = client.get(f"/b/{BRANCH_A}")
                self.assertEqual(response.status_code, 200)
        status = client.get("/api/order_status/1", query_string={"token": TOKEN})
        self.assertEqual(status.status_code, 200)
        self.assertIn("no-store", status.headers["Cache-Control"])
        self.assertEqual(status.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(status.headers["X-Content-Type-Options"], "nosniff")
        self.assertTrue(status.headers["X-Request-ID"])


if __name__ == "__main__":
    unittest.main()
