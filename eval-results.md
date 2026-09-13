# Evaluation results

Model: `claude-opus-5` · reports classified: 32/32 · run started 2026-09-13T20:41:09+00:00. All data is synthetic.

## 1. Classification accuracy (vs `true_label`)

**Overall: 23/32 (72%)**

| Label | True n | Correct | Recall | Predicted n | Precision |
|---|---|---|---|---|---|
| PERSON | 7 | 3 | 43% | 3 | 100% |
| TASK | 6 | 4 | 67% | 9 | 44% |
| TECH | 7 | 7 | 100% | 10 | 70% |
| ORG | 6 | 5 | 83% | 6 | 83% |
| ENV | 6 | 4 | 67% | 4 | 100% |

Confusion matrix (rows = true, columns = predicted):

| true \ pred | PERSON | TASK | TECH | ORG | ENV | UNCLASSIFIED |
|---|---|---|---|---|---|---|
| **PERSON** | 3 | 4 |  |  |  |  |
| **TASK** |  | 4 | 1 | 1 |  |  |
| **TECH** |  |  | 7 |  |  |  |
| **ORG** |  |  | 1 | 5 |  |  |
| **ENV** |  | 1 | 1 |  | 4 |  |

| Subset | Accuracy |
|---|---|
| Ambiguous reports | 2/6 (33%) |
| Non-ambiguous reports | 21/26 (81%) |
| Cluster members | 6/12 (50%) |
| Noise reports | 17/20 (85%) |

Misclassified reports routed to human review: **9/9 (100%)** (a wrong label that auto-classified is the costly failure). Misclassified reports whose `alternative_label` was the true label: 4/9 (44%).

## 2. Routing vs the `ambiguous` flag

Positive = routed to human review (`fits_taxonomy` false, `processing_note` set, or `alternative_label` set).

| Metric | Value |
|---|---|
| Routed to review | 27 |
| Ambiguous (ground truth) | 6 |
| Precision | 6/27 (22%) |
| Recall | 6/6 (100%) |

Routing reasons (a report can trigger more than one):

| Reason | Count |
|---|---|
| alternative label named | 27 |
| none | 5 |
| processing note present | 2 |

Routed but not flagged ambiguous:

| Report | Predicted | True | Reason | Alternative |
|---|---|---|---|---|
| R001 | ENV | ENV | alternative label named | ORG |
| R004 | TECH | TECH | alternative label named | TASK |
| R005 | PERSON | PERSON | processing note present; alternative label named | TASK |
| R007 | PERSON | PERSON | alternative label named | TASK |
| R008 | ENV | ENV | alternative label named | TASK |
| R009 | TECH | TECH | alternative label named | TASK |
| R010 | ORG | TASK | alternative label named | TECH |
| R011 | TECH | TECH | alternative label named | ORG |
| R013 | TECH | TECH | alternative label named | ORG |
| R014 | ENV | ENV | alternative label named | ORG |
| R016 | TASK | PERSON | alternative label named | ORG |
| R017 | TASK | TASK | alternative label named | ORG |
| R021 | PERSON | PERSON | alternative label named | ORG |
| R023 | TASK | TASK | alternative label named | ORG |
| R024 | TASK | PERSON | alternative label named | PERSON |
| R026 | TASK | PERSON | alternative label named | ORG |
| R027 | TASK | TASK | alternative label named | ORG |
| R028 | TECH | TECH | alternative label named | PERSON |
| R029 | TASK | TASK | alternative label named | ORG |
| R030 | ORG | ORG | alternative label named | PERSON |
| R032 | TECH | TASK | processing note present; alternative label named | TASK |

## 3. Parse reliability

| Metric | Value |
|---|---|
| Reports | 32 |
| Parse failures after retry | 0/32 (0%) |
| Parsed on raw text | 32 |
| Parsed only after stripping fences/whitespace | 0 |
| Reports needing a second API call | 0 |
| Total API calls | 32 |
| Schema problems in parsed output | 0 |
| Served by a fallback model | 0 |

## 4. Clustering

Match rule, fixed before results existed: P matches C if purity (share of P in C) >= 50% AND coverage (share of C in P) >= 50%.

**clusters_found: 2/2**  ·  proposed clusters: 11  ·  **false_clusters: 9**

