"""Step 3: write one Notion review-queue row per classified report, or fill in the Cluster column.

Usage:
  python write_notion.py                      # create/update rows from results.json
  python write_notion.py --clusters           # write cluster names from clusters.json into Cluster
  python write_notion.py --verify             # count R### rows currently in the database

The token is read from NOTION_TOKEN (environment or git-ignored .env). It is never written to disk.
"""
import argparse
import json
import os
import sys
import time

import requests

from common import ROOT, load_env

DATABASE_ID = "44ee3dfd094d83cfa59a81f1aea58f35"
API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def rich(value):
    """rich_text property; Notion caps each text object at 2000 chars, so long values are chunked."""
    value = value or ""
    if not value:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": value[i:i + 2000]}} for i in range(0, len(value), 2000)]}


def notion_headers():
    token = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY")
    if not token:
        sys.exit("NOTION_TOKEN is not set. Export it in your shell or put it in the git-ignored .env file.")
    return {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}


def notion(method, path, headers, body=None):
    for attempt in range(5):
        resp = requests.request(method, API + path, headers=headers, json=body, timeout=30)
        if resp.status_code == 429 or resp.status_code >= 500:
            time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
            continue
        if not resp.ok:
            raise RuntimeError(f"Notion {method} {path} -> {resp.status_code}: {resp.text}")
        return resp.json()
    raise RuntimeError(f"Notion {method} {path} kept failing after retries")


def find_pages(headers, report_id):
    body = {"filter": {"property": "Report ID", "title": {"equals": report_id}}}
    return [page["id"] for page in notion("POST", f"/databases/{DATABASE_ID}/query", headers, body)["results"]]


def load_assignments():
    path = ROOT / "clusters.json"
    return json.load(open(path)).get("assignments", {}) if path.exists() else {}


def row_properties(record, clusters=()):
    c, routing = record["classification"], record["routing"]
    return {
        "Report ID": {"title": [{"text": {"content": record["id"]}}]},
        "Report Text": rich(record["text"]),
        "Proposed Label": {"select": {"name": c.get("label") or "UNCLASSIFIED"}},
        "Confidence": {"select": {"name": routing["confidence"]}},
        "Routing Reason": rich(routing["reason"]),
        "Fits Taxonomy": {"checkbox": bool(c.get("fits_taxonomy"))},
        "Alternative Label": rich(c.get("alternative_label") or ""),
        "Amplifiers": {"multi_select": [{"name": a} for a in c.get("amplifiers") or []]},
        "Reasoning": rich(c.get("reasoning") or ""),
        "Processing Note": rich(c.get("processing_note") or ""),
        "Status": {"select": {"name": routing["status"]}},
        "Cluster": rich("; ".join(clusters)),
    }


def write_rows(headers, only=None):
    records = json.load(open(ROOT / "results.json"))["records"]
    assignments = load_assignments()  # rewriting a row must not blank out its cluster
    for record in records:
        if only and record["id"] not in only:
            continue
        props = row_properties(record, assignments.get(record["id"], []))
        existing = find_pages(headers, record["id"])
        if existing:
            for page_id in existing:
                notion("PATCH", f"/pages/{page_id}", headers, {"properties": props})
            print(f"{record['id']}: updated {len(existing)} existing row(s)")
        else:
            notion("POST", "/pages", headers, {"parent": {"database_id": DATABASE_ID}, "properties": props})
            print(f"{record['id']}: created")
        time.sleep(0.35)  # Notion allows ~3 requests/second


def write_clusters(headers):
    assignments = load_assignments()
    records = json.load(open(ROOT / "results.json"))["records"]
    for record in records:
        value = "; ".join(assignments.get(record["id"], []))
        for page_id in find_pages(headers, record["id"]):
            notion("PATCH", f"/pages/{page_id}", headers, {"properties": {"Cluster": rich(value)}})
        print(f"{record['id']}: Cluster = {value or '(none)'}")
        time.sleep(0.35)


def verify(headers):
    ids = [r["id"] for r in json.load(open(ROOT / "results.json"))["records"]]
    missing = [i for i in ids if not find_pages(headers, i)]
    print(f"{len(ids) - len(missing)}/{len(ids)} report rows present in Notion" + (f"; missing: {missing}" if missing else ""))
    return not missing


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clusters", action="store_true", help="write clusters.json names into the Cluster column")
    parser.add_argument("--verify", action="store_true", help="check every report has a row")
    parser.add_argument("--only", nargs="*", help="limit row writes to these report ids")
    args = parser.parse_args()
    load_env()
    headers = notion_headers()
    if args.verify:
        sys.exit(0 if verify(headers) else 1)
    if args.clusters:
        write_clusters(headers)
    else:
        write_rows(headers, set(args.only) if args.only else None)


if __name__ == "__main__":
    main()
