"""Escalation step: post the review-queue summary and latent failure-mode hypotheses to Slack.

Usage:
  python notify_slack.py           # dry run: print the Slack payload, send nothing
  python notify_slack.py --send    # post to the channel behind SLACK_WEBHOOK_URL

The webhook URL is read from SLACK_WEBHOOK_URL (environment or git-ignored .env). Notion page links
use NOTION_TOKEN when available; without it the message links to the database only.
"""
import argparse
import json
import os
import sys
from collections import Counter

import requests

from common import ROOT, load_env

NOTION_DB_URL = "https://www.notion.so/44ee3dfd094d83cfa59a81f1aea58f35"
CONFIDENCE_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def esc(text):
    """Slack mrkdwn requires &, <, > to be escaped."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def page_urls():
    """Map report id -> Notion page URL, if a Notion token is available."""
    if not (os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY")):
        return {}
    import write_notion as w
    headers, urls, cursor = w.notion_headers(), {}, None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        page = w.notion("POST", f"/databases/{w.DATABASE_ID}/query", headers, body)
        for row in page["results"]:
            urls["".join(t["plain_text"] for t in row["properties"]["Report ID"]["title"])] = row["url"]
        if not page["has_more"]:
            return urls
        cursor = page["next_cursor"]


def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}}


def build_blocks(records, clusters, urls):
    link = lambda rid: f"<{urls[rid]}|{rid}>" if rid in urls else rid
    review = [r for r in records if r["routing"]["status"] == "Needs Review"]
    auto = [r for r in records if r["routing"]["status"] == "Auto-classified"]
    reasons = Counter(part for r in review for part in r["routing"]["reason"].split("; "))
    parse_failures = sum(1 for r in records if not r["parsed"])

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "Latente AI · review queue: new batch classified"}},
        section(f"*{len(records)} incident reports* classified. _Synthetic data._\n"
                f"• *{len(review)} need human review*: " + ", ".join(f"{k} ({v})" for k, v in reasons.most_common()) + "\n"
                f"• *{len(auto)} auto-classified*, awaiting human confirmation\n"
                f"• Parse failures: {parse_failures}\n"
                f"<{NOTION_DB_URL}|Open the review queue in Notion>"),
        {"type": "divider"},
    ]
    ranked = sorted(clusters, key=lambda c: (CONFIDENCE_ORDER.get(c.get("confidence"), 3), -len(c["member_ids"])))
    alerts = [c for c in ranked if c.get("confidence") == "HIGH"]
    others = [c for c in ranked if c.get("confidence") != "HIGH"]
    blocks.append(section(f"*Latent failure-mode hypotheses: {len(alerts)} high-confidence alerts*\n"
                          "_Hypotheses for a reviewer to test, not findings._"))
    for c in alerts:
        blocks.append(section(f":rotating_light: *{esc(c['name'])}* ({len(c['member_ids'])} reports)\n"
                              f"{esc(c.get('hypothesis'))}\n"
                              f"Reports: {', '.join(link(m) for m in c['member_ids'])}"))
    if others:
        blocks.append(section("*Lower-confidence hypotheses*\n" + "\n".join(
            f"• [{c.get('confidence')}] {esc(c['name'])} ({len(c['member_ids'])}): {', '.join(link(m) for m in c['member_ids'])}"
            for c in others)))
    return blocks


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--send", action="store_true", help="post to Slack (default is a dry run)")
    args = parser.parse_args()
    load_env()

    records = json.load(open(ROOT / "results.json"))["records"]
    clusters = json.load(open(ROOT / "clusters.json"))["clusters"]
    blocks = build_blocks(records, clusters, page_urls())
    payload = {"text": f"Latente AI: {len(records)} incident reports classified", "blocks": blocks}

    if not args.send:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("\nDry run only. Re-run with --send to post.", file=sys.stderr)
        return
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        sys.exit("SLACK_WEBHOOK_URL is not set.")
    resp = requests.post(webhook, json=payload, timeout=30)
    if resp.status_code != 200 or resp.text != "ok":
        sys.exit(f"Slack rejected the message: {resp.status_code} {resp.text}")
    print(f"Posted to Slack: {len(blocks)} blocks")


if __name__ == "__main__":
    main()
