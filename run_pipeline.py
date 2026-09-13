"""Orchestrator: runs each incoming report through the whole workflow, one stage at a time.

Deterministic Python coordinates the agents; no model decides control flow.
  0. Preflight: stage gate 1 (classifier tested in isolation) must have passed, or nothing runs.
  1. Classifier agent (Claude): label, amplifiers, and uncertainty signals.
  2. Routing gate: Needs Review or Auto-classified. The model never sets Confirmed.
  3. Notion: write the review-queue row (rate limits and server errors are retried).
  4. Slack: post a review request for every report routed to review, then a run summary.

Failure handling: if the Notion write fails, the report is saved to runs/held_reports.json instead
of being dropped, and Slack gets an integration-failure alert. --retry-held delivers held reports.
Every step is appended to runs/pipeline_log.jsonl as a decision trail.

Usage:
  python run_pipeline.py --input incoming/demo_reports.json
  python run_pipeline.py --input incoming/demo_reports.json --simulate-notion-outage
  python run_pipeline.py --retry-held
  python run_pipeline.py --input incoming/demo_reports.json --reset-demo   # trash those reports' old rows first
  python run_pipeline.py --input incoming/demo_reports.json --no-slack     # print Slack messages, post nothing
"""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

import anthropic
import requests

import write_notion as wn
from classify import DELAY_S, classify_report
from common import MODEL, ROOT, load_env, load_system_prompt
from notify_slack import NOTION_DB_URL, esc
from stage_gates import gate_classifier_isolated

PROMPT = "agent-instructions-v5.txt"
LOG = ROOT / "runs" / "pipeline_log.jsonl"
HELD = ROOT / "runs" / "held_reports.json"
RUN = {}  # run id, model, prompt file and hash: stamped on every log entry so a failure traces to prompt vs model vs data


def log(report_id, stage, outcome, detail="", context=None, **extra):
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **(context or RUN),
             "report_id": report_id, "stage": stage, "outcome": outcome, "detail": detail, **extra}
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[{stage:>10}] {report_id}: {outcome}" + (f"  ·  {detail}" if detail else ""), flush=True)


class Slack:
    def __init__(self, enabled):
        self.enabled = enabled
        self.url = os.environ.get("SLACK_WEBHOOK_URL")

    def post(self, text, blocks):
        """Returns True if posted, False if skipped because of --no-slack."""
        if not self.enabled:
            print(f"             (not posted: --no-slack) {text}")
            return False
        if not self.url:
            raise RuntimeError("SLACK_WEBHOOK_URL is not set")
        resp = requests.post(self.url, json={"text": text, "blocks": blocks}, timeout=30)
        if resp.status_code != 200 or resp.text != "ok":
            raise RuntimeError(f"Slack rejected the message: {resp.status_code} {resp.text}")
        return True


def sent(posted, what):
    return f"{what} posted" if posted else f"{what} built (not posted: --no-slack)"


def section(markdown):
    return [{"type": "section", "text": {"type": "mrkdwn", "text": markdown[:3000]}}]


def notion_headers(simulate_outage):
    if simulate_outage:  # an invalid credential makes Notion reject the write, exactly as a real outage or revoked token would
        return {"Authorization": "Bearer simulated-outage", "Notion-Version": wn.NOTION_VERSION, "Content-Type": "application/json"}
    return wn.notion_headers()


def write_row(headers, record):
    props = wn.row_properties(record)
    existing = wn.find_pages(headers, record["id"])
    if existing:
        page = wn.notion("PATCH", f"/pages/{existing[0]}", headers, {"properties": props})
    else:
        page = wn.notion("POST", "/pages", headers, {"parent": {"database_id": wn.DATABASE_ID}, "properties": props})
    return page["url"]


def review_request(record, url):
    c, routing = record["classification"], record["routing"]
    lines = [f":mag: *Review requested: {record['id']}*",
             f"Proposed label: *{c['label'] or 'UNCLASSIFIED'}* (not final)"
             + (f"  ·  competing label: *{c['alternative_label']}*" if c["alternative_label"] else ""),
             f"Why it needs a person: {esc(routing['reason'])}"]
    if c["processing_note"]:
        lines.append(f"Note: {esc(c['processing_note'])}")
    if c["reasoning"]:
        lines.append(f"Model reasoning: _{esc(c['reasoning'])}_")
    lines.append(f"<{url}|Open in the Notion review queue>")
    return f"Latente AI: review requested for {record['id']}", section("\n".join(lines))


def failure_alert(record, error):
    body = (f":warning: *Integration failure: {record['id']} held for retry*\n"
            "Classification finished, but the Notion review queue could not be updated, so the report was held instead of dropped.\n"
            f"Error: `{esc(error)[:300]}`\n"
            "Recover with `python run_pipeline.py --retry-held`.")
    return f"Latente AI: Notion write failed for {record['id']}, held for retry", section(body)


def load_held():
    return json.load(open(HELD)) if HELD.exists() else []


def save_held(records):
    HELD.parent.mkdir(exist_ok=True)
    HELD.write_text(json.dumps(records, indent=2, ensure_ascii=False))


