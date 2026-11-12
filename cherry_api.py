"""Live Cherry client — filled in from browser network inspection.

The browser task inspecting cherry.blackbookcloud.com reports the
login + VIN-lookup endpoints here. Until then, server.py runs in
TEST_MODE=1 and serves only the verified test VIN.

Expected shape (to confirm):
  POST <base>/login  {username, password} -> session token / cookie
  GET/POST <base>/vehicle?vin=...&kilometers=...&region=Ontario
    -> vehicle + wholesale / retail / trade-in tables

Never log credentials or tokens. Never commit this file with secrets.
"""

def lookup(vin, km, region):
    raise RuntimeError(
        "live Cherry client not wired yet — browser network inspection "
        "is still in progress. Set BLACKBOOK_TEST_MODE=1 for the verified "
        "test VIN, or fill in the endpoints found in the inspection."
    )
