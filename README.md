# Latent failure detection for patient safety incident reports

**All data in this repository is synthetic.** No real patients, staff, or incidents. `corpus.json` was written for this project; it contains no PHI.

## Problem and intended outcome

**User:** a hospital quality and safety reviewer working through incoming incident reports.

**Problem:** Reports are reviewed one at a time. Each gets a contributing-factor category and is filed. Practitioners describe this taxonomy mapping as largely failed. Labels are inconsistent, and system-level hazards stay invisible because each report blames a different proximate cause.

**What the agent does, as one workflow:** ingest an incident report → propose a contributing factor, amplifiers, and explicit uncertainty signals → send anything uncertain to a human review queue in Notion → cluster the full set into latent failure-mode hypotheses and log them back to the queue.

**Intended outcome:**
- The reviewer's attention goes to the reports that need it.
- A confident but wrong label never silently enters the pattern analysis.
- Cross-report hazards surface as hypotheses a person can check.

**Success criteria, measured on a synthetic test corpus:**
- Every wrong label reaches a human.
- Planted cross-report patterns are recovered under a match rule fixed in advance.
- Every number is reproducible from this repository.

**Not yet measured:** reviewer time saved in a live setting.

## Where the idea came from

The idea came out of practitioner conversations at a patient safety fellowship. Two points kept coming up:
- Mapping incident reports onto a contributing-factor taxonomy had largely failed as a practice: labels were applied inconsistently and rarely changed anything.
- Analysing reports one at a time misses system-level vulnerability, because a latent hazard is spread across reports that each blame a different proximate cause.

This project keeps the taxonomy as a first pass, makes its uncertainty explicit instead of hiding it, and puts the real weight on cross-report pattern detection.

## What was built

```mermaid
flowchart LR
    A[Incident report<br/>text only] --> B[Stage 1: Classifier agent<br/>claude-opus-5]
    B -->|unparseable twice| P[processing_note set]
    B --> G{Gate: any uncertainty signal?<br/>fits_taxonomy false<br/>alternative_label set<br/>processing_note set}
    P --> G
    G -->|yes| R[Notion: Needs Review]
    G -->|no| Q[Notion: Auto-classified]
    R --> H((Human reviewer<br/>Confirmed / Rejected))
    Q --> H
    B --> C[Stage 2: Clustering agent<br/>all reports, one call]
    C --> N[Notion: Cluster column]
    C --> S[Slack: pattern alerts<br/>+ review-queue summary]
    S --> H
    N --> H
```

A human sits above every path. The model can only ever set `Needs Review` or `Auto-classified`.

### Stages, inputs, and outputs

| Stage | Purpose | Input | Output | Gate / escalation | Stage-specific eval |
|---|---|---|---|---|---|
| 1. Classifier (`classify.py`) | Propose one contributing factor per report | Report text only | label, alternative_label, amplifiers, fits_taxonomy, reasoning, processing_note | Two-step parse, then one retry; any uncertainty signal routes to review | Label accuracy; amplifier precision and recall; parse-failure rate |
| 2. Routing (`classify.py`) | Decide what a human must look at | Stage 1 output | Needs Review / Auto-classified, with reason | Rule-based; never sets Confirmed | Routing precision and recall vs `ambiguous`; share of wrong labels that reached review |
| 3. Review queue (`write_notion.py`) | Put decisions in front of a reviewer | Stage 1–2 output | One Notion row per report | `--verify` checks that every report landed | 32/32 rows present |
| 4. Clustering (`cluster.py`) | Surface cross-report latent failure modes | Text + stage 1 output | Cluster hypotheses with confidence and members | Every cluster is a hypothesis for a person, not a finding | Purity/coverage under a fixed match rule; false clusters; tested in isolation (below) |
| 5. Escalation (`notify_slack.py`) | Alert reviewers to patterns | Stage 3–4 output | Slack message linking Notion rows | Dry run by default; `--send` posts | Message content checked in dry run |

