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


def _gql_escape(s):
    """Escape a value for embedding in a GraphQL string literal."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _query(vin, km, province):
    args = f'vin: "{_gql_escape(vin)}", mileage: {km}, province: "{_gql_escape(province)}", evm_flag:BOTH'
    return f"query{{ usedvehicles({args}){{ usedvehicles{{ {_fields()} }} }} }}"


def _query_by_uvc(uvc, km, province):
    args = f'uvc: "{_gql_escape(uvc)}", mileage: {km}, province: "{_gql_escape(province)}", evm_flag:BOTH'
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


def _check_errors(data):
    if data.get("errors"):
        msgs = "; ".join(str(e.get("message", e)) for e in data["errors"])
        raise RuntimeError(f"Cherry GraphQL error: {msgs[:300]}")


def _vehicles_from(data, what):
    vehicles = ((data.get("data") or {}).get("usedvehicles") or {}).get("usedvehicles") or []
    if not vehicles:
        raise RuntimeError(f"no vehicle found in Cherry for {what}")
    return vehicles[0]


def _parse_vehicle(v, km, region, vin=None):
    """Shared usedvehicles[0] → result shape (same as server.py fixture)."""
    vehicle_name = " ".join(
        str(v.get(k, "")).strip()
        for k in ("model_year", "make", "model", "series", "style")
        if v.get(k)
    ).strip()
    result = {
        # For VIN lookups the caller passes the requested full VIN: the
        # GraphQL `vin` field echoes a truncated (first 9 chars) value.
        # For UVC lookups there is no requested VIN, so the echoed value
        # (possibly truncated) is all we have — the UI keys those by UVC.
        "vin": vin if vin is not None else (v.get("vin") or ""),
        "uvc": v.get("uvc") or "",
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


def lookup(vin, km, region):
    province = os.environ.get("CHERRY_PROVINCE", "ON")
    data = _post(_query(vin, km, province))
    _check_errors(data)
    return _parse_vehicle(_vehicles_from(data, f"VIN {vin}"), km, region, vin=vin)


def lookup_by_uvc(uvc, km, region):
    """Same values as lookup(), but by UVC (from autocomplete/drilldown)."""
    province = os.environ.get("CHERRY_PROVINCE", "ON")
    data = _post(_query_by_uvc(uvc, km, province))
    _check_errors(data)
    return _parse_vehicle(_vehicles_from(data, f"UVC {uvc}"), km, region)


def autocomplete(text):
    """Cherry autocomplete: free text → candidate vehicles with UVCs.

    Query shape from the app's own JS bundle (Canada provider):
    query{autocomplete(searchtext:"..." maxresults:25 useevm:true)
      {matching_vehicles{uvc style description matchcode
      enhanced_trim_match}}}
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("autocomplete needs search text")
    query = (
        f'query{{autocomplete(searchtext:"{_gql_escape(text)}" '
        f"maxresults:25 useevm:true){{matching_vehicles{{uvc style "
        f"description matchcode enhanced_trim_match}}}}}}"
    )
    data = _post(query)
    _check_errors(data)
    vehicles = ((data.get("data") or {}).get("autocomplete") or {}).get("matching_vehicles") or []
    return [
        {
            "uvc": str(v.get("uvc") or ""),
            "style": v.get("style") or "",
            "description": v.get("description") or "",
            "matchcode": v.get("matchcode") or "",
            "enhanced_trim_match": v.get("enhanced_trim_match") or "",
        }
        for v in vehicles
    ]


def drilldown(year=None, make=None, model=None, series=None):
    """Stepwise year → make → model → series → style (with UVC) drilldown.

    Query shapes from the app's own JS bundle. The bundle's no-year
    form needs a vehicleclass whose value is unknown, so a year is
    required here — the UI asks for it (typed or spoken) first.
    Returns {"level": <next level>, "items": [{"name": ...,
    "uvc": ... (style level only)}]}.
    """
    year = (str(year) if year else "").strip()
    if not year or not year.isdigit() or len(year) != 4:
        raise RuntimeError("drilldown needs a 4-digit year")
    make = (make or "").strip()
    model = (model or "").strip()
    series = (series or "").strip()
    if series:
        if not model or not make:
            raise RuntimeError("drilldown series needs make and model")
        args = (f'year: "{_gql_escape(year)}", make: "{_gql_escape(make)}", '
                f'model: "{_gql_escape(model)}", series: "{_gql_escape(series)}"')
        inner = "class_list{year_list{make_list{model_list{series_list{style_list{name uvc}}}}}}"
        level, path = "style", ("class_list", "year_list", "make_list", "model_list", "series_list", "style_list")
    elif model:
        if not make:
            raise RuntimeError("drilldown model needs a make")
        args = (f'year: "{_gql_escape(year)}", make: "{_gql_escape(make)}", '
                f'model: "{_gql_escape(model)}"')
        inner = "class_list{year_list{make_list{model_list{series_list{name}}}}}"
        level, path = "series", ("class_list", "year_list", "make_list", "model_list", "series_list")
    elif make:
        args = f'year: "{_gql_escape(year)}", make: "{_gql_escape(make)}"'
        inner = "class_list{year_list{make_list{model_list{name}}}}"
        level, path = "model", ("class_list", "year_list", "make_list", "model_list")
    else:
        args = f'year: "{_gql_escape(year)}"'
        inner = "class_list{year_list{make_list{name}}}"
        level, path = "make", ("class_list", "year_list", "make_list")
    query = f"query{{drilldown({args}){{{inner}}}}}"
    data = _post(query)
    _check_errors(data)
    # Walk down to the parent of the wanted list, taking [0] of each
    # intermediate list (class_list/year_list/make_list/... are 1-elem
    # here), then read the final list whole.
    node = (data.get("data") or {}).get("drilldown") or {}
    for key in path[:-1]:
        if isinstance(node, dict):
            node = node.get(key)
        if isinstance(node, list):
            node = node[0] if node else None
        if node is None:
            break
    items = []
    if isinstance(node, dict):
        items = node.get(path[-1]) or []
    if not isinstance(items, list):
        items = []
    return {
        "level": level,
        "items": [
            {"name": it.get("name") or "", "uvc": str(it.get("uvc") or "")}
            for it in items
            if isinstance(it, dict) and it.get("name")
        ],
    }


def provinces():
    """List provinces (abbreviation + name) — verifies the Ontario code."""
    data = _post('query{provinces{abbreviation name}}')
    return (data.get("data") or {}).get("provinces") or []
