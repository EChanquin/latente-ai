# Stage gates

Checked in order; the run stops at the first failing gate.

| Gate | Stage | Result | Detail |
|---|---|---|---|
| 1 | Classifier, isolated tests | PASS | 6/6 policy-gate cases passed |
| 2 | Classifier, full run | PASS | parse-failure rate 0%; silent errors 0 |

Thresholds: `policy_gate_pass_rate_min` = 1.0, `parse_failure_rate_max` = 0.05, `silent_errors_max` = 0, `notion_rows_missing_max` = 0, `planted_clusters_found_min` = 2, `unlinked_alert_members_max` = 0
