# Latent failure detection for patient safety incident reports

**All data in this repository is synthetic.** No real patients, staff, or incidents. `corpus.json` was written for this project; it contains no PHI.

Most incident-review tooling reads one report at a time and files it under a contributing-factor category. This project does that step, but treats it as the input to a second question: *which failure modes show up across many reports that each describe them differently and never name them?*

## Where the idea came from

The idea came out of practitioner conversations at a patient safety fellowship. Two points kept coming up:
- Mapping incident reports onto a contributing-factor taxonomy had largely failed as a practice: labels were applied inconsistently and rarely changed anything.
- Analysing reports one at a time misses system-level vulnerability, because a latent hazard is spread across reports that each blame a different proximate cause.

This project keeps the taxonomy as a first pass, makes its uncertainty explicit instead of hiding it, and puts the real weight on cross-report pattern detection.

## What was built

```
corpus.json ──► classify.py ──► routing ──► Notion review queue ──► cluster.py ──► Cluster column ──► eval.py
 (intake)      one report per    explicit     one row per report     all reports      written back       scored vs
               API call, SEIPS-  uncertainty  (HIGH / REVIEW)        in one call,     to Notion          ground truth
               style label       signals                             hypotheses
```

1. **Classification** (`classify.py`). Each report's text alone is sent to Claude with the system prompt from `agent-instructions-v4.txt`. The model returns one primary label (PERSON, TASK, TECH, ORG, ENV), zero or more amplifiers (INTERRUPTION, FATIGUE, MEMORY_LOAD), a one-sentence reasoning, and three uncertainty signals: `fits_taxonomy`, `alternative_label`, and `processing_note`.
2. **Routing.** A report goes to human review if *any* uncertainty signal fires; otherwise it is auto-classified. The triggering condition is recorded as the routing reason.
3. **Review queue** (`write_notion.py`). One Notion database row per report, with label, confidence (HIGH or REVIEW), routing reason, reasoning, and status (Confirmed or Needs Review).
4. **Clustering** (`cluster.py`). A separate model call receives all classifications (text, label, amplifiers, reasoning) and proposes latent failure modes. Each is phrased as a hypothesis with a confidence level and member report ids. The model is not told how many clusters exist. Proposed cluster names are written back to the Cluster column in Notion.
5. **Evaluation** (`eval.py`). Results are scored against the ground truth in `corpus.json` and written to `eval-results.md`.

### External apps

| App | Role |
|---|---|
| **Anthropic Claude API** (`claude-opus-5`) | Per-report classification and cross-report clustering |
| **Notion** | Human review queue: one row per report, plus the cluster hypothesis for each |
| **Intake source** | Incident reports arrive as `corpus.json`, a synthetic stand-in for an incident-reporting system export. A Langflow flow was built first as a proof of concept of the intake-to-Notion path; its rows (`R-001`) remain in the database as evidence. |

## How to run

```bash
python3 -m venv .venv && .venv/bin/pip install anthropic requests
```

Create a `.env` file (git-ignored) with `ANTHROPIC_API_KEY=...` and `NOTION_TOKEN=...`, or export both in your shell. Share the Notion database with your integration first.

```bash
.venv/bin/python classify.py                  # steps 1-2 -> results.json (resumes if interrupted)
.venv/bin/python write_notion.py              # step 3 -> one Notion row per report
.venv/bin/python write_notion.py --verify     # confirm every report has a row
.venv/bin/python cluster.py                   # step 4 -> clusters.json
.venv/bin/python write_notion.py --clusters   # write cluster names into Notion
.venv/bin/python eval.py                      # step 5 -> eval-results.md
```

A full run of 32 reports plus clustering cost roughly $1–2 in API usage.

## How reliability was tested

**A corpus built to be scored honestly.** `corpus.json` holds 32 reports: two planted latent failure modes (`handoff_information_loss` and `verification_step_erosion`, 6 reports each) and 20 unrelated noise reports.
- **Hidden from the label:** cluster members are spread across different primary labels, reporter roles, units, and times of day, so no label reveals a cluster.
- **Hidden from the amplifiers:** amplifier tags are deliberately decontaminated. No single tag appears on more than 4 members of either cluster, and filtering on any one tag recovers neither cluster under the match rule below. That was verified before any model ran.
- **Ambiguous reports:** 6 are ambiguous by design. Each has a named "settling fact" that would decide its label.
- **Near-misses:** 4 reports are near-misses where no harm reached the patient.

**Ground truth never reaches the model.** Only `text` is sent for classification. The clustering call gets text plus the classifier's own outputs. `true_label`, `true_amplifiers`, `planted_cluster`, `ambiguous`, and `notes_for_eval` are read only by `eval.py`.

**Routing uses signals the model states, not sampled agreement.** Sampling-based confidence (3 runs at temperature 0.7) was tested earlier and abandoned: outputs were near-deterministic, and the temperature control was not reachable in the tooling. Routing is built on explicit uncertainty signals the model emits instead. This was a deliberate choice, not a shortcut. The system prompt sets a high bar for `alternative_label` and asks the model to flag a poor taxonomy fit rather than force one, because a confident wrong label corrupts the pattern data while a review flag costs only staff time.

