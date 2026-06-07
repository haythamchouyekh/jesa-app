# metrics/long_duration.py
# Metric #8: High Duration (Long Activity Durations)
#
# DCMA SPEC:
#   % = (incomplete normal tasks with BASELINE duration > 44 working days)
#         / (total incomplete normal tasks) × 100
#   TARGET: should not exceed 5%
#   EXCLUDES: milestones, WBS summary tasks, LOE tasks
#
# hours_per_day is read from the project's base calendar so the threshold
# comparison uses actual working hours rather than assuming 8 h/day.

DURATION_THRESHOLD_DAYS = 44
THRESHOLD_PCT           = 5


def check_long_duration(activities, duration_days=None, threshold_pct=None, hours_per_day=8):
    d_days  = duration_days if duration_days is not None else DURATION_THRESHOLD_DAYS
    hpd     = hours_per_day if hours_per_day and hours_per_day > 0 else 8
    d_hours = d_days * hpd
    thresh  = threshold_pct if threshold_pct is not None else THRESHOLD_PCT

    eligible = [
        a for a in activities.values()
        if a.is_incomplete and a.is_normal
    ]
    violations = []

    for act in eligible:
        dur = act.base_duration if act.base_duration > 0 else act.duration
        if dur > d_hours:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : (f'Baseline duration too long: '
                              f'{dur}h '
                              f'({round(dur / hpd, 1)} days) '
                              f'— exceeds {d_days} days limit'),
            })

    total      = len(eligible)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #8 - Long Activity Durations',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}% with duration > {d_days} days',
        'details'    : violations,
    }