| Planted cluster | Matched by | Purity | Coverage |
|---|---|---|---|
| handoff_information_loss | verbal_only_handoff_with_no_required_field | 100% | 67% |
| verification_step_erosion | double_check_present_in_policy_degraded_in_practice | 100% | 83% |

All proposed clusters:

| Proposed cluster | Confidence | Size | Members | Ground-truth composition | Matches planted? |
|---|---|---|---|---|---|
| interrupted_task_resumed_without_external_place_marker | HIGH | 6 | R001, R004, R012, R023, R026, R029 | noise: 6 | no |
| cross_patient_task_interleaving_identity_in_memory | MEDIUM | 5 | R012, R017, R021, R025, R027 | noise: 4, verification_step_erosion: 1 | no |
| double_check_present_in_policy_degraded_in_practice | HIGH | 5 | R006, R018, R020, R024, R032 | verification_step_erosion: 5 | yes |
| automated_signal_read_as_broader_assurance_than_it_covers | MEDIUM | 5 | R011, R013, R015, R025, R032 | noise: 3, handoff_information_loss: 1, verification_step_erosion: 1 | no |
| unannounced_change_to_product_or_system_configuration | MEDIUM | 4 | R004, R011, R012, R015 | noise: 4 | no |
| verbal_only_handoff_with_no_required_field | HIGH | 4 | R002, R010, R016, R022 | handoff_information_loss: 4 | yes |
| capacity_pressure_relocates_care_to_unsuitable_space | MEDIUM | 5 | R001, R008, R014, R019, R025 | noise: 4, handoff_information_loss: 1 | no |
| workload_normalizes_skipped_or_unsupported_steps | MEDIUM | 5 | R006, R017, R018, R021, R031 | noise: 3, verification_step_erosion: 2 | no |
| requests_for_help_or_escalation_not_actionable | MEDIUM | 2 | R030, R031 | noise: 2 | no |
| outdated_record_becomes_default_source_of_truth | MEDIUM | 3 | R013, R020, R024 | verification_step_erosion: 2, handoff_information_loss: 1 | no |
| non_default_device_state_without_persistent_indicator | LOW | 3 | R003, R009, R023 | noise: 3 | no |

### False clusters (no planted match). Read these: some may be real patterns.

- **interrupted_task_resumed_without_external_place_marker** (HIGH): We hypothesize a shared failure mode in which multi-step preparation tasks leave no physical or system artifact showing which steps are already done, so an interruption causes the worker to resume at the wrong point and the omission or duplication is invisible afterward.  
  Members: R001, R004, R012, R023, R026, R029
- **cross_patient_task_interleaving_identity_in_memory** (MEDIUM): We hypothesize that when the same task is run in parallel for several patients, patient-specific parameters or specimens are held in the worker's head or on informal notes rather than bound to the artifact at the point of action, allowing details from one patient to be applied to another.  
  Members: R012, R017, R021, R025, R027
- **automated_signal_read_as_broader_assurance_than_it_covers** (MEDIUM): We hypothesize a shared mechanism in which a system's positive signal, or its silence, is interpreted by staff as confirmation of overall safety when the system in fact checks or displays only a narrow slice, leaving the uncovered gap invisible.  
  Members: R011, R013, R015, R025, R032
- **unannounced_change_to_product_or_system_configuration** (MEDIUM): We hypothesize that changes to packaging, vendor, or software are reaching the point of care without notification, so staff continue to rely on discriminating cues (shape, container, alert behavior, scheduling logic) that are no longer valid.  
  Members: R004, R011, R012, R015
- **capacity_pressure_relocates_care_to_unsuitable_space** (MEDIUM): We hypothesize that bed and room pressure is pushing clinical tasks into physical spaces not designed for them, and that the resulting environmental conditions — noise, sightlines, no clear floor, solar gain — become the proximate hazard.  
  Members: R001, R008, R014, R019, R025
- **workload_normalizes_skipped_or_unsupported_steps** (MEDIUM): We hypothesize that staffing shortfalls and assignment load are converting deliberate safety steps into optional ones, with reporters describing the degraded practice as routine rather than as a deviation.  
  Members: R006, R017, R018, R021, R031
- **requests_for_help_or_escalation_not_actionable** (MEDIUM): We hypothesize that frontline staff who correctly identified risk and asked for support were constrained by unit norms or unavailable backup and proceeded anyway, so the recognition of danger did not translate into a change in care.  
  Members: R030, R031
