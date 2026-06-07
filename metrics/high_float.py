# metrics/high_float.py
# Metric #6: High Float (Total Slack)
#
# DCMA SPEC:
#   % = (incomplete normal tasks with total float > 44 working days)
#         / (total incomplete normal tasks) × 100
#   TARGET: should not exceed 5%
#   EXCLUDES: milestones, WBS summary tasks, LOE tasks
#
# hours_per_day is read from the project's base calendar so the threshold
# comparison uses actual working hours rather than assuming 8 h/day.

FLOAT_THRESHOLD_DAYS = 44   # DCMA standard
THRESHOLD_PCT        = 5


def check_high_float(activities, float_days=None, threshold_pct=None, hours_per_day=8):
    f_days  = float_days if float_days is not None else FLOAT_THRESHOLD_DAYS
    hpd     = hours_per_day if hours_per_day and hours_per_day > 0 else 8
    f_hours = f_days * hpd
    thresh  = threshold_pct if threshold_pct is not None else THRESHOLD_PCT

    eligible = [
        a for a in activities.values()
        if a.is_incomplete and a.is_normal
    ]
    violations = []

    for act in eligible:
        if act.total_float > f_hours:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : (f'Excessive total float: '
                              f'{round(act.total_float, 1)}h '
                              f'({round(act.total_float / hpd, 1)} days) '
                              f'> {f_days} days limit'),
            })

    # Deduplicate by task_code (safeguard)
    seen, unique = set(), []
    for v in violations:
        if v['task_code'] not in seen:
            seen.add(v['task_code'])
            unique.append(v)
    violations = unique

    total      = len(eligible)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #6 - High Float',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}% with float > {f_days} days',
        'details'    : violations,
    }
