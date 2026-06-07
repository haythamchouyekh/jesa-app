# metrics/negative_float.py
# Metric #7: Negative Float
#
# DCMA SPEC:
#   % = (incomplete tasks with total float < 0)
#         / (total incomplete tasks) × 100
#   TARGET: 0% — no negative float allowed

def check_negative_float(activities, threshold_pct=None, hours_per_day=8):
    thresh = threshold_pct if threshold_pct is not None else 0
    hpd    = hours_per_day if hours_per_day and hours_per_day > 0 else 8
    incomplete = [a for a in activities.values()
                  if a.is_incomplete and a.is_normal]
    violations = []

    for act in incomplete:
        if act.total_float < 0:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : (f'Negative total float: '
                              f'{act.total_float}h '
                              f'({round(act.total_float / hpd, 1)} days)'),
            })

    total      = len(incomplete)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #7 - Negative Float',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}%',
        'details'    : violations,
    }
