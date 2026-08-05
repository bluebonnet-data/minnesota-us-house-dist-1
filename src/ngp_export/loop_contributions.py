# loop_contributions.py
#
# Stopgap workaround: until our key gets the bulk Changed
# Entity Export permission, we can't ask NGP "all donations since date X". So
# instead we loop over a bounded list of VAN IDs and check each one's recent
# contributions individually.
#
# Population: the "NGP ID" column from the CallTime list exports in data/. These
# are people we're already calling, so they're a small, likely-to-have-donated
# set — good for testing the approach without hammering the whole database.
# We probably will want to change this to a more comprehensive list of VAN IDs 
# once we have access to ActBlue or another data source.
#
# Reads: data/list-*.csv   ->   Writes: data/contributions_found.csv
# Auth is the same as the other scripts (NGP_APP_NAME + NGP_KEY from .env).
#
# Run:  python loop_contributions.py

import csv
import glob
import os
import sys
import time

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

BASE_URL = "https://api.securevan.com/v4"
DB_MODE = "1"                    # 1 = My Campaign
SINCE = "2026-04-01"            # only keep contributions received on/after this
PAUSE = 0.35                    # seconds between calls (~3/sec, polite pacing)

HERE = os.path.dirname(__file__)
DATA_DIR = os.path.join(HERE, "..", "..", "data")
ENV_PATH = os.path.join(HERE, "..", "..", ".env")


def build_auth():
    load_dotenv(ENV_PATH)
    app_name, key = os.getenv("NGP_APP_NAME"), os.getenv("NGP_KEY")
    if not app_name or not key:
        sys.exit(f"Missing NGP_APP_NAME / NGP_KEY in {os.path.abspath(ENV_PATH)}")
    return HTTPBasicAuth(app_name, key if "|" in key else f"{key}|{DB_MODE}")


def read_van_ids():
    """Unique numeric VAN IDs from the 'NGP ID' column of every data/list-*.csv."""
    ids = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "list-*.csv"))):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                van = (row.get("NGP ID") or "").strip()
                if van.isdigit():
                    ids.append(van)
    return sorted(set(ids), key=int)


def get_json(auth, url, params=None):
    """GET with a simple 429 back-off. Returns parsed JSON."""
    for attempt in range(4):
        r = requests.get(url, auth=auth, params=params,
                         headers={"Accept": "application/json"}, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 5))
            print(f"    429 rate-limited, waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    sys.exit("Giving up after repeated 429s")


def recent_contributions(auth, van_id):
    """All recent contributions for one contact, following pagination."""
    url = f"{BASE_URL}/contributions/recentContributions"
    params = {"vanId": van_id, "$top": 100}
    while url:
        data = get_json(auth, url, params)
        for item in data.get("items", []):
            yield item
        url = data.get("nextPageLink")   # full URL, already has its own params
        params = None
        if url:
            time.sleep(PAUSE)


def main():
    auth = build_auth()
    van_ids = read_van_ids()
    print(f"Checking {len(van_ids)} contacts for contributions since {SINCE}...")

    found = []
    donors = 0
    for i, van_id in enumerate(van_ids, 1):
        gifts = [c for c in recent_contributions(auth, van_id)
                 if (c.get("dateReceived") or "") >= SINCE]
        if gifts:
            donors += 1
            found.extend(gifts)
        if i % 25 == 0:
            print(f"  {i}/{len(van_ids)} checked, {donors} donors so far")
        time.sleep(PAUSE)

    out = os.path.join(DATA_DIR, "contributions_found.csv")
    fields = ["vanId", "donorName", "amount", "dateReceived", "designationName", "type"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(found)

    total = sum(c.get("amount") or 0 for c in found)
    print(f"\nDone. {donors} of {len(van_ids)} contacts gave since {SINCE}; "
          f"{len(found)} contributions totaling ${total:,.2f}")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
