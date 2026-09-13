"""Step 5: score results.json and clusters.json against corpus.json ground truth -> eval-results.md.

Cluster match rule (fixed before any results existed, never changed afterward):
a proposed cluster P matches planted cluster C if BOTH
  purity   = |P ∩ C| / |P| >= 0.5
  coverage = |P ∩ C| / |C| >= 0.5
"""
import json
from collections import Counter

from common import ROOT

LABELS = ["PERSON", "TASK", "TECH", "ORG", "ENV"]
AMPS = ["INTERRUPTION", "FATIGUE", "MEMORY_LOAD"]
PLANTED = ["handoff_information_loss", "verification_step_erosion"]


def pct(n, d):
    return f"{n / d:.0%}" if d else "n/a"


def frac(n, d):
    return f"{n}/{d} ({pct(n, d)})"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def classification_section(truth, records):
    out = ["## 1. Classification accuracy (vs `true_label`)", ""]
    correct = [r for r in records if r["classification"].get("label") == truth[r["id"]]["true_label"]]
    out.append(f"**Overall: {frac(len(correct), len(records))}**")
    out.append("")
    rows = []
    for label in LABELS:
        with_true = [r for r in records if truth[r["id"]]["true_label"] == label]
        predicted = [r for r in records if r["classification"].get("label") == label]
        hits = [r for r in with_true if r["classification"].get("label") == label]
        rows.append([label, len(with_true), len(hits), pct(len(hits), len(with_true)),
                     len(predicted), pct(len(hits), len(predicted))])
    out += [table(["Label", "True n", "Correct", "Recall", "Predicted n", "Precision"], rows), ""]

    cols = LABELS + ["UNCLASSIFIED"]
    matrix = []
    for label in LABELS:
        counts = Counter(r["classification"].get("label") or "UNCLASSIFIED"
                         for r in records if truth[r["id"]]["true_label"] == label)
        matrix.append([f"**{label}**"] + [counts.get(c, "") for c in cols])
    out += ["Confusion matrix (rows = true, columns = predicted):", "",
            table(["true \\ pred"] + cols, matrix), ""]

    def subset(name, pred):
        sub = [r for r in records if pred(truth[r["id"]])]
        hit = [r for r in sub if r["classification"].get("label") == truth[r["id"]]["true_label"]]
        return [name, frac(len(hit), len(sub))]

    out += [table(["Subset", "Accuracy"], [
        subset("Ambiguous reports", lambda t: t["ambiguous"]),
        subset("Non-ambiguous reports", lambda t: not t["ambiguous"]),
        subset("Cluster members", lambda t: t["planted_cluster"]),
        subset("Noise reports", lambda t: not t["planted_cluster"]),
    ]), ""]

    wrong = [r for r in records if r not in correct]
    caught = [r for r in wrong if r["routing"]["confidence"] == "REVIEW"]
    alt_right = [r for r in wrong if r["classification"].get("alternative_label") == truth[r["id"]]["true_label"]]
    out += [f"Misclassified reports routed to human review: **{frac(len(caught), len(wrong))}** "
            f"(a wrong label that auto-classified is the costly failure). "
            f"Misclassified reports whose `alternative_label` was the true label: {frac(len(alt_right), len(wrong))}.", ""]
    silent = [r for r in wrong if r["routing"]["confidence"] == "HIGH"]
    if silent:
        out += ["Wrong and auto-classified (silent errors):", "",
                table(["Report", "True", "Predicted", "Ambiguous", "Reasoning"],
                      [[r["id"], truth[r["id"]]["true_label"], r["classification"].get("label"),
                        truth[r["id"]]["ambiguous"], r["classification"].get("reasoning", "")] for r in silent]), ""]
    return out


