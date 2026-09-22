"""Order-service properties: capabilities, operating hours, ETA and safe errors."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask

from app.services.errors import UserError, database_error
from app.services.orders import (branch_accepting, estimate_wait, get_order, money,
                                 requested_slots, stable_access_token, token_hash)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "a-stable-long-secret-for-unit-tests"
        self.branch = {"timezone": "Asia/Bangkok", "is_active": True, "is_accepting_orders": True,
                       "opening_time": "08:00:00", "closing_time": "20:00:00", "prep_minutes": 10,
                       "kitchen_capacity": 2, "slot_minutes": 15, "slot_capacity": 10, "preorder_days": 0}

    def test_order_capability_is_stable_but_changes_for_key_and_secret(self):
        key = "00000000-0000-0000-0000-000000000001"
        with self.app.app_context():
            first = stable_access_token(key)
            self.assertEqual(first, stable_access_token(key))
            self.assertNotEqual(first, stable_access_token("00000000-0000-0000-0000-000000000002"))
            self.app.secret_key = "different-secret-for-new-installation"
            self.assertNotEqual(first, stable_access_token(key))
        self.assertRegex(first, r"^[A-Za-z0-9_-]{43}$")
        self.assertRegex(token_hash(first), r"^[a-f0-9]{64}$")
        self.assertNotEqual(first, token_hash(first))

    def test_missing_or_short_order_token_never_queries_database(self):
        with patch("app.services.orders.get_supabase") as database:
            for token in (None, "", "guess", "A" * 39, "A" * 101, "/" * 43):
                with self.subTest(token=token), self.assertRaises(UserError) as error:
                    get_order(1, token)
                self.assertEqual(error.exception.status, 404)
            database.assert_not_called()

    def test_lookup_requires_order_id_and_hashed_capability(self):
        db = MagicMock()
        query = db.table.return_value
        query.select.return_value = query
        query.eq.return_value = query
        query.limit.return_value = query
        query.execute.return_value = SimpleNamespace(data=[])
        token = "A" * 43
        with patch("app.services.orders.get_supabase", return_value=db), self.assertRaises(UserError):
            get_order(23, token)
        self.assertIn((("id", 23),), query.eq.call_args_list)
        self.assertIn((("token_hash", token_hash(token)),), query.eq.call_args_list)

    def test_prices_reject_nonfinite_negative_and_overflow_values(self):
        for value in ("NaN", "Infinity", "-Infinity", "-0.01", "1000000", "bad", None):
            with self.subTest(value=value), self.assertRaises(UserError):
                money(value)
        self.assertEqual(money("40.25"), Decimal("40.25"))

    def test_branch_hours_use_local_timezone_and_support_overnight(self):
        # 01:00 UTC is 08:00 Bangkok; closing boundary is exclusive.
        self.assertTrue(branch_accepting(self.branch, datetime(2026, 9, 21, 1, tzinfo=timezone.utc)))
        self.assertFalse(branch_accepting(self.branch, datetime(2026, 9, 21, 13, tzinfo=timezone.utc)))
        overnight = dict(self.branch, opening_time="20:00", closing_time="02:00")
        self.assertTrue(branch_accepting(overnight, datetime(2026, 9, 21, 18, tzinfo=timezone.utc)))
        self.assertFalse(branch_accepting(overnight, datetime(2026, 9, 21, 8, tzinfo=timezone.utc)))
        self.assertFalse(branch_accepting(dict(self.branch, is_accepting_orders=False)))
        self.assertFalse(branch_accepting(dict(self.branch, is_active=False)))

    def test_first_waiting_order_never_claims_zero_minutes(self):
        eta = estimate_wait(self.branch, ahead=0, order={"status": "waiting"})
        self.assertGreater(eta["min"], 0)
        self.assertGreaterEqual(eta["max"], eta["min"])
        later = estimate_wait(self.branch, ahead=4, order={"status": "waiting"})
        self.assertGreater(later["max"], eta["max"])
        faster = estimate_wait(dict(self.branch, kitchen_capacity=4), ahead=4)
        self.assertLess(faster["max"], later["max"])

    def test_terminal_orders_have_zero_eta_and_overdue_work_stays_positive(self):
        now = datetime(2026, 9, 21, 1, tzinfo=timezone.utc)
        for status in ("ready", "completed", "cancelled"):
            self.assertEqual(estimate_wait(self.branch, order={"status": status}, now=now), {"min": 0, "max": 0})
        eta = estimate_wait(self.branch, order={"status": "preparing", "started_at": (now - timedelta(hours=1)).isoformat()}, now=now)
        self.assertGreater(eta["min"], 0)

    def test_preorders_zero_days_allows_today_and_respects_prep_lead_time(self):
        now = datetime(2026, 9, 21, 1, 2, tzinfo=timezone.utc)  # 08:02 Bangkok
        slots = requested_slots(self.branch, now=now)
        self.assertTrue(slots, "preorder_days=0 means today-only; slot_capacity=0 disables preorders")
        dates = [datetime.fromisoformat(slot["value"]) for slot in slots]
        self.assertTrue(all(value.date().isoformat() == "2026-09-21" for value in dates))
        self.assertTrue(all(value >= now + timedelta(minutes=10) for value in dates))
        self.assertTrue(all(value.minute % 15 == 0 and value.second == 0 for value in dates))
        self.assertEqual(requested_slots(dict(self.branch, slot_capacity=0), now=now), [])

    def test_domain_errors_are_translated_without_database_details(self):
        for message in ("price_changed", "pickup_slot_full", "promptpay_unavailable", "branch_unavailable"):
            with self.subTest(message=message):
                result = database_error(SimpleNamespace(message=message))
                self.assertIsInstance(result, UserError)
                self.assertNotIn(message, result.message)
        self.assertIsNone(database_error(SimpleNamespace(message="password=secret server=private-db unexpected error")))


if __name__ == "__main__":
    unittest.main()