def deliver(record, headers, slack):
    """Stages 3-4 for one classified report. Returns False if the report had to be held."""
    rid = record["id"]
    ctx = record.setdefault("pipeline_context", dict(RUN))  # a held report keeps the run context it was classified under
    try:
        url = write_row(headers, record)
        log(rid, "notion", "row written", f"status {record['routing']['status']}", context=ctx)
    except Exception as e:
        log(rid, "notion", "FAILED: report held for retry", str(e)[:160], context=ctx)
        save_held([r for r in load_held() if r["id"] != rid] + [record])
        try:
            log(rid, "slack", sent(slack.post(*failure_alert(record, str(e))), "integration-failure alert"), context=ctx)
        except Exception as se:
            log(rid, "slack", "FAILED to post alert", str(se)[:160], context=ctx)
        return False
    if record["routing"]["confidence"] == "REVIEW":
        try:
            log(rid, "slack", sent(slack.post(*review_request(record, url)), "review request"), context=ctx)
        except Exception as e:
            log(rid, "slack", "FAILED: row is in Notion but review request not sent", str(e)[:160], context=ctx)
    else:
        log(rid, "slack", "no review request", "auto-classified; waits for a person to confirm in Notion", context=ctx)
    return True


def post_summary(slack, counts, total):
    line = "  ·  ".join(f"{k}: {v}" for k, v in counts.items())
    try:
        posted = slack.post(f"Latente AI pipeline run: {total} reports",
                            section(f"*Latente AI pipeline run complete*: {total} report(s)  ·  {line}\n<{NOTION_DB_URL}|Open the review queue>"))
        log("-", "slack", sent(posted, "run summary"), line)
    except Exception as e:
        log("-", "slack", "FAILED to post run summary", str(e)[:160])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", help="JSON list of {id, text} reports")
    parser.add_argument("--simulate-notion-outage", action="store_true")
    parser.add_argument("--retry-held", action="store_true")
    parser.add_argument("--reset-demo", action="store_true", help="move existing Notion rows for these report ids to trash first")
    parser.add_argument("--no-slack", action="store_true")
    args = parser.parse_args()
    load_env()
    slack = Slack(enabled=not args.no_slack)
    system = load_system_prompt(ROOT / PROMPT)
    RUN.update({"run_id": uuid.uuid4().hex[:8], "model": MODEL, "prompt": PROMPT,
                "prompt_sha256": hashlib.sha256(system.encode()).hexdigest()[:12]})

    if args.retry_held:
        held = load_held()
        if not held:
            print("No held reports.")
            return
        headers, counts, remaining = notion_headers(False), Counter(), []
        for record in held:
            log(record["id"], "retry", "delivering held report")
            if deliver(record, headers, slack):
                counts[record["routing"]["status"]] += 1
            else:
                remaining.append(record)
                counts["held"] += 1
        save_held(remaining)
        post_summary(slack, counts, len(held))
        sys.exit(1 if remaining else 0)

    if not args.input:
        parser.error("--input is required unless --retry-held is used")
    print(f"Latente AI orchestrator · run {RUN['run_id']} · classifier: Claude {MODEL} · prompt {PROMPT} ({RUN['prompt_sha256']})", flush=True)
    ok, detail = gate_classifier_isolated()
    log("-", "preflight", "stage gate 1 PASS" if ok else "stage gate 1 FAIL", detail)
    if not ok:
        sys.exit("Refusing to run: the classifier has not passed its isolated tests (run test_stage1.py).")

    reports = json.load(open(ROOT / args.input))
    if args.reset_demo:
        real = wn.notion_headers()
        for report in reports:
            for page_id in wn.find_pages(real, report["id"]):
                wn.notion("PATCH", f"/pages/{page_id}", real, {"archived": True})
                log(report["id"], "reset", "previous demo row moved to Notion trash")
    headers = notion_headers(args.simulate_notion_outage)
    client = anthropic.Anthropic()

    counts = Counter()
    for i, report in enumerate(reports):  # reports are independent; run one at a time for rate limits and an ordered trail
        if i:
            time.sleep(DELAY_S)
        record = classify_report(client, system, report)
        c = record["classification"]
        served = ", ".join(sorted({a.get("served_by") or "?" for a in record["raw_responses"]})) or "not sent"
        request = record["raw_responses"][-1].get("request_id") if record["raw_responses"] else None
        log(report["id"], "classifier", f"Claude proposed {c['label'] or 'no label'}",
            f"served by {served} · request {request} · alternative {c['alternative_label']} · fits_taxonomy {c['fits_taxonomy']}",
            request_ids=[a.get("request_id") for a in record["raw_responses"]],
            served_by=[a.get("served_by") for a in record["raw_responses"]],
            parse_stage=record["parse_stage"])
        log(report["id"], "gate", record["routing"]["status"], record["routing"]["reason"])
        counts["held" if not deliver(record, headers, slack) else record["routing"]["status"]] += 1

    post_summary(slack, counts, len(reports))
    if counts.get("held"):
        sys.exit(1)


if __name__ == "__main__":
    main()
