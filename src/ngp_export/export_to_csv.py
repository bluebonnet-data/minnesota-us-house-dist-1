# export_to_csv.py
#
# Demo (not production): given a list of VAN IDs, pull each contact's notes and
# contributions and write them to two CSVs. Read-only. Same auth as
# test_ngp_connection.py — NGP_APP_NAME and NGP_KEY from the repo-root .env.
#
# Run:  python export_to_csv.py

import csv
import os
import sys

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

BASE_URL = "https://api.securevan.com/v4"
DB_MODE = "1"                       # 1 = My Campaign (where contributions live)
VAN_IDS = [120591234]              # Nancy Ebb; add more IDs here
OUT_DIR = os.path.dirname(__file__)
ENV_PATH = os.path.join(OUT_DIR, "..", "..", ".env")


def build_auth():
    load_dotenv(ENV_PATH)
    app_name, key = os.getenv("NGP_APP_NAME"), os.getenv("NGP_KEY")
    if not app_name or not key:
        sys.exit(f"Missing NGP_APP_NAME / NGP_KEY in {os.path.abspath(ENV_PATH)}")
    return HTTPBasicAuth(app_name, key if "|" in key else f"{key}|{DB_MODE}")


def get_items(auth, path, params=None):
    """GET an endpoint and return its list of records (handles list or {items})."""
    r = requests.get(f"{BASE_URL}{path}", auth=auth, params=params,
                     headers={"Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("items", [])


def write_csv(filename, fields, rows):
    path = os.path.join(OUT_DIR, filename)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {len(rows)} rows -> {filename}")


def main():
    auth = build_auth()
    notes, contributions = [], []

    for van_id in VAN_IDS:
        for n in get_items(auth, f"/people/{van_id}/notes"):
            notes.append({"vanId": van_id, **n})
        for c in get_items(auth, "/contributions/recentContributions",
                           params={"vanId": van_id, "$top": 100}):
            contributions.append(c)

    print(f"Pulled {len(VAN_IDS)} contact(s):")
    write_csv("notes.csv",
              ["vanId", "createdDate", "createdByName", "text"], notes)
    write_csv("contributions.csv",
              ["vanId", "donorName", "amount", "dateReceived",
               "designationName", "type"], contributions)


if __name__ == "__main__":
    main()
