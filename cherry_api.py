"""Live Cherry client — direct GraphQL, no browser needed.

Discovered 2026-11-12 by reading Cherry's own JS bundle
(main.167d26d445b21651.js, see API_DISCOVERY.md). The app calls:

  POST https://service.blackbookcloud.com/UsedCarWS/CanUsedCherry/GraphQL
  Authorization: Basic base64(username + ":" + password)
  Content-Type: application/json
  Body: {"query": "query{ usedvehicles(vin: ..., mileage: ..., province: \"ON\", evm_flag:BOTH){ usedvehicles{ ... } } }"}

Credentials come only from env vars CHERRY_USERNAME / CHERRY_PASSWORD
(never committed, never logged, never printed). Province defaults to
"ON" for Ontario (override with CHERRY_PROVINCE if the provinces
query ever shows a different code).

Returns the same shape as the test fixture in server.py:
wholesale / retail / trade_in each with base / adjusted / mileage_adj /
region_adj (+ loan_value), plus vehicle identity.
"""

import base64
import json
import os
import urllib.error
import urllib.request
import uuid

HAV_URL = "https://service.blackbookcloud.com/UsedCarWS/CanUsedCherry/GraphQL"

_CONDITIONS = (("xclean", "XCLN"), ("clean", "CLN"), ("avg", "AVG"), ("rough", "RGH"))
_TYPES = (("whole", "wholesale"), ("retail", "retail"), ("tradein", "trade_in"))


def _fields():
    """GraphQL field list, copied from the app's own query + parser."""
    f = [
        "publish_date", "vin", "uvc", "model_year", "make", "model",
        "series", "style", "city_mpg", "hwy_mpg", "model_number_list",
        "groupnum", "fuel_type", "state",
    ]
    for t, _ in _TYPES:
        conds = ("xclean", "clean", "avg", "rough") if t != "tradein" else ("clean", "avg", "rough")
        for c in conds:
            for prefix in ("base", "add_deduct", "mileage", "regional", "history", "adjusted"):
                f.append(f"{prefix}_{t}_{c}")
    f += ["adjusted_finadv", "enhanced_trim_match"]
    f.append("add_deduct_list{ uoc name xclean clean avg rough auto "
             "resid12 resid24 resid30 resid36 resid42 resid48 resid60 resid72 }")
    return ", ".join(f)


def _query(vin, km, province):
    args = f'vin: "{vin}", mileage: {km}, province: "{province}", evm_flag:BOTH'
    return f"query{{ usedvehicles({args}){{ usedvehicles{{ {_fields()} }} }} }}"


def _post(query):
    username = os.environ.get("CHERRY_USERNAME")
    password = os.environ.get("CHERRY_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "live Cherry lookup needs CHERRY_USERNAME and CHERRY_PASSWORD "
            "set as environment variables (enter them in the Render "
            "dashboard — never in chat or in code)."
        )
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request(HAV_URL, data=body, method="POST")
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/json")
    # The app's HTTP interceptor also sends these on API calls.
    req.add_header("state-token", str(uuid.uuid4()))
    req.add_header("DeviceType", "desktop")
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise RuntimeError(
                "Cherry rejected the login (401) — check the Cherry "
                "username/password in the Render dashboard."
            )
        raise RuntimeError(f"Cherry GraphQL returned HTTP {e.code}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"could not reach Cherry GraphQL: {e.reason}")


def _num(v):
    return None if v is None else int(v)


def _section(vehicle, t):
    """Build one wholesale/retail/trade_in section from GraphQL fields."""
    conds = ("xclean", "clean", "avg", "rough") if t != "tradein" else ("clean", "avg", "rough")
    out = {"base": {}, "adjusted": {}, "mileage_adj": {}, "region_adj": {}}
    for c, label in _CONDITIONS:
        if c not in conds:
            continue
        out["base"][label] = _num(vehicle.get(f"base_{t}_{c}"))
        out["adjusted"][label] = _num(vehicle.get(f"adjusted_{t}_{c}"))
        out["mileage_adj"][label] = _num(vehicle.get(f"mileage_{t}_{c}"))
        out["region_adj"][label] = _num(vehicle.get(f"regional_{t}_{c}"))
    # Drop region_adj if every entry is null (Ontario shows N/A).
    if all(v is None for v in out["region_adj"].values()):
        out["region_adj"] = None
    out["loan_value"] = _num(vehicle.get("adjusted_finadv"))
    return out


def lookup(vin, km, region):
    province = os.environ.get("CHERRY_PROVINCE", "ON")
    data = _post(_query(vin, km, province))
    if data.get("errors"):
        msgs = "; ".join(str(e.get("message", e)) for e in data["errors"])
        raise RuntimeError(f"Cherry GraphQL error: {msgs[:300]}")
    vehicles = ((data.get("data") or {}).get("usedvehicles") or {}).get("usedvehicles") or []
    if not vehicles:
        raise RuntimeError(f"no vehicle found in Cherry for VIN {vin}")
    v = vehicles[0]
    vehicle_name = " ".join(
        str(v.get(k, "")).strip()
        for k in ("model_year", "make", "model", "series", "style")
        if v.get(k)
    ).strip()
    result = {
        # Use the requested full VIN: the GraphQL `vin` field echoes a
        # truncated (first 9 chars) value, which broke the glasses app's
        # VIN display and recent-lookup keys.
        "vin": vin,
        "vehicle": vehicle_name,
        "year": _num(v.get("model_year")),
        "make": v.get("make"),
        "model": v.get("model"),
        "trim": " ".join(str(v.get(k, "")).strip() for k in ("series", "style") if v.get(k)),
        "region": region,
        "kilometers": km,
        "options_selected": 0,
        "source": "live Cherry GraphQL (UsedCarWS CanUsedCherry)",
    }
    for t, key in _TYPES:
        result[key] = _section(v, t)
    return result


def provinces():
    """List provinces (abbreviation + name) — verifies the Ontario code."""
    data = _post('query{provinces{abbreviation name}}')
    return (data.get("data") or {}).get("provinces") or []