1. **Classification** (`classify.py`). Each report's text alone is sent to Claude with the system prompt from `agent-instructions-v4.txt`. The model returns one primary label (PERSON, TASK, TECH, ORG, ENV), zero or more amplifiers (INTERRUPTION, FATIGUE, MEMORY_LOAD), a one-sentence reasoning, and three uncertainty signals: `fits_taxonomy`, `alternative_label`, and `processing_note`.
2. **Routing.** A report goes to human review if *any* uncertainty signal fires; otherwise it is auto-classified. The triggering condition is recorded as the routing reason.
3. **Review queue** (`write_notion.py`). One Notion database row per report, with label, confidence (HIGH or REVIEW), routing reason, reasoning, and status. The model only ever sets `Needs Review` or `Auto-classified`. `Confirmed` and `Rejected` are reserved for a human reviewer, so human judgment stays above the model even when every threshold is met.
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

### Clustering stage tested in isolation

The clustering prompt was run on four inputs and scored with the same fixed match rule. The ground-truth condition shows only `true_label` and `true_amplifiers`, never `planted_cluster` or `notes_for_eval`. These three extra runs cost about $0.75.

| Input to clustering | Found | handoff purity / coverage | verification purity / coverage | False clusters |
|---|---|---|---|---|
| Classifier output (production path) | 2/2 | 100% / 67% | 100% / 83% | 9 |
| Classifier output, repeated run | 2/2 | 100% / 83% | 100% / 83% | 11 |
| Report text only (no classifier) | 2/2 | 100% / 67% | 100% / 83% | 8 |
| Ground-truth labels + amplifiers | 2/2 | 100% / 83% | 83% / 83% | 9 |

- **Classifier errors do not propagate into clustering.** Scores are essentially unchanged whether clustering sees the classifier's output, perfect labels, or no labels at all.
- **The flip side:** the classifier's value in this workflow is review routing, not feeding the pattern stage.
- **The planted clusters are stable across repeated runs.** The number of false clusters varies from 8 to 11, so any single run's false clusters should be read with that variance in mind.
- **Several false clusters recur across independent runs.** That recurrence makes them more credible as real, unplanted patterns:
  - In all 4 runs: interrupted multi-step task resumed at the wrong step, care performed in a space unfit for the task, and risk voiced with no change in care.
  - In 3 of 4: unannounced product or system change, and a stale record accepted as current.

### Manual error analysis: traced failures by stage

All 9 misclassifications and both unexpected processing notes were read by hand against the report text, the model's reasoning, and the corpus's settling facts.

| Failure category | Reports | Where it breaks | What the trace shows | Proposed fix at that stage |
|---|---|---|---|---|
| Taxonomy definition mismatch | R016, R020, R024, R026 (PERSON → TASK) | Taxonomy definition, before the model runs | The classifier prompt defines TASK as covering "skipped or degraded steps". The corpus reserves TASK for complexity, sequencing, and post-completion steps. An individual's slip that involves a skipped step is therefore read as TASK, correctly by the prompt's own wording. | Align the TASK and PERSON definitions between prompt and answer key |
| Instruction leakage | R032 | Prompt construction | The Langflow-specific write step was stripped, but the TASK section still says "Then write the result to the Notion review queue." The model reported "No Notion write tool was available" in `processing_note`, which routed the report to review. | Remove the residual write instruction from the prompt |
| Field misuse | R005 | Output schema | `processing_note` holds the model's reasoning about an alternative label instead of a policy-gate message, which inflates review routing. | Constrain `processing_note` to the policy gates, e.g. an enum of gate reasons |
| Genuine ambiguity (working as designed) | R003, R020, R022, R025 | None | The model chose the other defensible label, named the competing label or reasoning, and routed to review. | None. This is the intended behavior. |
| Handoff read as structure | R010 | Classifier judgment | A skipped handoff step under time pressure was read as ORG, production pressure, rather than TASK. | Examples contrasting TASK and ORG in the prompt |

None of these fixes has been applied. Applying them and re-scoring on this same 32-report corpus would overstate the improvement, so the next iteration needs a held-out set.

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
