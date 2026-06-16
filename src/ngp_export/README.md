# NGP VAN API Export

Scripts that pull data **out of** NGP VAN via its REST API, so we can sync it to
other organizing apps. This is the reverse direction of
`Cleaning_CallTime_for_NGP_upload/` (which prepares data to upload *into* NGP).

The first goal is a recurring export of donations (updated every Monday) and
contact notes.

## Authentication

NGP VAN uses HTTP Basic Auth:

| Field | Value |
|---|---|
| username | **Application Name** — `NGP_APP_NAME` |
| password | **API key** in the form `<GUID>\|<mode>` — GUID is `NGP_KEY` |

Both `NGP_APP_NAME` and `NGP_KEY` are secret and live in the repo-root `.env`
(gitignored). Keep them out of code and commits. The mode is appended in code:
`0` = My Voters, `1` = My Campaign. We use **mode 1 (My Campaign)** because
donations and contributions live there.

Base URL: `https://api.securevan.com/v4`

## Scripts

### `test_ngp_connection.py`

A read-only smoke test. Confirms the API key can read People, Notes, and
Contributions for a single contact (Nancy Ebb, VAN ID 120591234). Run this
first whenever credentials change.

```
python test_ngp_connection.py
```

As of 2026-06-14, reads for People, Notes, and per-person Contributions all
return 200. The script also probes the bulk export routes (see below).

## Endpoints in use

| Data | Method & path |
|---|---|
| Person by ID | `GET /people/{vanId}` |
| Notes | `GET /people/{vanId}/notes` |
| Contributions (per person) | `GET /contributions/recentContributions?vanId={vanId}` |

Docs: https://docs.ngpvan.com/reference/overview

## Open issue: no campaign-wide donations-by-date

The weekly export needs "all contributions since last Monday," but nothing the
key can currently reach does that:

- `changedEntityExportJobs` — the bulk export built for exactly this — returns
  **403 Forbidden**. The key doesn't have the Changed Entity Export permission.
- `financialBatches` returns batch headers only; there's no way to read the
  contributions inside a batch.
- There's no listable `GET /contributions` endpoint.
- `recentContributions` works but is per-`vanId`, so it can't find *new* donors
  we don't already have IDs for.

**Next step:** get the Changed Entity Export permission added to this API key
(via the committee's NGP admin / NGP support). Once it's granted, the Monday job
is: POST a `changedEntityExportJobs` for Contributions with a date range, poll
until done, download the CSV.

## Requirements

- Python
- Packages: `requests`, `python-dotenv` (both already installed)
