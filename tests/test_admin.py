"""Authorization and money boundaries exercised without live Supabase access."""
import copy
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from uuid import UUID, uuid4

from flask import Flask

from app.routes.admin_routes import admin_bp
from app.services.auth import safe_next_url
from scripts.create_admin import validate_scope
from scripts.create_branch import create_branch


ORG_A = "00000000-0000-0000-0000-000000000001"
ORG_B = "00000000-0000-0000-0000-000000000002"
BRANCH_A = "00000000-0000-0000-0000-000000000011"
BRANCH_B = "00000000-0000-0000-0000-000000000012"
STAFF_ID = "00000000-0000-0000-0000-000000000021"
ITEM_ID = "00000000-0000-0000-0000-000000000031"


class Query:
    def __init__(self, db, table):
        self.db, self.name, self.filters = db, table, []
        self.operation, self.payload, self.maximum = "select", None, None

    def select(self, *args, **kwargs):
        return self

    def eq(self, name, value):
        self.filters.append(lambda row: row.get(name) == value)
        return self

    def in_(self, name, values):
        self.filters.append(lambda row: row.get(name) in values)
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, maximum):
        self.maximum = maximum
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.operation, self.payload = "update", payload
        return self

    def execute(self):
        self.db.calls.append((self.name, self.operation, self.payload))
        rows = [row for row in self.db.rows.get(self.name, []) if all(test(row) for test in self.filters)]
        if self.operation == "insert":
            row = dict(self.payload)
            row.setdefault("id", str(uuid4()))
            rows = [row]
            self.db.rows.setdefault(self.name, []).extend(rows)
        elif self.operation == "update":
            for row in rows:
                row.update(self.payload)
        if self.maximum is not None:
            rows = rows[:self.maximum]
        return SimpleNamespace(data=copy.deepcopy(rows), count=len(rows))


