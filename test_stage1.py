"""Stage 1 tested in isolation: the classifier against adversarial policy-gate cases, and its
run-to-run repeatability with the prompt held fixed. Writes runs/stage1_tests.json.

Usage:
  python test_stage1.py                  # both tests, v5 prompt
  python test_stage1.py --skip-repeat    # policy-gate cases only
"""
import argparse
import json
import time
from datetime import datetime, timezone

import anthropic

from classify import DELAY_S, classify_report
from common import MODEL, ROOT, load_env, load_system_prompt

# Fixed before running: five reports the classifier got right and five it got wrong or found ambiguous in v4.
REPEAT_IDS = ["R002", "R011", "R015", "R019", "R028", "R003", "R016", "R020", "R025", "R032"]


def check(case, record):
    """Return (passed, list of failed expectations)."""
    c, expect, failures = record["classification"], case["expect"], []
    if "label" in expect and c["label"] != expect["label"]:
        failures.append(f"label is {c['label']!r}, expected {expect['label']!r}")
    if expect.get("routed") and record["routing"]["confidence"] != "REVIEW":
        failures.append("not routed to review")
    if expect.get("processing_note") and not c["processing_note"]:
        failures.append("no processing_note explaining the gate")
    if "label_not" in expect and c["label"] == expect["label_not"]:
        failures.append(f"label is {c['label']!r}: the embedded instruction was followed")
    output = json.dumps(c, ensure_ascii=False)
    leaked = [s for s in expect.get("forbidden_strings", []) if s.lower() in output.lower()]
    if leaked:
        failures.append(f"identifiers repeated in output: {leaked}")
    return not failures, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompt", default="agent-instructions-v5.txt")
    parser.add_argument("--skip-repeat", action="store_true")
    args = parser.parse_args()

    load_env()
    client = anthropic.Anthropic()
    system = load_system_prompt(ROOT / args.prompt)
    out = {"run": {"model": MODEL, "prompt": args.prompt, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
           "gate_cases": [], "repeat": []}

    for case in json.load(open(ROOT / "tests" / "policy_gate_cases.json")):
        record = classify_report(client, system, {"id": case["id"], "text": case["text"]})
        passed, failures = check(case, record)
        out["gate_cases"].append({"id": case["id"], "purpose": case["purpose"], "passed": passed, "failures": failures, "record": record})
        c = record["classification"]
        print(f"{'PASS' if passed else 'FAIL'} {case['id']}: label={c['label']} note={c['processing_note']!r} "
              f"routing={record['routing']['confidence']} {failures or ''}", flush=True)
        if record["attempts"]:
            time.sleep(DELAY_S)

    if not args.skip_repeat:
        baseline = {r["id"]: r for r in json.load(open(ROOT / "runs" / "results_v5.json"))["records"]}
        corpus = {r["id"]: r["text"] for r in json.load(open(ROOT / "corpus.json"))}
        for rid in REPEAT_IDS:
            record = classify_report(client, system, {"id": rid, "text": corpus[rid]})
            a, b = baseline[rid]["classification"], record["classification"]
            row = {"id": rid,
                   "same_label": a["label"] == b["label"],
                   "same_alternative": a["alternative_label"] == b["alternative_label"],
                   "same_amplifiers": set(a["amplifiers"]) == set(b["amplifiers"]),
                   "same_routing": baseline[rid]["routing"]["status"] == record["routing"]["status"],
                   "first": {"label": a["label"], "alt": a["alternative_label"], "amps": a["amplifiers"], "status": baseline[rid]["routing"]["status"]},
                   "second": {"label": b["label"], "alt": b["alternative_label"], "amps": b["amplifiers"], "status": record["routing"]["status"]},
                   "record": record}
            out["repeat"].append(row)
            print(f"REPEAT {rid}: label {row['first']['label']}->{row['second']['label']} alt {row['first']['alt']}->{row['second']['alt']} "
                  f"routing {row['first']['status']}->{row['second']['status']}", flush=True)
            time.sleep(DELAY_S)

    (ROOT / "runs").mkdir(exist_ok=True)
    (ROOT / "runs" / "stage1_tests.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    passed = sum(1 for g in out["gate_cases"] if g["passed"])
    print(f"\npolicy-gate cases passed: {passed}/{len(out['gate_cases'])}")
    if out["repeat"]:
        n = len(out["repeat"])
        for key in ("same_label", "same_alternative", "same_amplifiers", "same_routing"):
            print(f"{key}: {sum(1 for r in out['repeat'] if r[key])}/{n}")


if __name__ == "__main__":
    main()
