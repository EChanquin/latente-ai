"""Steps 1-2: classify every report in corpus.json, apply review routing, save results.json.

Only each report's `text` is sent to the model. Ground-truth fields (true_label, true_amplifiers,
planted_cluster, ambiguous, notes_for_eval) are never read here.

Usage:
  python classify.py                 # classify all reports not already in results.json
  python classify.py --only R001     # classify specific reports (merged into results.json)
  python classify.py --fresh         # discard results.json and classify everything
"""
import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import anthropic

from common import MODEL, ROOT, load_env, load_system_prompt, response_text, try_parse

LABELS = {"PERSON", "TASK", "TECH", "ORG", "ENV"}
AMPLIFIERS = {"INTERRUPTION", "FATIGUE", "MEMORY_LOAD"}
PARSE_FAILURE_NOTE = "parse failure after retry"
DELAY_S = 1.0
RESULTS = ROOT / "results.json"


def call_model(client, system, text):
    """One API call. Returns the raw response text plus metadata, or the error if the call failed."""
    started = time.time()
    try:
        message = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": text}],
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
            anthropic.NotFoundError, anthropic.BadRequestError):
        raise  # configuration problems: stop the run instead of burning 32 failed reports
    except anthropic.APIError as e:  # rate limits / 5xx / network, after the SDK's own retries
        return {"text": None, "error": f"{type(e).__name__}: {e}", "latency_s": round(time.time() - started, 2)}
    return {
        "text": response_text(message),
        "stop_reason": message.stop_reason,
        "served_by": message.model,
        "request_id": message._request_id,
        "usage": {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens},
        "latency_s": round(time.time() - started, 2),
    }


def normalize(obj):
    """Coerce the parsed object into the output schema and list anything that did not conform."""
    errors = []
    for key in ["label", "alternative_label", "amplifiers", "fits_taxonomy", "reasoning", "processing_note"]:
        if key not in obj:
            errors.append(f"missing key: {key}")
    c = {
        "label": obj.get("label"),
        "alternative_label": obj.get("alternative_label"),
        "amplifiers": obj.get("amplifiers") or [],
        "fits_taxonomy": obj.get("fits_taxonomy"),
        "reasoning": obj.get("reasoning"),
        "processing_note": obj.get("processing_note"),
    }
    for key in ("alternative_label", "processing_note"):
        if isinstance(c[key], str) and not c[key].strip():
            c[key] = None  # an empty string is not a real signal
    if c["label"] is not None and c["label"] not in LABELS:
        errors.append(f"label not in taxonomy: {c['label']!r}")
    if c["alternative_label"] is not None and c["alternative_label"] not in LABELS:
        errors.append(f"alternative_label not in taxonomy: {c['alternative_label']!r}")
    if not isinstance(c["amplifiers"], list):
        errors.append(f"amplifiers not a list: {c['amplifiers']!r}")
        c["amplifiers"] = []
    unknown = [a for a in c["amplifiers"] if a not in AMPLIFIERS]
    if unknown:
        errors.append(f"unknown amplifiers dropped: {unknown}")
        c["amplifiers"] = [a for a in c["amplifiers"] if a in AMPLIFIERS]
    if not isinstance(c["fits_taxonomy"], bool):
        errors.append(f"fits_taxonomy not boolean: {c['fits_taxonomy']!r}")
    return c, errors


def route(c):
    """Route to human review if ANY explicit uncertainty signal is present.

    Reports with no signal are marked "Auto-classified", never "Confirmed": only a human reviewer
    confirms or rejects a label, even when every threshold is met.
    """
    reasons = []
    if c["fits_taxonomy"] is not True:
        reasons.append("taxonomy does not fit")
    if c["processing_note"] is not None:
        reasons.append("processing note present")
    if c["alternative_label"] is not None:
        reasons.append("alternative label named")
    if reasons:
        return {"confidence": "REVIEW", "status": "Needs Review", "reason": "; ".join(reasons)}
    return {"confidence": "HIGH", "status": "Auto-classified", "reason": "none"}


