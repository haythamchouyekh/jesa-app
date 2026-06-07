# metrics/open_ends.py
# Metric #1: Logic (Open Ends)
#
# DCMA SPEC:
#   % = (incomplete tasks with no predecessor OR no successor)
#         / (total incomplete tasks) × 100
#   TARGET: should not exceed 5%
#
# FIX vs original:
#   - Denominator is now INCOMPLETE tasks only (not all tasks)
#   - Threshold changed from 0% to 5%
#   - Only incomplete activities are checked (complete ones can have open ends)

THRESHOLD_PCT = 5   # DCMA: max 5 %


def check_open_ends(activities, threshold_pct=None):
    thresh = threshold_pct if threshold_pct is not None else THRESHOLD_PCT
    # PDF spec: "lowest-level tasks" — excludes milestones, WBS summaries, LOE
    incomplete = [a for a in activities.values() if a.is_incomplete and a.is_normal]
    violations = []

    for act in incomplete:
        no_pred = len(act.predecessors) == 0
        no_succ = len(act.successors)   == 0

        if no_pred and no_succ:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : 'No predecessors AND no successors (fully isolated)',
            })
        elif no_pred:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : 'No predecessors (open start)',
            })
        elif no_succ:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : 'No successors (open finish)',
            })

    total      = len(incomplete)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #1 - Logic (Open Ends)',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}%',
        'details'    : violations,
    }
