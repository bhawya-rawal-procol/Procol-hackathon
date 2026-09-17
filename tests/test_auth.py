"""Login (mobile + OTP) and vendor isolation.

The product promise is that a vendor sees its own record and nothing else. The guard proves that
for the payloads; these tests prove it for the session — a signed-in vendor cannot reach another
vendor's routes even by typing the id into the URL.
"""
import os
import unittest
from pathlib import Path

from tests.conftest_db import conn, test_db_path, vendor_id
from vi import auth


class Normalisation(unittest.TestCase):
    def test_indian_mobile_formats_collapse(self):
        for raw in ("9810000001", "+91 98100-00001", "098100 00001", "+919810000001"):
            self.assertEqual(auth.normalize_mobile(raw), "9810000001", raw)

    def test_five_accounts_all_map_to_seeded_vendors(self):
        c = conn()
        self.assertEqual(len(auth.ACCOUNTS), 5)
        seen = set()
        for mobile, acct in auth.ACCOUNTS.items():
            v = auth.vendor_id_for(c, acct["archetype"])
            self.assertIsNotNone(v, f"{mobile} has no seeded vendor")
            seen.add(v)
        self.assertEqual(len(seen), 5, "two accounts resolved to the same vendor")

    def test_vendor_logins_file_matches_the_accounts(self):
        """The codes live in VENDOR_LOGINS.md and nowhere a user can see. Keep the two in step."""
        doc = Path(__file__).resolve().parent.parent / "VENDOR_LOGINS.md"
        text = doc.read_text()
        for mobile, acct in auth.ACCOUNTS.items():
            row = next((l for l in text.splitlines() if f"| {mobile} |" in l), None)
            self.assertIsNotNone(row, f"{mobile} is missing from VENDOR_LOGINS.md")
            self.assertIn(f"| {acct['otp']} |", row, f"{mobile} has the wrong OTP in VENDOR_LOGINS.md")
            self.assertIn(acct["archetype"], row)


class ApiCase(unittest.TestCase):
    """Shared fixture: the Flask test client against the seeded test DB."""
    @classmethod
    def setUpClass(cls):
        os.environ["VI_DB"] = test_db_path()
        from vi import api as api_mod
        api_mod.DB_PATH = test_db_path()
        cls.api = api_mod
        cls.c = conn()

    def setUp(self):
        self.client = self.api.app.test_client()
        auth._PENDING.clear()

    def post(self, path, body):
        r = self.client.post(path, json=body)
        return r.status_code, r.get_json()

    def login(self, mobile, otp=None):
        self.post("/api/auth/request_otp", {"mobile": mobile})
        code = otp or auth.ACCOUNTS[auth.normalize_mobile(mobile)]["otp"]
        return self.post("/api/auth/verify_otp", {"mobile": mobile, "otp": code})


class OtpFlow(ApiCase):

    def test_request_otp_never_returns_the_code(self):
        status, body = self.post("/api/auth/request_otp", {"mobile": "9810000001"})
        self.assertEqual(status, 200)
        self.assertNotIn(auth.ACCOUNTS["9810000001"]["otp"], str(body))

    def test_no_endpoint_lists_the_accounts(self):
        self.assertEqual(self.client.get("/api/auth/accounts").status_code, 404)

    def test_happy_path_signs_in_as_that_vendor(self):
        status, body = self.login("9810000001")
        self.assertEqual(status, 200)
        self.assertEqual(body["vendor_id"], vendor_id(self.c, "V-STAR"))
        me = self.client.get("/api/session").get_json()
        self.assertEqual(me["vendor"]["archetype"], "V-STAR")

    def test_unregistered_number_is_rejected(self):
        status, body = self.post("/api/auth/request_otp", {"mobile": "9999999999"})
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    def test_wrong_otp_is_rejected_and_attempts_run_out(self):
        self.post("/api/auth/request_otp", {"mobile": "9810000002"})
        for _ in range(auth.MAX_ATTEMPTS):
            status, body = self.post("/api/auth/verify_otp", {"mobile": "9810000002", "otp": "000000"})
            self.assertEqual(status, 401)
        status, body = self.post("/api/auth/verify_otp", {"mobile": "9810000002", "otp": "222222"})
        self.assertEqual(status, 401)                       # correct code, but the request is burned
        self.assertIn("Request a new OTP", body["error"])
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_otp_cannot_be_verified_without_being_requested(self):
        status, body = self.post("/api/auth/verify_otp", {"mobile": "9810000003", "otp": "333333"})
        self.assertEqual(status, 401)
        self.assertIn("Request an OTP", body["error"])

    def test_expired_otp_is_rejected(self):
        self.post("/api/auth/request_otp", {"mobile": "9810000004"})
        auth._PENDING["9810000004"]["issued_at"] -= auth.OTP_TTL_SECONDS + 1
        status, body = self.post("/api/auth/verify_otp", {"mobile": "9810000004", "otp": "444444"})
        self.assertEqual(status, 401)
        self.assertIn("expired", body["error"])


