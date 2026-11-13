# BlackBook Glasses

Canadian Black Book values on Meta Ray-Ban Display glasses, powered by Joel's Black Book Cherry dealer subscription.

- Enter a VIN + km, Region is always Ontario (locked).
- Shows Wholesale / Retail / Trade-In AVG (adjusted), Loan Value, plus XCLN/CLN/AVG/RGH breakdown.
- 600×600 glasses UI, same pattern as PulseView. Swipe / D-pad between Lookup, Results, Detail, and By vehicle.
- Backend: stdlib-only Python (`server.py`), hosted on Render free tier.
- Access key gates `/` and the `/api/*` endpoints as `?k=`.

## Ways to look a car up

1. **By VIN** — type, speak, or photograph it (see below).
2. **By vehicle** — "By vehicle" screen: type or speak a year + vehicle
   (e.g. "2021 Mercedes CLA250") to search, or step through
   Year → Make → Model → Series → Style pickers, then enter km.

## Voice

- 🎤 mic button next to the VIN field and on the By-vehicle search box.
  Uses the browser's SpeechRecognition (Chrome/Android). A spoken VIN is
  **never auto-submitted**: it is shown as "Heard: … — tap Get values
  to confirm" so mishears (B/D, 0/O, 5/S) can be corrected. A spoken
  year + vehicle jumps to the By-vehicle screen and runs the search.
- 🔊 "Read aloud" on the Results screen speaks the vehicle name and
  the Wholesale / Retail / Trade-in / loan values (numbers as words,
  e.g. 21250 → "twenty-one thousand two hundred fifty"). "Auto-read"
  toggles reading automatically after each lookup (saved on device).
  Speaking stops when you leave the Results screen.
- **Caveat — untested on the glasses:** SpeechRecognition and
  speechSynthesis work in a phone/desktop browser, but whether the
  Meta AI app's webview on the Ray-Ban Display grants microphone
  access / supports them has not been tested on the glasses yet.

## VIN photo scan (OCR)

- 📷 "Scan VIN" on the Lookup screen opens the camera/file picker
  (`<input type="file" accept="image/*" capture="environment">`).
- The photo is read in the browser with Tesseract.js (loaded lazily
  from CDN only when Scan is first tapped — no backend change, no API
  key). It extracts a 17-character VIN candidate (VINs never contain
  I, O, or Q), validates it with the ISO 3779 check digit when
  possible, and shows it as "Photo read: … — tap Get values to
  confirm" — never auto-submitted. If no VIN is found it shows the raw
  text read and asks for a retake. If the CDN cannot be reached it
  fails with a clear error instead of hanging.
- **Caveat — untested on the glasses:** whether the Meta AI webview
  grants camera access is unknown; on a phone browser the capture
  input opens the camera directly.

## API endpoints

- `GET /api/value?vin=…&km=…` — values by VIN.
- `GET /api/value_by_uvc?uvc=…&km=…` — values by UVC (from
  autocomplete / drilldown).
- `GET /api/autocomplete?text=…` — Cherry autocomplete candidates
  (`{candidates: [{uvc, style, description, matchcode}]}`).
- `GET /api/drilldown?year=…&make=…&model=…&series=…` — stepwise
  drilldown; returns `{level, items: [{name, uvc}]}` for the next
  level (make → model → series → style). A 4-digit year is required.

In TEST_MODE=1, `/api/value` keeps serving the verified CLA fixture;
the new endpoints return 503 "live lookup only", except
`/api/autocomplete` with text matching "cla" (one fake CLA candidate,
UVC "TEST") and `/api/value_by_uvc` with uvc "TEST" (the fixture), so
the By-vehicle flow can be tested end-to-end locally.

## Tap fix (2026-11-12, on-glasses report)

Joel reported on the glasses that typing the VIN worked but buttons
(Get values, Scan, By vehicle, picklist items) did not respond. Cause:
the deck's swipe handler treated any touch/mouse gesture starting on
a button as a page swipe, so an imprecise temple-touchpad tap flipped
the page (or was swallowed) instead of clicking; and the By-vehicle
screen was ~940 px tall in a 600 px viewport, so km / Get values sat
below the fold. Fix (app.html only): swipes are ignored when the
gesture starts on a button/input/picklist or inside the scrollable
By-vehicle screen (background swipes still navigate); only the visible
screen receives taps (`pointer-events`); picklist items are real
`<button>`s; the By-vehicle screen auto-scrolls Get values into view
after a selection; a typed 4-digit year now starts the drilldown
without waiting for blur; Enter on the VIN field runs the lookup.
Verified with touch taps in headless Chromium (precise tap, drift tap,
background swipe, full By-vehicle flow).

## Test VIN (verified live in Cherry, Ontario + 56,000 km, 2026-11-12)

VIN `W1K5J4HB7MN217673` = 2021 Mercedes-Benz CLA250 4D Coupe 4MATIC
- Wholesale AVG $21,250, Retail AVG $24,100, Trade-In AVG $21,595, Loan $21,150

## Run locally

```bash
cd ~/workspace/blackbook-glasses
BLACKBOOK_TEST_MODE=1 python3 server.py
# open http://127.0.0.1:8766/?vin=W1K5J4HB7MN217673&km=56000
```

Live mode needs `BLACKBOOK_TEST_MODE=0` plus `CHERRY_USERNAME` / `CHERRY_PASSWORD` in env. Cherry is single-session: logging in here signs the other device out.
