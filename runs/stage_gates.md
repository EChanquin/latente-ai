# Stage gates

Checked in order; the run stops at the first failing gate.

| Gate | Stage | Result | Detail |
|---|---|---|---|
| 1 | Classifier, isolated tests | PASS | 6/6 policy-gate cases passed |
| 2 | Classifier, full run | PASS | parse-failure rate 0%; silent errors 0 |
| 3 | Review queue (Notion) | PASS | 32/32 rows present |
| 4 | Clustering, isolated (ground-truth input) | PASS | 2/2 planted clusters found with ground-truth input |
| 5 | Clustering, production | PASS | 2/2 planted clusters found; invalid member ids: 0 |
| 6 | Escalation (Slack, dry run) | PASS | 8 Slack blocks built (dry run); 15/15 alerted reports link to Notion |

Thresholds: `policy_gate_pass_rate_min` = 1.0, `parse_failure_rate_max` = 0.05, `silent_errors_max` = 0, `notion_rows_missing_max` = 0, `planted_clusters_found_min` = 2, `unlinked_alert_members_max` = 0