**Parse failures are measured, not hidden.** For each report:
1. Parse the response as JSON.
2. On failure, strip markdown fences and whitespace and parse again.
3. On a second failure, retry the API call once.
4. If that also fails, record `label: null` with `processing_note: "parse failure after retry"`, which routes the report to review.

Every raw response, its parse stage, and its attempt count is saved in `results.json`.

**The cluster match rule was fixed before any results existed and was not changed afterward.** A proposed cluster P matches a planted cluster C only if both hold:
- **Purity:** at least 50% of P's members belong to C.
- **Coverage:** P contains at least 50% of C's members, i.e. 3 of 6.

Proposed clusters that match nothing are counted and listed as false clusters, not dropped. Some may be real patterns the corpus did not intend.

## Evaluation results

<!-- EVAL:START -->
One run over all 32 reports with `claude-opus-5`: 33 API calls, about $1.33. Full breakdown, confusion matrix, and per-report lists are in [`eval-results.md`](eval-results.md).

| Metric | Result |
|---|---|
| Parse failures after retry | **0/32** (0 retries needed, 0 schema errors) |
| Classification accuracy | **23/32 (72%)** |
| Misclassified reports routed to human review | **9/9 (100%)**: no wrong label was auto-classified |
| Routing recall (ambiguous reports sent to review) | **6/6 (100%)** |
| Routing precision (routed reports that were ambiguous) | **6/27 (22%)** |
| Planted clusters found | **2/2** |
| False clusters | 9 |

### Classification by label

| Label | True n | Recall | Predicted n | Precision |
|---|---|---|---|---|
| PERSON | 7 | 43% | 3 | 100% |
| TASK | 6 | 67% | 9 | 44% |
| TECH | 7 | 100% | 10 | 70% |
| ORG | 6 | 83% | 6 | 83% |
| ENV | 6 | 67% | 4 | 100% |

Accuracy was 81% on non-ambiguous reports and 33% on ambiguous ones. It was 85% on noise and 50% on cluster members, which were built to be spread across labels.

### Clusters (match rule fixed in advance)

| Planted cluster | Matched by proposed cluster | Purity | Coverage |
|---|---|---|---|
| `handoff_information_loss` | `verbal_only_handoff_with_no_required_field` | 100% | 67% |
| `verification_step_erosion` | `double_check_present_in_policy_degraded_in_practice` | 100% | 83% |

The model proposed 11 clusters; 9 match no planted cluster. Some of these read as plausible real patterns rather than noise, for example `unannounced_change_to_product_or_system_configuration` (look-alike product substitutions, a phone software push, and an EHR default change) and `interrupted_task_resumed_without_external_place_marker`. They are listed in full in `eval-results.md`.

### Amplifiers

| Tag | True count | Predicted | Precision | Recall |
|---|---|---|---|---|
| INTERRUPTION | 9 | 11 | 82% | 100% |
| FATIGUE | 9 | 1 | 100% | 11% |
| MEMORY_LOAD | 8 | 8 | 75% | 75% |

### What the numbers say

- **Parsing is fully reliable.** No failures, no retries, no schema errors.
- **The routing gate caught every wrong label,** which is the property the design is built around. A confident wrong label that bypasses review is the costly failure, and it did not occur.
- **Routing is over-cautious.** The model named an `alternative_label` on 27 of 32 reports despite the prompt's high bar, so the review queue is larger than it needs to be. Calibrating that signal is the clearest next improvement. We did not tune the prompt after seeing these results.
- **The main label confusion is PERSON read as TASK** (4 of 7). Individual slips described inside a multi-step procedure pull toward TASK.
- **FATIGUE recall is low by design tension, not a parsing issue.** The prompt forbids tagging FATIGUE from night-shift timing alone. The corpus tagged it more liberally. The two definitions disagree.
- **Clustering recovered both planted failure modes with no false members,** despite their members being filed under different labels and amplifiers.
<!-- EVAL:END -->

## Repository contents

| File | Purpose |
|---|---|
| `corpus.json` | 32 synthetic reports with ground-truth labels, amplifiers, planted clusters, ambiguity flags |
| `agent-instructions-v4.txt` | Classifier instructions. The `## WRITING THE RESULT` section is Langflow-specific and is stripped at runtime. |
| `common.py` | Shared helpers: `.env` loading, JSON parsing, prompt extraction |
| `classify.py` | Steps 1–2: classification, parse-failure handling, routing → `results.json` |
| `write_notion.py` | Step 3: Notion rows, cluster write-back, verification |
| `cluster.py` | Step 4: latent failure mode proposals → `clusters.json` |
| `eval.py` | Step 5: scoring → `eval-results.md` |
| `results.json`, `clusters.json`, `eval-results.md` | Outputs of the run reported above |

No API keys or tokens are committed. Credentials are read from environment variables or a git-ignored `.env`.
