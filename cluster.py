"""Step 4: propose latent failure modes across all classified reports, save clusters.json.

The model sees each report's text plus the classifier's label, amplifiers, and reasoning. It never
sees ground truth (this script does not read those fields) and is never told how many clusters exist.
"""
import json
import sys
import time
from datetime import datetime, timezone

import anthropic

from common import MODEL, ROOT, load_env, response_text, try_parse

SYSTEM = """You are the pattern-analysis stage of a patient safety review system used by quality and safety staff at a hospital. Each incident report below has already been classified on its own, one report at a time. Single-report analysis misses system-level vulnerability: a latent failure mode can surface across several reports that describe it in different words, attribute it to different proximate causes, and never name the underlying pattern.

Your task: propose latent failure modes, meaning groups of reports that share a contributing factor that no single report names.

Rules:
- Group by a shared underlying mechanism, not by surface features. Sharing a label, an amplifier tag, a unit, a reporter role, or a time of day is not a failure mode on that basis alone.
- Propose as many or as few clusters as the evidence supports, including none. Not every report belongs to a cluster, and a report may belong to more than one.
- Each cluster is a hypothesis for human reviewers, not a finding. Phrase it as a hypothesis and say what in the member reports supports it.
- Confidence is HIGH, MEDIUM, or LOW and reflects how strongly the member reports support one shared mechanism.
- Never propose corrective actions or assign blame. Never repeat patient or staff identifiers.

Return only a JSON object with this shape. No markdown fences, no text before or after it.
{"clusters": [{"name": "<short snake_case name>", "hypothesis": "<one or two sentences, phrased as a hypothesis>", "confidence": "<HIGH, MEDIUM, or LOW>", "member_ids": ["<report id>", "..."], "evidence": "<brief: how the member reports each show the shared factor>"}]}"""


def main():
    load_env()
    records = json.load(open(ROOT / "results.json"))["records"]
    items = [{"id": r["id"], "text": r["text"], "label": r["classification"]["label"],
              "amplifiers": r["classification"]["amplifiers"], "reasoning": r["classification"]["reasoning"]}
             for r in records]
    valid_ids = {r["id"] for r in items}
    user = "Classified incident reports (JSON):\n\n" + json.dumps(items, indent=1, ensure_ascii=False)

    client = anthropic.Anthropic()
    raw_responses, parsed, stage = [], None, None
    for attempt in (1, 2):
        message = client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=SYSTEM,
            messages=[{"role": "user", "content": user}],
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        text = response_text(message)
        raw_responses.append({"text": text, "stop_reason": message.stop_reason, "served_by": message.model,
                              "request_id": message._request_id,
                              "usage": {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}})
        parsed, stage = try_parse(text)
        if parsed is not None and isinstance(parsed.get("clusters"), list):
            break
        parsed = None
        time.sleep(1)
    if parsed is None:
        (ROOT / "clusters.json").write_text(json.dumps({"parse_failure": True, "raw_responses": raw_responses}, indent=2))
        sys.exit("Clustering response did not parse after retry; raw output saved to clusters.json")

    warnings, assignments = [], {}
    for cluster in parsed["clusters"]:
        unknown = [m for m in cluster.get("member_ids", []) if m not in valid_ids]
        if unknown:
            warnings.append(f"{cluster.get('name')}: unknown ids dropped {unknown}")
        cluster["member_ids"] = sorted({m for m in cluster.get("member_ids", []) if m in valid_ids})
        for member in cluster["member_ids"]:
            assignments.setdefault(member, []).append(cluster["name"])

    out = {"run": {"model": MODEL, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "attempts": len(raw_responses), "parse_stage": stage},
           "clusters": parsed["clusters"], "assignments": assignments, "warnings": warnings,
           "raw_responses": raw_responses}
    (ROOT / "clusters.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    for c in parsed["clusters"]:
        print(f"[{c.get('confidence')}] {c['name']} ({len(c['member_ids'])}): {', '.join(c['member_ids'])}\n    {c.get('hypothesis')}")
    if warnings:
        print("warnings:", warnings)


if __name__ == "__main__":
    main()