class FakeDB:
    def __init__(self):
        self.calls, self.rpcs, self.signed = [], [], []
        self.rows = {
            "organizations": [{"id": ORG_A}, {"id": ORG_B}],
            "branches": [{"id": BRANCH_A, "organization_id": ORG_A, "name": "A", "is_active": True,
                          "is_accepting_orders": True, "timezone": "Asia/Bangkok"},
                         {"id": BRANCH_B, "organization_id": ORG_B, "name": "B", "is_active": True}],
            "staff": [{"id": STAFF_ID, "auth_user_id": "00000000-0000-0000-0000-000000000099",
                       "role": "branch_admin", "is_active": True, "username": "test@example.com",
                       "organization_id": ORG_A, "branch_id": BRANCH_A}],
            "orders": [{"id": 1, "branch_id": BRANCH_A, "status": "waiting", "payment_status": "pending"},
                       {"id": 2, "branch_id": BRANCH_B, "status": "waiting", "payment_status": "pending"}],
            "menu_items": [{"id": ITEM_ID, "branch_id": BRANCH_A, "name": "Rice", "price": 40,
                            "is_available": True, "options": []}],
            "audit_log": [],
        }
        self.storage = self
        self.auth = SimpleNamespace(admin=SimpleNamespace(
            create_user=lambda payload: SimpleNamespace(user=SimpleNamespace(id="00000000-0000-0000-0000-000000000088")),
            update_user_by_id=lambda uid, payload: None,
        ))

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params):
        self.rpcs.append((name, params))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data={"id": 9, "order_code": "Q009"}))

    def from_(self, bucket):
        self.bucket = bucket
        return self

    def create_signed_url(self, path, ttl):
        self.signed.append((self.bucket, path, ttl))
        return {"signedURL": "https://storage.example.test/signed"}


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret-key-is-long-enough"
        self.app.testing = True
        self.app.register_blueprint(admin_bp)
        self.app.add_url_rule("/payment/<int:order_id>", endpoint="user.payment_page", view_func=lambda order_id: "payment")
        self.db = FakeDB()
        self.patches = [patch("app.services.auth.get_supabase", return_value=self.db),
                        patch("app.routes.admin_routes.get_supabase", return_value=self.db),
                        patch("app.routes.admin_routes.render_template", return_value="rendered")]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["staff_id"] = STAFF_ID
            session["staff_auth_until"] = 9999999999.0
            # Deliberately stale/higher role must never grant permission.
            session["staff_role"] = "super_admin"


    def role(self, role):
        self.db.rows["staff"][0]["role"] = role

    def test_session_role_is_not_authority(self):
        self.role("staff")
        self.assertEqual(self.client.get("/admin/menu").status_code, 403)
        self.assertEqual(self.client.post(f"/admin/branches/{BRANCH_A}/settings", data={}).status_code, 403)
        self.assertFalse(any(name == "menu_items" for name, _, _ in self.db.calls))

    def test_revocation_takes_effect_next_request(self):
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.db.rows["staff"][0]["is_active"] = False
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.location)
        with self.client.session_transaction() as session:
            self.assertNotIn("staff_id", session)

    def test_missing_branch_fails_closed(self):
        self.role("staff")
        self.db.rows["staff"][0]["branch_id"] = None
        response = self.client.post("/admin/order/2/start")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.rpcs, [])
        self.assertFalse(any(name == "orders" for name, _, _ in self.db.calls))

    def test_mismatched_staff_organization_fails_closed(self):
        self.db.rows["staff"][0]["organization_id"] = ORG_B
        self.assertIn("/admin/login", self.client.get("/admin/").location)

    def test_org_admin_only_own_organization(self):
        self.role("org_admin")
        self.assertEqual(self.client.post("/admin/order/2/start").status_code, 404)
        self.assertEqual(self.db.rpcs, [])
        with patch("app.routes.admin_routes.render_template", return_value="ok") as render:
            self.assertEqual(self.client.get("/admin/").status_code, 200)
            self.assertEqual([b["id"] for b in render.call_args.kwargs["branches"]], [BRANCH_A])

    def test_super_admin_can_cross_organization(self):
        self.role("super_admin")
        self.assertEqual(self.client.post("/admin/order/2/start").status_code, 302)
        self.assertEqual(self.db.rpcs[-1][1]["p_order_id"], 2)

    def test_order_actions_use_atomic_rpc(self):
        self.role("staff")
        self.assertEqual(self.client.post("/admin/order/1/payment/cash", data={"reference": "cashbox"}).status_code, 302)
        self.assertEqual(self.db.rpcs, [("order_action", {"p_order_id": 1, "p_staff_id": STAFF_ID,
                         "p_action": "cash", "p_reason": "", "p_reference": "cashbox", "p_expected_slip_path": None})])
        self.assertFalse(any(name == "orders" and op == "update" for name, op, _ in self.db.calls))

    def test_cancellation_requires_reason(self):
        self.assertEqual(self.client.post("/admin/order/1/cancel").status_code, 302)
        self.assertEqual(self.db.rpcs, [])

    def test_cross_branch_menu_update_denied(self):
        self.db.rows["menu_items"][0]["branch_id"] = BRANCH_B
        self.assertEqual(self.client.post(f"/admin/menu/{ITEM_ID}/toggle").status_code, 404)
        self.assertTrue(self.db.rows["menu_items"][0]["is_available"])

    def test_menu_rejects_invalid_money(self):
        for price in ("NaN", "Infinity", "-1", "12.345", "1000000", "not money"):
            with self.subTest(price=price):
                self.client.post("/admin/menu/add", data={"branch_id": BRANCH_A, "name": "Rice", "price": price})
        self.assertFalse(any(name == "menu_items" and op == "insert" for name, op, _ in self.db.calls))

    def test_menu_rejects_duplicate_options_and_unsafe_image(self):
        payloads = [{"options": '[{"id":"egg","name":"Egg"},{"id":"egg","name":"More"}]'},
                    {"image_url": "javascript:alert(1)"}]
        for extra in payloads:
            self.client.post("/admin/menu/add", data={"branch_id": BRANCH_A, "name": "Rice", "price": "40", **extra})
        self.assertFalse(any(name == "menu_items" and op == "insert" for name, op, _ in self.db.calls))

    def test_menu_audit_uses_actual_target_branch(self):
        self.role("super_admin")
        self.client.post("/admin/menu/add", data={"branch_id": BRANCH_B, "name": "Rice", "price": "40.25"})
        log = self.db.rows["audit_log"][-1]
        self.assertEqual(log["branch_id"], BRANCH_B)
        self.assertEqual(self.db.rows["menu_items"][-1]["price"], 40.25)

    def test_legacy_slip_url_is_never_redirected(self):
        self.db.rows["orders"][0]["slip_url"] = "https://legacy.example.test/public.png"
        self.assertEqual(self.client.get("/admin/order/1/slip").status_code, 404)
        self.assertEqual(self.db.signed, [])

    def test_private_slip_signed_only_after_scope_check(self):
        path = "orders/1/random.jpg"
        self.db.rows["orders"][0]["slip_path"] = path
        response = self.client.get("/admin/order/1/slip")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.signed, [("slips", path, 60)])
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.db.rows["orders"][1]["slip_path"] = "orders/2/random.jpg"
        self.assertEqual(self.client.get("/admin/order/2/slip").status_code, 404)
        self.assertEqual(len(self.db.signed), 1)

    def test_safe_next_redirect(self):
        with self.app.test_request_context():
            for unsafe in ("https://evil.test", "//evil.test/path", "/\\evil.test", "/\n/evil.test", "relative"):
                self.assertEqual(safe_next_url(unsafe), "/admin/")
            self.assertEqual(safe_next_url("/admin/menu?branch_id=abc"), "/admin/menu?branch_id=abc")

    def test_branch_settings_invalid_payment_and_timezone(self):
        for extra in ({"promptpay_id": "123", "promptpay_name": "Name"}, {"timezone": "invalid-zone"},
                      {"opening_time": "12:00"}, {"slot_capacity": "-1"}, {"slot_minutes": "7"}):
            response = self.client.post(f"/admin/branches/{BRANCH_A}/settings", data={"name": "A", **extra})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(any(name == "branches" and op == "update" for name, op, _ in self.db.calls))

    def test_branch_settings_audit_and_normalization(self):
        self.role("super_admin")
        response = self.client.post(f"/admin/branches/{BRANCH_B}/settings", data={"name": "New B",
            "promptpay_id": "081-234-5678", "promptpay_name": "Owner", "is_accepting_orders": "on",
            "opening_time": "08:00", "closing_time": "20:00", "preorder_days": "0"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.db.rows["branches"][1]["promptpay_id"], "0812345678")
        log = self.db.rows["audit_log"][-1]
        self.assertEqual(log["branch_id"], BRANCH_B)
        self.assertIn("promptpay_id", log["details"]["changed_fields"])
        self.assertNotIn("0812345678", str(log))

    def test_bootstrap_scope_validation_precedes_auth(self):
        with self.assertRaises(ValueError):
            validate_scope(self.db, "staff")
        with self.assertRaises(ValueError):
            validate_scope(self.db, "org_admin")
        with self.assertRaises(ValueError):
            validate_scope(self.db, "branch_admin", BRANCH_A, ORG_B)
        self.assertEqual(validate_scope(self.db, "staff", BRANCH_A), (BRANCH_A, ORG_A))

    def test_walkin_replay_keeps_capability_and_server_price(self):
        self.role("staff")
        with self.client.session_transaction() as session:
            session["walk_in_attempts"] = {
                "00000000-0000-0000-0000-000000000041": {
                    "branch_id": BRANCH_A, "staff_id": STAFF_ID, "expires_at": 9999999999.0,
                    "prices": {ITEM_ID: {"base": "40.00", "options": {}}},
                }
            }
        payload = {"idempotency_key": "00000000-0000-0000-0000-000000000041",
                   f"qty_{ITEM_ID}": "2", "payment_method": "cash", "price": "0.01", "total_price": "0.01"}
        first = self.client.post(f"/admin/kitchen/{BRANCH_A}/walk-in", data=payload)
        self.assertEqual(first.status_code, 302)
        self.db.rows["menu_items"][0]["is_available"] = False
        second = self.client.post(f"/admin/kitchen/{BRANCH_A}/walk-in", data=payload)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(self.db.rpcs[0], self.db.rpcs[1])
        args = self.db.rpcs[0][1]
        self.assertEqual(args["p_staff_id"], STAFF_ID)
        self.assertEqual(args["p_items"], [{"menu_item_id": ITEM_ID, "quantity": 2, "option_ids": [], "note": "", "expected_unit_price": "40.00"}])
        self.assertEqual(len(args["p_token_hash"]), 64)
        self.assertNotIn("p_price", args)

    def test_walkin_quantity_over_database_limit_rejected(self):
        with self.client.session_transaction() as session:
            session["walk_in_attempts"] = {
                "00000000-0000-0000-0000-000000000041": {
                    "branch_id": BRANCH_A, "staff_id": STAFF_ID, "expires_at": 9999999999.0,
                    "prices": {ITEM_ID: {"base": "40.00", "options": {}}},
                }
            }
        response = self.client.post(f"/admin/kitchen/{BRANCH_A}/walk-in", data={
            "idempotency_key": "00000000-0000-0000-0000-000000000041", f"qty_{ITEM_ID}": "21"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.rpcs, [])

    def test_promptpay_walkin_provides_usable_payment_link_on_replay(self):
        from app.services.orders import token_hash
        self.role("staff")
        with self.client.session_transaction() as session:
            session["walk_in_attempts"] = {
                "00000000-0000-0000-0000-000000000041": {
                    "branch_id": BRANCH_A, "staff_id": STAFF_ID, "expires_at": 9999999999.0,
                    "prices": {ITEM_ID: {"base": "40.00", "options": {}}},
                }
            }
        payload = {"idempotency_key": "00000000-0000-0000-0000-000000000041",
                   f"qty_{ITEM_ID}": "1", "payment_method": "promptpay"}
        first = self.client.post(f"/admin/kitchen/{BRANCH_A}/walk-in", data=payload)
        self.assertEqual(first.status_code, 303)
        location = urlsplit(first.location)
        self.assertEqual(location.path, "/payment/9")
        token = parse_qs(location.query)["token"][0]
        self.assertEqual(token_hash(token), self.db.rpcs[-1][1]["p_token_hash"])
        replay = self.client.post(f"/admin/kitchen/{BRANCH_A}/walk-in", data=payload)
        self.assertEqual(replay.location, first.location)

    def test_dashboard_scopes_date_in_sql_and_denies_foreign_branch(self):
        self.role("org_admin")
        with patch("app.routes.admin_routes.render_template", return_value="ok") as render:
            response = self.client.get(f"/admin/dashboard?branch_id={BRANCH_A}&date=2026-09-21")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.db.rpcs[-1], ("branch_dashboard", {"p_branch_id": BRANCH_A,
                             "p_staff_id": STAFF_ID, "p_date": "2026-09-21"}))
            self.assertEqual(render.call_args.kwargs["selected_date"], "2026-09-21")
        before = len(self.db.rpcs)
        self.assertEqual(self.client.get(f"/admin/dashboard?branch_id={BRANCH_B}").status_code, 404)
        self.assertEqual(len(self.db.rpcs), before)

    def test_new_shop_starts_paused_and_requires_real_organization(self):
        with self.assertRaises(ValueError):
            create_branch(self.db, organization_id=STAFF_ID, name="Missing org")
        branch = create_branch(self.db, organization_id=ORG_A, name=" New shop ")
        self.assertFalse(branch["is_accepting_orders"])
        self.assertEqual(branch["name"], "New shop")

    def test_super_admin_endpoints_permission_denied_for_staff(self):
        self.role("staff")
        self.assertEqual(self.client.get("/admin/super").status_code, 403)
        self.assertEqual(self.client.get("/admin/super/branches").status_code, 403)
        self.assertEqual(self.client.get("/admin/super/organizations").status_code, 403)
        self.assertEqual(self.client.get("/admin/super/staff").status_code, 403)

    def test_super_admin_endpoints_permission_denied_for_org_admin(self):
        self.role("org_admin")
        self.assertEqual(self.client.get("/admin/super").status_code, 403)
        self.assertEqual(self.client.get("/admin/super/branches").status_code, 403)

    def test_super_admin_can_access_dashboard_and_manage_resources(self):
        self.role("super_admin")
        self.assertEqual(self.client.get("/admin/super").status_code, 200)
        self.assertEqual(self.client.get("/admin/super/branches").status_code, 200)
        self.assertEqual(self.client.get("/admin/super/organizations").status_code, 200)
        self.assertEqual(self.client.get("/admin/super/staff").status_code, 200)

    def test_super_admin_create_branch_and_toggle(self):
        self.role("super_admin")
        response = self.client.post("/admin/super/branches/create", data={
            "organization_id": ORG_A, "name": "Super New Branch",
            "campus": "Test Campus", "pickup_point": "Counter 1", "timezone": "Asia/Bangkok",
        })
        self.assertEqual(response.status_code, 302)
        created = [b for b in self.db.rows["branches"] if b.get("name") == "Super New Branch"]
        self.assertTrue(len(created) > 0)
        new_id = created[0]["id"]

        # Toggle orders
        toggle_res = self.client.post(f"/admin/super/branches/{new_id}/toggle-orders")
        self.assertEqual(toggle_res.status_code, 302)
        self.assertTrue(created[0]["is_accepting_orders"])

        # Toggle active
        active_res = self.client.post(f"/admin/super/branches/{new_id}/toggle-active")
        self.assertEqual(active_res.status_code, 302)
        self.assertFalse(created[0]["is_active"])

    def test_super_admin_create_organization(self):
        self.role("super_admin")
        response = self.client.post("/admin/super/organizations/create", data={"name": "New Network Org"})
        self.assertEqual(response.status_code, 302)
        created = [o for o in self.db.rows["organizations"] if o.get("name") == "New Network Org"]
        self.assertTrue(len(created) > 0)

    def test_super_admin_create_and_manage_staff(self):
        self.role("super_admin")
        response = self.client.post("/admin/super/staff/create", data={
            "email": "newbie@example.com", "password": "password123456",
            "role": "staff", "organization_id": ORG_A, "branch_id": BRANCH_A,
        })
        self.assertEqual(response.status_code, 302)
        created = [s for s in self.db.rows["staff"] if s.get("username") == "newbie@example.com"]
        self.assertTrue(len(created) > 0)
        staff_id = created[0]["id"]

        # Reset password
        reset_res = self.client.post(f"/admin/super/staff/{staff_id}/reset-password", data={"new_password": "newpassword123"})
        self.assertEqual(reset_res.status_code, 302)

        # Toggle active
        toggle_res = self.client.post(f"/admin/super/staff/{staff_id}/toggle-active")
        self.assertEqual(toggle_res.status_code, 302)
        self.assertFalse(created[0]["is_active"])


if __name__ == "__main__":

    unittest.main()
