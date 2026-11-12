#!/usr/bin/env python3
"""BlackBook Glasses — Canadian Black Book values on Meta Ray-Ban Display.

Same pattern as PulseView: stdlib-only Python, serves a 600x600 glasses
web app at / and one JSON endpoint at /api/value.

  GET /api/value?vin=<17-char VIN>&km=<kilometres>&k=<access key>

Region is always Ontario (Joel's requirement, 2026-11-12).
km defaults to 56000 when omitted (test CLA250's mileage).

Cherry auth:
  The backend logs in to Cherry (cherry.blackbookcloud.com) with the
  dealer credentials from env vars — never committed, never logged:
    CHERRY_USERNAME, CHERRY_PASSWORD
  It keeps the session token in memory only. Cherry is single-session:
  logging in here signs the other device out, so the backend logs in
  lazily per lookup and the glasses app caches the last result.

  CHERRY_API_BASE / CHERRY_LOGIN_PATH / CHERRY_VALUE_PATH are filled in
  from the browser network inspection (see cherry_api.py). Until the
  live client is wired, TEST_MODE=1 serves the verified test VIN so
  the UI can be tested end-to-end.

Verified test data (Cherry, Ontario + 56,000 km, 2026-11-12):
  VIN W1K5J4HB7MN217673 = 2021 Mercedes-Benz CLA250 4D Coupe 4MATIC
  Wholesale adjusted AVG $21,250, Retail $24,100, Trade-In $21,595,
  Loan $21,150.
"""

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

PORT = int(os.environ.get("PORT", "8766"))
HOST = os.environ.get("BLACKBOOK_HOST", "127.0.0.1")
ACCESS_KEY = os.environ.get("BLACKBOOK_KEY") or None
TORONTO = ZoneInfo("America/Toronto")
REGION = "Ontario"
DEFAULT_KM = 56000

# Verified test fixture — Ontario + 56,000 km, from live Cherry 2026-11-12.
TEST_VIN = "W1K5J4HB7MN217673"
TEST_FIXTURE = {
    "vin": TEST_VIN,
    "vehicle": "2021 Mercedes-Benz CLA250 4D Coupe 4MATIC",
    "year": 2021, "make": "Mercedes-Benz", "model": "CLA250",
    "trim": "4D Coupe 4MATIC",
    "region": "Ontario", "kilometers": 56000, "options_selected": 0,
    "wholesale": {
        "base": {"XCLN": 24300, "CLN": 22650, "AVG": 20350, "RGH": 18150},
        "adjusted": {"XCLN": 25025, "CLN": 23450, "AVG": 21250, "RGH": 19125},
        "mileage_adj": {"XCLN": 725, "CLN": 800, "AVG": 900, "RGH": 975},
        "region_adj": None, "loan_value": 21150,
    },
    "retail": {
        "base": {"XCLN": 27775, "CLN": 25900, "AVG": 23200, "RGH": 20675},
        "adjusted": {"XCLN": 28500, "CLN": 26700, "AVG": 24100, "RGH": 21650},
        "mileage_adj": {"XCLN": 725, "CLN": 800, "AVG": 900, "RGH": 975},
        "region_adj": None, "loan_value": 21150,
    },
    "trade_in": {
        "base": {"CLN": 22895, "AVG": 20695, "RGH": 17060},
        "adjusted": {"CLN": 23695, "AVG": 21595, "RGH": 18035},
        "mileage_adj": {"CLN": 800, "AVG": 900, "RGH": 975},
        "region_adj": None, "loan_value": 21150,
    },
}

_cache = {"at": 0, "key": None, "data": None}
_cache_lock = threading.Lock()
TEST_MODE = os.environ.get("BLACKBOOK_TEST_MODE", "1") == "1"


def _clean_vin(vin):
    if not vin:
        return None
    vin = re.sub(r"[^A-Za-z0-9]", "", vin).upper()
    return vin if len(vin) == 17 else None


def fetch_value(vin, km):
    """Return Cherry values for vin/km in Ontario. Raises on failure."""
    # Test mode: verified fixture only, so UI/deploy can be proven
    # before the live Cherry client is wired.
    if TEST_MODE:
        if vin == TEST_VIN:
            data = json.loads(json.dumps(TEST_FIXTURE))
            data["kilometers"] = km
            data["fetched_at"] = datetime.now(TORONTO).isoformat()
            data["source"] = "test-fixture (verified Cherry values, Ontario + 56,000 km)"
            # NOTE: fixture numbers are for 56,000 km. If km differs we
            # still return them labelled as the fixture, not a fresh lookup.
            if km != 56000:
                data["source"] += " — km differs from fixture, values are for 56,000 km"
            return data
        raise RuntimeError("TEST_MODE is on: only the verified test VIN is available. Wire the live Cherry client for other VINs.")
    # Live path — implemented in cherry_api.py once endpoints are known.
    try:
        from cherry_api import lookup as cherry_lookup
    except ImportError as e:
        raise RuntimeError(f"live Cherry client not wired yet: {e}")
    return cherry_lookup(vin, km, REGION)


def get_value_cached(vin, km):
    key = f"{vin}|{km}|{REGION}"
    with _cache_lock:
        if _cache["data"] and _cache["key"] == key and time.time() - _cache["at"] < 60:
            return _cache["data"]
        data = fetch_value(vin, km)
        _cache["data"] = data
        _cache["key"] = key
        _cache["at"] = time.time()
        return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{datetime.now().isoformat()}] {self.command} {self.path.split('?')[0]}")

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text, status=200):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _need_key(self, parsed):
        if not ACCESS_KEY:
            return False
        qs = urllib.parse.parse_qs(parsed.query)
        return qs.get("k", [None])[0] != ACCESS_KEY

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/api/value") and self._need_key(parsed):
            self._send_json({"error": "forbidden"}, 403)
            return
        if path == "/":
            try:
                with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.html"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self._send_html("<h1>BlackBook Glasses</h1><p>app.html missing.</p>", 500)
            return
        if path == "/api/value":
            qs = urllib.parse.parse_qs(parsed.query)
            vin = _clean_vin(qs.get("vin", [""])[0])
            if not vin:
                self._send_json({"error": "vin must be a 17-character VIN"}, 400)
                return
            try:
                km = int(qs.get("km", [str(DEFAULT_KM)])[0])
            except ValueError:
                self._send_json({"error": "km must be a number"}, 400)
                return
            if km < 0 or km > 999999:
                self._send_json({"error": "km out of range"}, 400)
                return
            try:
                data = get_value_cached(vin, km)
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 502)
                return
            self._send_json(data)
            return
        if path == "/api/status":
            self._send_json({
                "region": REGION, "default_km": DEFAULT_KM,
                "test_mode": TEST_MODE,
                "test_vin": TEST_VIN,
                "cache_age_seconds": int(time.time() - _cache["at"]) if _cache["data"] else None,
            })
            return
        self._send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    print(f"BlackBook Glasses backend on http://{HOST}:{PORT} (region={REGION}, test_mode={TEST_MODE})", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
