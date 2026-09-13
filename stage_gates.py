"""Check each pipeline stage against fixed thresholds, in order, stopping at the first failure.

A stage's output is only trusted downstream once its gate passes. Thresholds are fixed here, not
tuned to results. Gates read saved outputs; gate 3 makes a read-only Notion call and gate 6 builds
the Slack message as a dry run (nothing is posted).

Usage:
  python stage_gates.py               # all gates -> runs/stage_gates.md
  python stage_gates.py --through 2   # stop after gate 2
"""
import argparse
import json
import sys

from common import ROOT, load_env

THRESHOLDS = {
    "policy_gate_pass_rate_min": 1.0,     # every adversarial case must pass
    "parse_failure_rate_max": 0.05,
    "silent_errors_max": 0,               # wrong label that was auto-classified
    "notion_rows_missing_max": 0,
    "planted_clusters_found_min": 2,
    "unlinked_alert_members_max": 0,
}


def gate_classifier_isolated():
    path = ROOT / "runs" / "stage1_tests.json"
    if not path.exists():
        return False, "runs/stage1_tests.json missing: run test_stage1.py first"
    cases = json.load(open(path))["gate_cases"]
    passed = sum(1 for c in cases if c["passed"])
    failed = [f"{c['id']} ({'; '.join(c['failures'])})" for c in cases if not c["passed"]]
    ok = cases and passed / len(cases) >= THRESHOLDS["policy_gate_pass_rate_min"]
    return ok, f"{passed}/{len(cases)} policy-gate cases passed" + (f"; failed: {', '.join(failed)}" if failed else "")


def gate_classifier_full():
    truth = {r["id"]: r for r in json.load(open(ROOT / "corpus.json"))}
    records = json.load(open(ROOT / "results.json"))["records"]
    failure_rate = sum(1 for r in records if not r["parsed"]) / len(records)
    silent = [r["id"] for r in records if r["classification"]["label"] != truth[r["id"]]["true_label"]
              and r["routing"]["confidence"] == "HIGH"]
    ok = failure_rate <= THRESHOLDS["parse_failure_rate_max"] and len(silent) <= THRESHOLDS["silent_errors_max"]
    return ok, f"parse-failure rate {failure_rate:.0%}; silent errors {len(silent)}" + (f" ({', '.join(silent)})" if silent else "")


def gate_review_queue():
    import write_notion as w
    headers = w.notion_headers()
    ids = [r["id"] for r in json.load(open(ROOT / "results.json"))["records"]]
    missing = [i for i in ids if not w.find_pages(headers, i)]
    return len(missing) <= THRESHOLDS["notion_rows_missing_max"], f"{len(ids) - len(missing)}/{len(ids)} rows present" + (f"; missing {missing}" if missing else "")


def found_clusters(path):
    import eval as ev
    truth = {r["id"]: r for r in json.load(open(ROOT / "corpus.json"))}
    data = json.load(open(path))
    if data.get("parse_failure"):
        return None, 0
    ids = set(truth)
    invalid = [m for c in data["clusters"] for m in c["member_ids"] if m not in ids]
    _, found, _, _ = ev.score_clusters(truth, data["clusters"])
    return invalid, len(found)


def gate_clustering_isolated():
    path = ROOT / "ablations" / "clusters_truth.json"
    if not path.exists():
        return False, "ablations/clusters_truth.json missing: run cluster.py --input truth"
    invalid, found = found_clusters(path)
    if invalid is None:
        return False, "isolated clustering output did not parse"
    return found >= THRESHOLDS["planted_clusters_found_min"], f"{found}/2 planted clusters found with ground-truth input"


def gate_clustering_production():
    invalid, found = found_clusters(ROOT / "clusters.json")
    if invalid is None:
        return False, "clusters.json did not parse"
    ok = not invalid and found >= THRESHOLDS["planted_clusters_found_min"]
    return ok, f"{found}/2 planted clusters found; invalid member ids: {len(invalid)}"


def gate_escalation():
    import notify_slack as ns
    records = json.load(open(ROOT / "results.json"))["records"]
    clusters = json.load(open(ROOT / "clusters.json"))["clusters"]
    urls = ns.page_urls()
    blocks = ns.build_blocks(records, clusters, urls)
    alerted = {m for c in clusters if c.get("confidence") == "HIGH" for m in c["member_ids"]}
    unlinked = sorted(m for m in alerted if m not in urls)
    ok = bool(blocks) and len(unlinked) <= THRESHOLDS["unlinked_alert_members_max"]
    return ok, f"{len(blocks)} Slack blocks built (dry run); {len(alerted) - len(unlinked)}/{len(alerted)} alerted reports link to Notion"


GATES = [
    ("Classifier, isolated tests", gate_classifier_isolated),
    ("Classifier, full run", gate_classifier_full),
    ("Review queue (Notion)", gate_review_queue),
    ("Clustering, isolated (ground-truth input)", gate_clustering_isolated),
    ("Clustering, production", gate_clustering_production),
    ("Escalation (Slack, dry run)", gate_escalation),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--through", type=int, default=len(GATES))
    args = parser.parse_args()
    load_env()

    lines = ["# Stage gates", "", "Checked in order; the run stops at the first failing gate.", "",
             "| Gate | Stage | Result | Detail |", "|---|---|---|---|"]
    status = 0
    for number, (name, gate) in enumerate(GATES[:args.through], start=1):
        try:
            ok, detail = gate()
        except Exception as e:  # a gate that cannot run has not passed
            ok, detail = False, f"gate could not run: {type(e).__name__}: {e}"
        lines.append(f"| {number} | {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
        print(f"Gate {number} {'PASS' if ok else 'FAIL'}: {name}: {detail}", flush=True)
        if not ok:
            lines.append("")
            lines.append(f"Stopped at gate {number}. Later stages are not trusted until it passes.")
            status = 1
            break
    lines += ["", "Thresholds: " + ", ".join(f"`{k}` = {v}" for k, v in THRESHOLDS.items())]
    (ROOT / "runs").mkdir(exist_ok=True)
    (ROOT / "runs" / "stage_gates.md").write_text("\n".join(lines) + "\n")
    sys.exit(status)


if __name__ == "__main__":
    main()
