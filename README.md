# BlackBook Glasses

Canadian Black Book values on Meta Ray-Ban Display glasses, powered by Joel's Black Book Cherry dealer subscription.

- Enter a VIN + km, Region is always Ontario (locked).
- Shows Wholesale / Retail / Trade-In AVG (adjusted), Loan Value, plus XCLN/CLN/AVG/RGH breakdown.
- 600×600 glasses UI, same pattern as PulseView. Swipe / D-pad between Lookup, Results, Detail.
- Backend: stdlib-only Python (`server.py`), hosted on Render free tier.
- Access key gates `/` and `/api/value` as `?k=`.

## Test VIN (verified live in Cherry, Ontario + 56,000 km, 2026-11-12)

VIN `W1K5J4HB7MN217673` = 2021 Mercedes-Benz CLA250 4D Coupe 4MATIC
- Wholesale AVG $21,250, Retail AVG $24,100, Trade-In AVG $21,595, Loan $21,150

## Run locally

```bash
cd ~/workspace/blackbook-glasses
BLACKBOOK_TEST_MODE=1 python3 server.py
# open http://127.0.0.1:8766/?vin=W1K5J4HB7MN217673&km=56000
```

Live mode needs `BLACKBOOK_TEST_MODE=0` plus `CHERRY_USERNAME` / `CHERRY_PASSWORD` in env, and `cherry_api.py` filled in from the network inspection. Cherry is single-session: logging in here signs the other device out.
