"""Vendor login — mobile number + OTP, hardcoded for five demo vendors.

Procol vendors sign in with their registered mobile and a one-time code. This prototype keeps the
same shape but skips the SMS gateway: the five accounts below carry a fixed OTP, and an OTP must
still be *requested* before it can be verified, so the flow a real gateway would drive is intact.
The numbers and codes are written down in VENDOR_LOGINS.md; nothing in the UI or the API reveals them.

Isolation is the point. A session carries exactly one vendor_company_id; `vi/api.py` refuses any
vendor route whose id is not the session's, so one vendor can never read another's record even by
editing the URL. The ConfidentialityGuard stays where it was — this is the layer in front of it.
"""
from __future__ import annotations

import re
import sqlite3
import time

from .db import one

OTP_TTL_SECONDS = 5 * 60
MAX_ATTEMPTS = 5

# Mobile → the vendor it signs in as. `archetype` is resolved to companies.id at login, so these
# survive a reseed (ids are not stable across `make seed`, archetypes are).
ACCOUNTS: dict[str, dict] = {
    "9810000001": {"archetype": "V-STAR", "name": "Shakti Enterprises", "otp": "111111",
                   "contact": "Priya Shah"},
    "9810000002": {"archetype": "V-LATE", "name": "Rathi Metallurgicals Pvt Ltd", "otp": "222222",
                   "contact": "Anil Rathi"},
    "9810000003": {"archetype": "V-HIGH", "name": "Omkar Industrial Supplies", "otp": "333333",
                   "contact": "Omkar Deshpande"},
    "9810000004": {"archetype": "V-TECHWEAK", "name": "Kaveri Chem & Spares", "otp": "444444",
                   "contact": "Lakshmi Iyer"},
    "9810000005": {"archetype": "V-SLIPPING", "name": "Meridian Freight & Pack", "otp": "555555",
                   "contact": "Farhan Qureshi"},
}

# mobile -> {"issued_at": float, "attempts": int}. Process memory only; a restart invalidates
# outstanding codes, which is the behaviour you want from a real OTP store anyway.
_PENDING: dict[str, dict] = {}


def normalize_mobile(raw: str | None) -> str:
    """`+91 98100-00001`, `098100 00001` and `9810000001` are the same number."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def account(mobile: str | None) -> dict | None:
    acct = ACCOUNTS.get(normalize_mobile(mobile))
    return {**acct, "mobile": normalize_mobile(mobile)} if acct else None


def vendor_id_for(conn: sqlite3.Connection, archetype: str) -> int | None:
    row = one(conn, "SELECT id FROM companies WHERE category='vendor' AND archetype=?", (archetype,))
    return row["id"] if row else None


def request_otp(mobile: str | None) -> dict:
    """Issue a code for a registered mobile. Unregistered numbers are told so — this is a demo
    console with five accounts, not a public sign-up, so enumeration is not a concern here."""
    acct = account(mobile)
    if not acct:
        return {"ok": False, "error": "That mobile number is not registered as a vendor on Procol."}
    _PENDING[acct["mobile"]] = {"issued_at": time.time(), "attempts": 0}
    return {
        "ok": True,
        "mobile": acct["mobile"],
        "vendor_name": acct["name"],
        "contact": acct["contact"],
        "expires_in": OTP_TTL_SECONDS,
        "message": f"OTP sent to the mobile registered to {acct['name']}.",
    }


def verify_otp(conn: sqlite3.Connection, mobile: str | None, otp: str | None) -> dict:
    acct = account(mobile)
    if not acct:
        return {"ok": False, "error": "That mobile number is not registered as a vendor on Procol."}

    pending = _PENDING.get(acct["mobile"])
    if not pending:
        return {"ok": False, "error": "Request an OTP first."}
    if time.time() - pending["issued_at"] > OTP_TTL_SECONDS:
        _PENDING.pop(acct["mobile"], None)
        return {"ok": False, "error": "That OTP has expired. Request a new one."}
    if pending["attempts"] >= MAX_ATTEMPTS:
        _PENDING.pop(acct["mobile"], None)
        return {"ok": False, "error": "Too many attempts. Request a new OTP."}

    if re.sub(r"\D", "", str(otp or "")) != acct["otp"]:
        pending["attempts"] += 1
        left = MAX_ATTEMPTS - pending["attempts"]
        return {"ok": False, "error": f"Incorrect OTP. {left} attempt{'s' if left != 1 else ''} left."}

    vendor = vendor_id_for(conn, acct["archetype"])
    if vendor is None:
        return {"ok": False, "error": f"No seeded vendor for {acct['archetype']} — run `./run.sh seed` first."}

    _PENDING.pop(acct["mobile"], None)
    return {"ok": True, "vendor_id": vendor, "mobile": acct["mobile"],
            "vendor_name": acct["name"], "contact": acct["contact"], "archetype": acct["archetype"]}