- **outdated_record_becomes_default_source_of_truth** (MEDIUM): We hypothesize that when current, patient-confirmed information is unavailable or effortful at the moment of decision, stale documentation carried forward from prior encounters becomes the de facto reference and is not re-confirmed.  
  Members: R013, R020, R024
- **non_default_device_state_without_persistent_indicator** (LOW): We hypothesize that devices are allowing temporary or context-dependent settings to persist or silently lapse without a visible, durable indicator, so staff cannot tell from the device that it is in a non-default state.  
  Members: R003, R009, R023

## 5. Amplifier tags vs ground truth

| Tag | True count | Predicted count | Both | Precision | Recall |
|---|---|---|---|---|---|
| INTERRUPTION | 9 | 11 | 9 | 82% | 100% |
| FATIGUE | 9 | 1 | 1 | 100% | 11% |
| MEMORY_LOAD | 8 | 8 | 6 | 75% | 75% |

Exact amplifier-set match: 20/32 (62%). Untagged reports: 12 true vs 16 predicted.

## 6. Clustering stage tested in isolation

Same clustering prompt and match rule, different inputs. This separates clustering quality from upstream classifier errors (does a classifier mistake propagate?) and measures run-to-run stability. The ground-truth condition shows the model only `true_label` and `true_amplifiers`, never `planted_cluster` or `notes_for_eval`.

| Input to clustering | Proposed | Found | handoff purity / coverage | verification purity / coverage | False clusters |
|---|---|---|---|---|---|
| Classifier output (production path) | 11 | 2/2 | 100% / 67% | 100% / 83% | 9 |
| Classifier output, repeated run (stability) | 13 | 2/2 | 100% / 83% | 100% / 83% | 11 |
| Report text only (no classifier) | 11 | 2/2 | 100% / 67% | 100% / 83% | 8 |
| Ground-truth label + amplifiers (perfect upstream classifier) | 11 | 2/2 | 100% / 83% | 83% / 83% | 9 |

## 7. Before/after: prompt v4 vs v5 (traced-failure fixes only)

v5 changes exactly two things found in manual error analysis:
1. It removes the residual 'write the result to the Notion review queue' instruction, which leaked into R032's `processing_note`.
2. It restricts `processing_note` to policy gates, since R005 used it as a reasoning scratchpad.

Taxonomy definitions and the `alternative_label` bar are unchanged. Both runs use the same 32 reports, so this is not a held-out comparison.

| Metric | v4 (baseline) | v5 (fixed) |
|---|---|---|
| Classification accuracy | 23/32 (72%) | 23/32 (72%) |
| Misclassified reports routed to review | 9/9 (100%) | 9/9 (100%) |
| Routed to review | 27/32 (84%) | 27/32 (84%) |
| Routing precision (vs ambiguous) | 6/27 (22%) | 6/27 (22%) |
| Routing recall (vs ambiguous) | 6/6 (100%) | 6/6 (100%) |
| `processing_note` set on a labeled report (no policy gate should fire) | 2 | 0 |
| `alternative_label` named | 27 | 27 |
| `fits_taxonomy` false | 0 | 0 |
| Parse failures after retry | 0/32 (0%) | 0/32 (0%) |
| Exact amplifier-set match | 20/32 (62%) | 22/32 (69%) |
| API cost (classification) | $1.10 | $1.07 |

Reports whose output changed: 9/32

| Report | True label | Changes (v4 → v5) |
|---|---|---|
| R002 | ORG | alternative_label: None → TASK; routing: HIGH → REVIEW |
| R005 | PERSON | alternative_label: TASK → ORG; processing_note: Alternative TASK would apply if the sling procedure includes a pre-lift symmetry or second-person verification step that was absent or unworkable here; that detail is not in the report. 'Second half of a double' is noted but FATIGUE is not assigned, as |
| R008 | ENV | alternative_label: TASK → ORG |
| R014 | ENV | alternative_label: ORG → None; routing: REVIEW → HIGH |
| R016 | PERSON | label: TASK → ORG; alternative_label: ORG → PERSON |
| R020 | PERSON | alternative_label: TECH → PERSON |
| R021 | PERSON | alternative_label: ORG → TASK |
| R026 | PERSON | alternative_label: ORG → ENV |
| R032 | TASK | processing_note: No Notion write tool was available in this session; classification is returned inline for manual entry into the review queue. → None |
