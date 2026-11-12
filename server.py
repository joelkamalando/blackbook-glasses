#!/usr/bin/env python3
"""BlackBook Glasses — Canadian Black Book values on Meta Ray-Ban Display.

Same pattern as PulseView: stdlib-only Python, serves a 600x600 glasses
web app at / and JSON endpoints:

  GET /api/value?vin=<17-char VIN>&km=<kilometres>&k=<access key>
  GET /api/value_by_uvc?uvc=<UVC>&km=<kilometres>&k=<access key>
  GET /api/autocomplete?text=<free text>&k=<access key>
  GET /api/drilldown?year=<YYYY>&make=...&model=...&series=...&k=<access key>

Region is always Ontario (Joel's requirement, 2026-11-12).
km defaults to 56000 when omitted (test CLA250's mileage).

Cherry auth: the backend calls Cherry's Canada GraphQL endpoint
(service.blackbookcloud.com/UsedCarWS/CanUsedCherry/GraphQL, see
cherry_api.py / API_DISCOVERY.md) with HTTP Basic auth from the dealer
credentials in env vars — never committed, never logged:
    CHERRY_USERNAME, CHERRY_PASSWORD
In TEST_MODE=1, /api/value serves the verified test VIN fixture only;
the new endpoints return a 503 "live lookup only" error in test mode,
except /api/autocomplete for text matching "cla" (fake CLA candidate)
and /api/value_by_uvc for uvc "TEST" (the fixture), so the By-vehicle
UI flow can be tested end-to-end locally.

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
    # Live path — cherry_api.py (direct Cherry GraphQL).
    try:
        from cherry_api import lookup as cherry_lookup
    except ImportError as e:
        raise RuntimeError(f"live Cherry client not wired yet: {e}")
    return cherry_lookup(vin, km, REGION)


def _fixture_for_test(km, uvc=None):
    data = json.loads(json.dumps(TEST_FIXTURE))
    data["kilometers"] = km
    data["fetched_at"] = datetime.now(TORONTO).isoformat()
    data["source"] = "test-fixture (verified Cherry values, Ontario + 56,000 km)"
    if km != 56000:
        data["source"] += " — km differs from fixture, values are for 56,000 km"
    if uvc is not None:
        data["uvc"] = uvc
    return data


def fetch_value_by_uvc(uvc, km):
    """Return Cherry values for a UVC/km in Ontario. Raises on failure."""
    if TEST_MODE:
        if uvc == "TEST":
            return _fixture_for_test(km, uvc="TEST")
        raise RuntimeError("TEST_MODE is on: live UVC lookup only (uvc TEST returns the fixture).")
    try:
        from cherry_api import lookup_by_uvc
    except ImportError as e:
        raise RuntimeError(f"live Cherry client not wired yet: {e}")
    return lookup_by_uvc(uvc, km, REGION)


def _get_cached(key, fetch_fn):
    with _cache_lock:
        if _cache["data"] and _cache["key"] == key and time.time() - _cache["at"] < 60:
            return _cache["data"]
        data = fetch_fn()
        _cache["data"] = data
        _cache["key"] = key
        _cache["at"] = time.time()
        return data


def get_value_cached(vin, km):
    return _get_cached(f"vin|{vin}|{km}|{REGION}", lambda: fetch_value(vin, km))


def get_value_by_uvc_cached(uvc, km):
    return _get_cached(f"uvc|{uvc}|{km}|{REGION}", lambda: fetch_value_by_uvc(uvc, km))


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

    def _parse_km(self, qs):
        """Parse ?km=, returning (km, error_json_or_None)."""
        try:
            km = int(qs.get("km", [str(DEFAULT_KM)])[0])
        except ValueError:
            return None, {"error": "km must be a number"}
        if km < 0 or km > 999999:
            return None, {"error": "km out of range"}
        return km, None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/api/value", "/api/value_by_uvc", "/api/autocomplete",
                    "/api/drilldown") and self._need_key(parsed):
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
            km, km_err = self._parse_km(qs)
            if km_err:
                self._send_json(km_err, 400)
                return
            try:
                data = get_value_cached(vin, km)
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 502)
                return
            self._send_json(data)
            return
        if path == "/api/value_by_uvc":
            qs = urllib.parse.parse_qs(parsed.query)
            uvc = (qs.get("uvc", [""])[0] or "").strip()
            if not uvc:
                self._send_json({"error": "uvc is required"}, 400)
                return
            km, km_err = self._parse_km(qs)
            if km_err:
                self._send_json(km_err, 400)
                return
            if TEST_MODE and uvc != "TEST":
                self._send_json({"error": "live lookup only — not available in TEST_MODE"}, 503)
                return
            try:
                data = get_value_by_uvc_cached(uvc, km)
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 502)
                return
            self._send_json(data)
            return
        if path == "/api/autocomplete":
            qs = urllib.parse.parse_qs(parsed.query)
            text = (qs.get("text", [""])[0] or "").strip()
            if not text:
                self._send_json({"error": "text is required"}, 400)
                return
            if TEST_MODE:
                # Fixture so the By-vehicle UI flow can be tested locally.
                if "cla" in text.lower():
                    self._send_json({"candidates": [{
                        "uvc": "TEST",
                        "style": "4D Coupe 4MATIC",
                        "description": "2021 Mercedes-Benz CLA250 4D Coupe 4MATIC",
                        "matchcode": "TEST",
                        "enhanced_trim_match": "",
                    }]})
                else:
                    self._send_json({"error": "live lookup only — not available in TEST_MODE"}, 503)
                return
            try:
                from cherry_api import autocomplete as cherry_autocomplete
                self._send_json({"candidates": cherry_autocomplete(text)})
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 502)
            return
        if path == "/api/drilldown":
            qs = urllib.parse.parse_qs(parsed.query)
            year = (qs.get("year", [""])[0] or "").strip()
            if not year or not year.isdigit() or len(year) != 4:
                self._send_json({"error": "year must be a 4-digit year"}, 400)
                return
            if TEST_MODE:
                self._send_json({"error": "live lookup only — not available in TEST_MODE"}, 503)
                return
            try:
                from cherry_api import drilldown as cherry_drilldown
                self._send_json(cherry_drilldown(
                    year=year,
                    make=qs.get("make", [""])[0] or None,
                    model=qs.get("model", [""])[0] or None,
                    series=qs.get("series", [""])[0] or None,
                ))
            except Exception as e:
                self._send_json({"error": str(e)[:300]}, 502)
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
