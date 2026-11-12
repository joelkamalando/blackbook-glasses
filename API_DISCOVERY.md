# Cherry direct API — discovery notes (2026-11-12)

Found by reading Cherry's own JavaScript bundle, not DevTools:
`https://cherry.blackbookcloud.com/main.167d26d445b21651.js`
(The cloud browser could not open DevTools/Network or view-source, but
`browser.open` on the bundle URL returns the full minified source.)

## Environment config (bundle line 1381)

- `API_URL: "https://cherry-api-prod.blackbookcloud.com"` — auth / users API
- Canada product (`PRODUCT_BBD_CANADA`):
  - Retail GraphQL: `https://service.blackbookcloud.com/RetailAPI/CanUsedCherry/GraphQL`
  - HAV / UsedCarWS GraphQL: `https://service.blackbookcloud.com/UsedCarWS/CanUsedCherry/GraphQL`
- US product (`PRODUCT_BBD`) uses `/RetailAPI/BBD/GraphQL` and
  `/UsedCarWS/BBD/GraphQL` instead. Country is set to `"C"` for Canada.

## Auth — HTTP Basic, not a token

The app's `api-service.request()` (bundle ~L1967-1971) builds, for every
call:

```
Authorization: Basic base64(username + ":" + password)
Content-Type: application/json   (POST only)
```

Username/password are the Cherry login credentials themselves, stored in
localStorage as `cherry-username` and AES-encrypted `cherry-password`.
An HTTP interceptor also adds, for some URLs, headers:
- `state-token`: a GUID persisted in localStorage (`state-token`)
- `DeviceType: desktop` (or `mobile` in the native app)

A 401 response makes the app clear the saved username/password and
reload to the login page (bundle ~L1976-1980).

No bearer token is needed for the GraphQL calls themselves. The
"Invalid authorization token" / single-session transfer prompt seen in
the web UI comes from the cherry-api-prod auth flow, not from GraphQL
Basic auth — whether GraphQL enforces the single session is untested.

## VIN lookup — GraphQL (Canada provider, bundle ~L2590-2608)

```
POST https://service.blackbookcloud.com/UsedCarWS/CanUsedCherry/GraphQL
Authorization: Basic base64(user:pass)
Content-Type: application/json
Body: {"query": "query{ usedvehicles(vin: \"<VIN>\", mileage: <km>, province: \"<PROV>\", evm_flag:BOTH){ usedvehicles{ ...fields... } } }"}
```

Arguments built by `getQueryJson()`: `uvc`, `vin`, `mileage`,
`province` (= stateProvinceCode, e.g. Ontario = `ON` — verify via the
provinces query below), `adddeductcodes` (comma-joined option codes),
plus literal `evm_flag:BOTH`. Only non-null args are included.

Response shape: `{ "data": { "usedvehicles": { "usedvehicles": [ {...} ], "message_list": [...] } } }`
(the outer `usedvehicles` is the query root; the inner list holds the
vehicles; `hydrateVehicleInfo` takes `usedvehicles[0]`).

Fields requested (when `getHav` is falsy — the normal path):
- identity: `publish_date, vin, uvc, model_year, make, model, series,
  style, city_mpg, hwy_mpg, model_number_list, groupnum, fuel_type`
- per condition (xclean/clean/avg/rough) × per type (whole/retail/tradein):
  `base_*`, `add_deduct_*`, `mileage_*`, `regional_*`,
  `adjusted_*`, `history_*`
  e.g. `base_whole_avg, adjusted_whole_avg, mileage_whole_avg,
  regional_whole_avg, history_whole_avg`, and the same for retail and
  tradein. Note tradein has no xclean fields.
- `adjusted_finadv` (loan value)
- `add_deduct_list{ uoc name xclean clean avg rough auto resid12
  resid24 resid30 resid36 resid42 resid48 resid60 resid72 }`

The app's mapping (bundle ~L2355-2359): for Wholesale/Retail/TradeIn,
conditions XCLN/CLN/AVG/RGH map to fields
`adjusted_<whole|retail|tradein>_<xclean|clean|avg|rough>`, with
`base_`, `mileage_`, `regional_`, `history_`, `add_deduct_` siblings.
Header "AVG WHOLESALE" = `adjusted_whole_avg`.

## Provinces query (verify the Ontario code)

```
POST <same HAV GraphQL URL>
{"query": "query{provinces{abbreviation name}}"}
```

US provider uses `query{states{abbreviation name car_region truck_region}}`.

## Other endpoints in the bundle

- Retail listings GraphQL: same RetailAPI URL, `listings(uvc, zipcode, ...)`
- Autocomplete: `query{autocomplete(searchtext:"..." maxresults:25 useevm:true){matching_vehicles{uvc style description matchcode enhanced_trim_match}}}` — implemented in `cherry_api.autocomplete()`, exposed as `GET /api/autocomplete`.
- UVC lookup: same `usedvehicles` query as VIN but with `uvc: "…"` in
  place of `vin:` — implemented in `cherry_api.lookup_by_uvc()`,
  exposed as `GET /api/value_by_uvc`.
- Drilldown: `query{drilldown(year:"..." make:"..." model:"..." series:"..."){class_list{...}}}` — stepwise: year → `year_list{make_list{name}}`, +make → `model_list{name}`, +model → `series_list{name}`, +series → `style_list{name uvc}`. Implemented in `cherry_api.drilldown()`, exposed as `GET /api/drilldown`. The no-year form needs a `vehicleclass` whose value is unknown, so the UI always starts from a typed/spoken year.
- PDF: `query{ pdf (uvc:"...") { file_contents, error_count } }`

## Implications for the glasses backend

Direct GraphQL is strictly better than browser automation:
- stdlib Python `urllib` POST, no Chrome, no Browserless, runs on
  Render free tier.
- No DOM fragility; the query/fields are pinned in this doc.
- Credentials: `CHERRY_USERNAME` / `CHERRY_PASSWORD` env vars on
  Render only, never committed, never shown in chat. The user enters
  them in the Render dashboard (Muse cannot pull the saved Secure
  Vault password back out).
- Still to verify live: (1) province code for Ontario is `ON`,
  (2) GraphQL Basic auth accepts the dealer login, (3) values for
  W1K5J4HB7MN217673 at Ontario + 56,000 km match the verified
  $21,250 / $24,100 / $21,595 / $21,150, (4) whether a GraphQL call
  disturbs the phone's Cherry session.