class Isolation(ApiCase):
    """The ones that matter: one session, one vendor, nothing else reachable."""

    def vendor_paths(self, v):
        return [f"/api/vendor/{v}/habits", f"/api/vendor/{v}/events", f"/api/vendor/{v}/profile",
                f"/api/vendor/{v}/priceband", f"/api/vendor/{v}/chat/greeting"]

    def test_anonymous_gets_nothing(self):
        for p in self.vendor_paths(vendor_id(self.c, "V-STAR")) + ["/api/meta", "/api/session", "/api/audit"]:
            self.assertEqual(self.client.get(p).status_code, 401, p)
        self.assertEqual(self.client.get("/").status_code, 302)     # → /login
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_signed_in_vendor_cannot_read_another_vendors_routes(self):
        self.login("9810000001")                                   # V-STAR
        other = vendor_id(self.c, "V-LATE")
        for p in self.vendor_paths(other):
            r = self.client.get(p)
            self.assertEqual(r.status_code, 403, p)
            self.assertNotIn("Rathi", r.get_data(as_text=True))

    def test_cross_vendor_post_is_refused_too(self):
        self.login("9810000001")
        other = vendor_id(self.c, "V-HIGH")
        r = self.client.post(f"/api/vendor/{other}/chat", json={"message": "how am I doing?"})
        self.assertEqual(r.status_code, 403)

    def test_cross_vendor_attempt_is_audited(self):
        self.login("9810000001")
        mine = vendor_id(self.c, "V-STAR")
        self.client.get(f"/api/vendor/{vendor_id(self.c, 'V-LATE')}/habits")
        row = self.c.execute("""SELECT actor_id, inputs_json FROM audit_log WHERE action='cross_vendor_denied'
                                ORDER BY id DESC LIMIT 1""").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], mine)

    def test_meta_only_ever_returns_the_signed_in_vendor(self):
        self.login("9810000003")                                   # V-HIGH
        meta = self.client.get("/api/meta").get_json()
        self.assertEqual(len(meta["vendors"]), 1)
        self.assertEqual(meta["vendors"][0]["archetype"], "V-HIGH")

    def test_audit_tail_is_scoped_to_the_signed_in_vendor(self):
        self.login("9810000005")                                   # V-SLIPPING
        mine = vendor_id(self.c, "V-SLIPPING")
        self.client.get(f"/api/vendor/{mine}/priceband")
        for row in self.client.get("/api/audit").get_json():
            self.assertEqual(row["actor_id"], mine)

    def test_logout_ends_the_session(self):
        self.login("9810000001")
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_each_account_sees_its_own_record(self):
        for mobile, acct in auth.ACCOUNTS.items():
            client = self.api.app.test_client()
            self.client = client
            auth._PENDING.clear()
            self.login(mobile)
            me = client.get("/api/session").get_json()
            self.assertEqual(me["vendor"]["archetype"], acct["archetype"])
            events = client.get(f"/api/vendor/{me['vendor']['id']}/events").get_json()
            self.assertGreater(len(events), 0, f"{acct['name']} has no events")


if __name__ == "__main__":
    unittest.main()
