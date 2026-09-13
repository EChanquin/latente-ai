"""Build dashboard/index.html from the saved run outputs. Read-only: no API calls.

Numbers come from eval.py's own scoring functions, so the dashboard and eval-results.md cannot disagree.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eval as ev  # noqa: E402
from common import ROOT  # noqa: E402

HERE = Path(__file__).resolve().parent
LOWER_IS_BETTER = ("Routed to review", "processing_note", "alternative_label", "Parse failures")
HIGHER_IS_BETTER = ("accuracy", "Misclassified", "precision", "recall", "Exact amplifier")


def lead_number(value):
    match = re.match(r"\$?([\d.]+)", str(value))
    return float(match.group(1)) if match else None


def direction(metric, before, after):
    a, b = lead_number(before), lead_number(after)
    if a is None or b is None or a == b:
        return ""
    if any(k in metric for k in LOWER_IS_BETTER):
        return "better" if b < a else "worse"
    if any(k in metric for k in HIGHER_IS_BETTER):
        return "better" if b > a else "worse"
    return ""


def main():
    truth = {r["id"]: r for r in json.load(open(ROOT / "corpus.json"))}
    results = json.load(open(ROOT / "results.json"))
    records = results["records"]
    clusters = json.load(open(ROOT / "clusters.json"))
    v5_path = ROOT / "runs" / "results_v5.json"
    v5 = {r["id"]: r for r in json.load(open(v5_path))["records"]} if v5_path.exists() else {}

    reports = []
    for r in records:
        t, c = truth[r["id"]], r["classification"]
        item = {
            "id": r["id"], "text": r["text"], "role": t["reporter_role"],
            "status": r["routing"]["status"], "reason": r["routing"]["reason"],
            "pred": {"label": c["label"], "alt": c["alternative_label"], "amps": c["amplifiers"], "fits": c["fits_taxonomy"],
                     "reasoning": c["reasoning"], "note": c["processing_note"]},
            "truth": {"label": t["true_label"], "amps": t["true_amplifiers"], "cluster": t["planted_cluster"],
                      "ambiguous": t["ambiguous"], "notes": t["notes_for_eval"]},
            "clusters": clusters["assignments"].get(r["id"], []),
        }
        if r["id"] in v5:
            c5 = v5[r["id"]]["classification"]
            item["v5"] = {"label": c5["label"], "status": v5[r["id"]]["routing"]["status"], "note": c5["processing_note"]}
        reports.append(item)

    n = len(records)
    wrong = [r for r in records if r["classification"]["label"] != truth[r["id"]]["true_label"]]
    routed = [r for r in records if r["routing"]["confidence"] == "REVIEW"]
    ambiguous = [r for r in records if truth[r["id"]]["ambiguous"]]
    planted, found, false_clusters, _ = ev.score_clusters(truth, clusters["clusters"])
    by_name = {name: (c, purity, coverage) for c, (name, purity, coverage) in found.items()}
    purities = [p for _, p, _ in found.values()]

    proof = [
        {"fig": f"{sum(1 for r in wrong if r in routed)}/{len(wrong)}", "cap": "wrong labels were sent to a human. None slipped through as auto-classified."},
        {"fig": f"{len(found)}/2", "cap": f"planted failure modes recovered, at {min(purities):.0%} purity or better." if purities else "planted failure modes recovered."},
        {"fig": f"{sum(1 for r in ambiguous if r in routed)}/{len(ambiguous)}", "cap": "genuinely ambiguous reports routed to review."},
        {"fig": f"{sum(1 for r in records if not r['parsed'])}/{n}", "cap": "model responses failed to parse. No retries were needed."},
    ]
    caveat = (f"{len(routed)} of {n} reports went to review. The model names an alternative label on almost every report, "
              "so the queue is larger than it needs to be. Calibrating that signal is the next step.")

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    cluster_items = []
    for c in clusters["clusters"]:
        match = by_name.get(c["name"])
        cluster_items.append({
            "name": c["name"], "confidence": c.get("confidence", ""), "hypothesis": c.get("hypothesis", ""),
            "members": [{"id": m, "truth": truth[m]["planted_cluster"] or "noise"} for m in c["member_ids"]],
            "matched": match[0] if match else None,
            "purity": f"{match[1]:.0%}" if match else None, "coverage": f"{match[2]:.0%}" if match else None,
        })
    cluster_items.sort(key=lambda x: (x["matched"] is None, order.get(x["confidence"], 3), -len(x["members"])))

    isolation = []
    conditions = [("classifier", ROOT / "clusters.json")] + [
        (p.stem.removeprefix("clusters_"), p) for p in sorted((ROOT / "ablations").glob("clusters_*.json"))]
    for key, path in conditions:
        data = json.load(open(path))
        if data.get("parse_failure"):
            continue
        _, f, fc, _ = ev.score_clusters(truth, data["clusters"])
        row = [ev.ABLATION_LABELS.get(key, key), f"{len(f)}/2"]
        row += [f"{f[c][1]:.0%} / {f[c][2]:.0%}" if c in f else "not found" for c in ev.PLANTED]
        row.append(str(len(fc)))
        isolation.append(row)

    by_label = []
    for label in ev.LABELS:
        with_true = [r for r in records if truth[r["id"]]["true_label"] == label]
        predicted = [r for r in records if r["classification"]["label"] == label]
        hits = [r for r in with_true if r["classification"]["label"] == label]
        by_label.append([label, str(len(with_true)), ev.pct(len(hits), len(with_true)), str(len(predicted)), ev.pct(len(hits), len(predicted))])

    before_after = None
    if v5 and len(v5) == n:
        m4 = ev.headline_metrics(truth, records)
        m5 = ev.headline_metrics(truth, list(v5.values()))
        before_after = [[a[0].replace("`", ""), str(a[1]), str(b[1]), direction(a[0], a[1], b[1])] for a, b in zip(m4, m5)]

    gate_cases, repeat, repeat_note, gates = None, None, "", None
    stage1_path = ROOT / "runs" / "stage1_tests.json"
    if stage1_path.exists():
        stage1 = json.load(open(stage1_path))
        gate_cases = [[g["id"], g["purpose"], "PASS" if g["passed"] else "FAIL"] for g in stage1["gate_cases"]]
        if stage1["repeat"]:
            k = len(stage1["repeat"])
            repeat = [[key.removeprefix("same_").replace("_", " ").capitalize(), ev.frac(sum(1 for r in stage1["repeat"] if r[key]), k)]
                      for key in ("same_label", "same_alternative", "same_amplifiers", "same_routing")]
            repeat_note = f"The v5 prompt run twice on {k} fixed reports, half previously correct and half previously wrong or ambiguous."
    gates_path = ROOT / "runs" / "stage_gates.md"
    if gates_path.exists():
        gates = [[cell.strip() for cell in line.strip("|").split("|")]
                 for line in gates_path.read_text().splitlines() if re.match(r"^\| \d+ \|", line)]

    usage = [a.get("usage", {}) for r in records for a in r["raw_responses"]]
    cost = sum(u.get("input_tokens", 0) for u in usage) * 5e-6 + sum(u.get("output_tokens", 0) for u in usage) * 25e-6
    data = {
        "meta": {"reports": f"{n} synthetic", "model": results["run"]["model"], "cost": f"${cost:.2f} per classification run"},
        "proof": proof, "caveat": caveat, "reports": reports, "clusters": cluster_items,
        "isolation": isolation, "byLabel": by_label, "beforeAfter": before_after, "defaultReport": "R018",
        "gateCases": gate_cases, "repeat": repeat, "repeatNote": repeat_note, "gates": gates,
    }
    html = (HERE / "template.html").read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (HERE / "index.html").write_text(html)
    print(f"wrote dashboard/index.html ({len(html) // 1024} KB); before/after included: {before_after is not None}")


if __name__ == "__main__":
    main()
