# metrics/resources.py
# Metric #10: Resources
#
# DCMA SPEC:
#   % = (incomplete normal tasks with NO baseline cost/work assigned)
#         / (total incomplete normal tasks) × 100
#   TARGET: 0% — all incomplete tasks should have resources
#
# FIX vs original:
#   - Now uses act.has_resource which is populated from TASKRSRC in the parser
#     (falls back to wbs_id/calendar_id proxy if TASKRSRC is absent)
#   - Denominator is INCOMPLETE NORMAL tasks only (excludes milestones)
#   - 0% threshold is correct per spec

def check_resources(activities, threshold_pct=None):
    thresh = threshold_pct if threshold_pct is not None else 0
    # DCMA: only normal tasks — excludes milestones, WBS summaries, and LOE
    eligible = [
        a for a in activities.values()
        if a.is_incomplete and a.is_normal
    ]
    violations = []

    for act in eligible:
        if not act.has_resource:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : 'No resource or cost assignment found',
            })

    total      = len(eligible)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #10 - Resources',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}%',
        'details'    : violations,
    }