def routing_section(truth, records):
    out = ["## 2. Routing vs the `ambiguous` flag", "",
           "Positive = routed to human review (`fits_taxonomy` false, `processing_note` set, or `alternative_label` set).", ""]
    routed = {r["id"] for r in records if r["routing"]["confidence"] == "REVIEW"}
    ambiguous = {i for i, t in truth.items() if t["ambiguous"] and i in {r["id"] for r in records}}
    tp = routed & ambiguous
    out += [table(["Metric", "Value"], [
        ["Routed to review", len(routed)],
        ["Ambiguous (ground truth)", len(ambiguous)],
        ["Precision", frac(len(tp), len(routed))],
        ["Recall", frac(len(tp), len(ambiguous))],
    ]), ""]
    reasons = Counter(part for r in records for part in r["routing"]["reason"].split("; "))
    out += ["Routing reasons (a report can trigger more than one):", "",
            table(["Reason", "Count"], sorted(reasons.items(), key=lambda kv: -kv[1])), ""]
    by_id = {r["id"]: r for r in records}
    missed = sorted(ambiguous - routed)
    extra = sorted(routed - ambiguous)
    if missed:
        out += ["Ambiguous but auto-classified (missed):", "",
                table(["Report", "Predicted", "True", "Settling fact (notes_for_eval)"],
                      [[i, by_id[i]["classification"].get("label"), truth[i]["true_label"], truth[i]["notes_for_eval"]] for i in missed]), ""]
    if extra:
        out += ["Routed but not flagged ambiguous:", "",
                table(["Report", "Predicted", "True", "Reason", "Alternative"],
                      [[i, by_id[i]["classification"].get("label"), truth[i]["true_label"], by_id[i]["routing"]["reason"],
                        by_id[i]["classification"].get("alternative_label")] for i in extra]), ""]
    return out


def parse_section(run, records):
    out = ["## 3. Parse reliability", ""]
    failures = [r for r in records if not r["parsed"]]
    attempts = Counter(r["attempts"] for r in records)
    stages = Counter(r["parse_stage"] or "failed" for r in records)
    out += [table(["Metric", "Value"], [
        ["Reports", len(records)],
        ["Parse failures after retry", frac(len(failures), len(records))],
        ["Parsed on raw text", stages.get("direct", 0)],
        ["Parsed only after stripping fences/whitespace", stages.get("stripped", 0)],
        ["Reports needing a second API call", sum(n for a, n in attempts.items() if a > 1)],
        ["Total API calls", sum(r["attempts"] for r in records)],
        ["Schema problems in parsed output", sum(1 for r in records if r.get("schema_errors"))],
        ["Served by a fallback model", sum(1 for r in records if any(a.get("served_by") and a["served_by"] != run["model"] for a in r["raw_responses"]))],
    ]), ""]
    return out


def score_clusters(truth, proposed):
    """Apply the fixed match rule. Returns (planted, found, false_clusters, detail rows)."""
    planted = {c: {i for i, t in truth.items() if t["planted_cluster"] == c} for c in PLANTED}
    found, false_clusters, detail = {}, [], []
    for p in proposed:
        members = set(p["member_ids"])
        matched = False
        for c, cm in planted.items():
            k = len(members & cm)
            purity, coverage = (k / len(members) if members else 0), k / len(cm)
            if purity >= 0.5 and coverage >= 0.5:
                matched = True
                best = found.get(c)
                if not best or (purity + coverage) > (best[1] + best[2]):
                    found[c] = (p["name"], purity, coverage)
        if not matched:
            false_clusters.append(p)
        composition = Counter(truth[i]["planted_cluster"] or "noise" for i in members if i in truth)
        detail.append([p["name"], p.get("confidence", ""), len(members), ", ".join(sorted(members)),
                       ", ".join(f"{k}: {v}" for k, v in composition.most_common()), "yes" if matched else "no"])
    return planted, found, false_clusters, detail


def cluster_section(truth, clusters):
    out = ["## 4. Clustering", "",
           "Match rule, fixed before results existed: P matches C if purity (share of P in C) >= 50% "
           "AND coverage (share of C in P) >= 50%.", ""]
    proposed = clusters["clusters"]
    planted, found, false_clusters, detail = score_clusters(truth, proposed)

    out += [f"**clusters_found: {len(found)}/2**  ·  proposed clusters: {len(proposed)}  ·  **false_clusters: {len(false_clusters)}**", ""]
    rows = []
    for c in PLANTED:
        if c in found:
            name, purity, coverage = found[c]
            rows.append([c, name, f"{purity:.0%}", f"{coverage:.0%}"])
        else:
            best = max(((p["name"], len(set(p["member_ids"]) & planted[c]) / max(len(p["member_ids"]), 1),
                         len(set(p["member_ids"]) & planted[c]) / len(planted[c])) for p in proposed),
                       key=lambda x: x[1] + x[2], default=("—", 0, 0))
            rows.append([c, f"not matched (closest: {best[0]})", f"{best[1]:.0%}", f"{best[2]:.0%}"])
    out += [table(["Planted cluster", "Matched by", "Purity", "Coverage"], rows), ""]
    out += ["All proposed clusters:", "",
            table(["Proposed cluster", "Confidence", "Size", "Members", "Ground-truth composition", "Matches planted?"], detail), ""]
    if false_clusters:
        out += ["### False clusters (no planted match). Read these: some may be real patterns.", ""]
        for p in false_clusters:
            out += [f"- **{p['name']}** ({p.get('confidence', '')}): {p.get('hypothesis', '')}  ", f"  Members: {', '.join(p['member_ids'])}"]
        out.append("")
    return out