def classify_report(client, system, report):
    raw_responses = []
    for attempt in (1, 2):
        raw = call_model(client, system, report["text"])
        raw_responses.append(raw)
        obj, stage = try_parse(raw["text"])  # 1) raw JSON, 2) fences/whitespace stripped
        if obj is not None:
            classification, errors = normalize(obj)
            return {"id": report["id"], "text": report["text"], "parsed": True, "attempts": attempt,
                    "parse_stage": stage, "schema_errors": errors, "classification": classification,
                    "routing": route(classification), "raw_responses": raw_responses}
        if attempt == 1:
            time.sleep(DELAY_S)  # 3) retry the API call once
    # 4) record the failure explicitly
    classification = {"label": None, "alternative_label": None, "amplifiers": [], "fits_taxonomy": None,
                      "reasoning": None, "processing_note": PARSE_FAILURE_NOTE}
    return {"id": report["id"], "text": report["text"], "parsed": False, "attempts": 2, "parse_stage": None,
            "schema_errors": [], "classification": classification, "routing": route(classification),
            "raw_responses": raw_responses}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="report ids to (re)classify")
    parser.add_argument("--fresh", action="store_true", help="ignore existing results.json")
    parser.add_argument("--reroute", action="store_true", help="recompute routing from saved classifications (no API calls)")
    parser.add_argument("--prompt", default="agent-instructions-v4.txt", help="instructions file for the system prompt")
    parser.add_argument("--results", default="results.json", help="output path, e.g. runs/results_v5.json")
    args = parser.parse_args()
    global RESULTS
    RESULTS = ROOT / args.results
    RESULTS.parent.mkdir(parents=True, exist_ok=True)

    if args.reroute:
        results = json.load(open(RESULTS))
        for record in results["records"]:
            record["routing"] = route(record["classification"])
        RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print("rerouted:", dict(Counter(r["routing"]["status"] for r in results["records"])))
        return

    load_env()
    system = load_system_prompt(ROOT / args.prompt)
    reports = [{"id": r["id"], "text": r["text"]} for r in json.load(open(ROOT / "corpus.json"))]

    if RESULTS.exists() and not args.fresh:
        results = json.load(open(RESULTS))
    else:
        results = {"run": {"model": MODEL, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "system_prompt_sha256": hashlib.sha256(system.encode()).hexdigest(),
                           "system_prompt_source": f"{args.prompt}, '## CONTEXT' to end, minus '## WRITING THE RESULT'",
                           "fallbacks": "server-side default", "delay_between_calls_s": DELAY_S},
                   "records": []}
    done = {r["id"] for r in results["records"]}
    if args.only:
        todo = [r for r in reports if r["id"] in set(args.only)]
    else:
        todo = [r for r in reports if r["id"] not in done]

    client = anthropic.Anthropic()
    for i, report in enumerate(todo):
        if i:
            time.sleep(DELAY_S)
        record = classify_report(client, system, report)
        results["records"] = [r for r in results["records"] if r["id"] != record["id"]] + [record]
        results["records"].sort(key=lambda r: r["id"])
        RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False))  # saved after every report
        c = record["classification"]
        print(f"{record['id']}: label={c['label']} alt={c['alternative_label']} amps={c['amplifiers']} "
              f"fits={c['fits_taxonomy']} -> {record['routing']['confidence']} ({record['routing']['reason']}) "
              f"attempts={record['attempts']} stage={record['parse_stage']}", flush=True)

    records = results["records"]
    failures = sum(1 for r in records if not r["parsed"])
    print(f"\n{len(records)} classified | parse failures {failures}/{len(records)} | "
          f"second API call needed {sum(1 for r in records if r['attempts'] > 1)} | "
          f"parsed only after stripping {sum(1 for r in records if r['parse_stage'] == 'stripped')} | "
          f"routed to review {sum(1 for r in records if r['routing']['confidence'] == 'REVIEW')}")


if __name__ == "__main__":
    sys.exit(main())
