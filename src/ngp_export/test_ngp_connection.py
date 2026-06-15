# test_ngp_connection.py
#
# Read-only check of what our NGP VAN API key can actually do. Pulls a known
# test contact's record, notes, and contributions, then probes the bulk
# endpoints we'd want for a weekly donation export.
#
# Auth is HTTP Basic: username = application name, password = the API key GUID
# plus "|1" for the My Campaign database (where contributions live). Both the
# app name (NGP_APP_NAME) and the key GUID (NGP_KEY) are secret and live in the
# repo-root .env.
#
# Results:
#   - People, Notes, and per-person Contributions all work.
#   - There's no campaign-wide "contributions since date X" we can reach:
#       * changedEntityExportJobs (the bulk export we'd want) is forbidden
#       * financialBatches returns batch headers only, not the contributions
#       * GET /contributions isn't a listable endpoint
#
# Run:  python test_ngp_connection.py

import os
import sys

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

BASE_URL = "https://api.securevan.com/v4"
DB_MODE = "1"                   # 0 = My Voters, 1 = My Campaign
TEST_VAN_ID = 120591234         # Nancy Ebb — has donated; safe to read

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", ".env")


def build_auth():
    """Basic auth from NGP_APP_NAME + NGP_KEY in .env (GUID gets '|1' appended)."""
    load_dotenv(ENV_PATH)
    app_name = os.getenv("NGP_APP_NAME")
    key = os.getenv("NGP_KEY")
    missing = [n for n, v in [("NGP_APP_NAME", app_name), ("NGP_KEY", key)] if not v]
    if missing:
        sys.exit(f"Missing {', '.join(missing)} in {os.path.abspath(ENV_PATH)}")
    password = key if "|" in key else f"{key}|{DB_MODE}"
    return HTTPBasicAuth(app_name, password)


def get(auth, path, params=None):
    """GET an endpoint; return (status_code, parsed_json_or_None)."""
    r = requests.get(f"{BASE_URL}{path}", auth=auth, params=params,
                     headers={"Accept": "application/json"}, timeout=30)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def main():
    auth = build_auth()
    print("NGP VAN check — My Campaign db")
    print(f"Test contact: Nancy Ebb (VAN ID {TEST_VAN_ID})")

    # Person
    status, person = get(auth, f"/people/{TEST_VAN_ID}")
    print(f"\nPerson  [{status}]")
    if person:
        print(f"  {person.get('firstName', '')} {person.get('lastName', '')} "
              f"(vanId {person.get('vanId')})")

    # Notes
    status, notes = get(auth, f"/people/{TEST_VAN_ID}/notes")
    items = (notes if isinstance(notes, list) else (notes or {}).get("items", [])) or []
    print(f"\nNotes  [{status}] — {len(items)} found")
    for n in items:
        print(f"  {n.get('createdDate', '')}: {n.get('text', '')}")

    # Contributions (per-person only)
    status, contribs = get(auth, "/contributions/recentContributions",
                           params={"vanId": TEST_VAN_ID, "$top": 6})
    items = (contribs or {}).get("items", [])
    print(f"\nContributions  [{status}] — {(contribs or {}).get('count', len(items))} total")
    for c in items:
        print(f"  ${c.get('amount')}  {c.get('dateReceived')}  "
              f"{c.get('designationName')}  [{c.get('type')}]")

    # Can we bulk-pull contributions by date? Not with this key — see header.
    print("\nWeekly-export probe (what we'd need for all donations since a date):")
    probes = [
        ("changedEntityExportJobs", "/changedEntityExportJobs/resources",
         "the bulk export we want — restricted on this key"),
        ("financialBatches", "/financialBatches",
         "batch headers only, no contributions inside"),
    ]
    for label, path, note in probes:
        status, _ = get(auth, path)
        print(f"  {label:24} [{status}] — {note}")
    print("  No campaign-wide 'contributions since date' yet. Next step: get the")
    print("  Changed Entity Export permission added to this API key.")


if __name__ == "__main__":
    main()