ABLATION_LABELS = {
    "classifier": "Classifier output (production path)",
    "classifier_repeat": "Classifier output, repeated run (stability)",
    "truth": "Ground-truth label + amplifiers (perfect upstream classifier)",
    "text-only": "Report text only (no classifier)",
}


def isolation_section(truth):
    """Score the clustering stage under different inputs with the same fixed match rule."""
    conditions = [("classifier", ROOT / "clusters.json")]
    conditions += [(p.stem.removeprefix("clusters_"), p) for p in sorted((ROOT / "ablations").glob("clusters_*.json"))]
    if len(conditions) == 1:
        return []
    out = ["## 6. Clustering stage tested in isolation", "",
           "Same clustering prompt and match rule, different inputs. This separates clustering quality from "
           "upstream classifier errors (does a classifier mistake propagate?) and measures run-to-run stability. "
           "The ground-truth condition shows the model only `true_label` and `true_amplifiers`, never "
           "`planted_cluster` or `notes_for_eval`.", ""]
    rows = []
    for key, path in conditions:
        data = json.load(open(path))
        label = ABLATION_LABELS.get(key, key)
        if data.get("parse_failure"):
            rows.append([label, "parse failure", "", "", "", ""])
            continue
        _, found, false_clusters, _ = score_clusters(truth, data["clusters"])
        cells = [label, len(data["clusters"]), f"{len(found)}/2"]
        for c in PLANTED:
            cells.append(f"{found[c][1]:.0%} / {found[c][2]:.0%}" if c in found else "not matched")
        cells.append(len(false_clusters))
        rows.append(cells)
    out += [table(["Input to clustering", "Proposed", "Found", "handoff purity / coverage",
                   "verification purity / coverage", "False clusters"], rows), ""]
    return out


def amplifier_section(truth, records):
    out = ["## 5. Amplifier tags vs ground truth", ""]
    rows = []
    for amp in AMPS:
        true_ids = {r["id"] for r in records if amp in truth[r["id"]]["true_amplifiers"]}
        pred_ids = {r["id"] for r in records if amp in (r["classification"].get("amplifiers") or [])}
        tp = true_ids & pred_ids
        rows.append([amp, len(true_ids), len(pred_ids), len(tp), pct(len(tp), len(pred_ids)), pct(len(tp), len(true_ids))])
    exact = sum(1 for r in records if set(r["classification"].get("amplifiers") or []) == set(truth[r["id"]]["true_amplifiers"]))
    true_empty = sum(1 for r in records if not truth[r["id"]]["true_amplifiers"])
    pred_empty = sum(1 for r in records if not r["classification"].get("amplifiers"))
    out += [table(["Tag", "True count", "Predicted count", "Both", "Precision", "Recall"], rows), "",
            f"Exact amplifier-set match: {frac(exact, len(records))}. Untagged reports: {true_empty} true vs {pred_empty} predicted.", ""]
    return out


def main():
    truth = {r["id"]: r for r in json.load(open(ROOT / "corpus.json"))}
    results = json.load(open(ROOT / "results.json"))
    records = results["records"]
    out = ["# Evaluation results", "",
           f"Model: `{results['run']['model']}` · reports classified: {len(records)}/{len(truth)} · "
           f"run started {results['run']['started_at']}. All data is synthetic.", ""]
    out += classification_section(truth, records)
    out += routing_section(truth, records)
    out += parse_section(results["run"], records)
    if (ROOT / "clusters.json").exists():
        out += cluster_section(truth, json.load(open(ROOT / "clusters.json")))
    else:
        out += ["## 4. Clustering", "", "_Not run yet._", ""]
    out += amplifier_section(truth, records)
    out += isolation_section(truth)
    (ROOT / "eval-results.md").write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
