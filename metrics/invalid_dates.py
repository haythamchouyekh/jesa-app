# metrics/invalid_dates.py
# Metric #9: Invalid Dates
#
# DCMA SPEC — flags any of:
#   (a) Actual Start or Actual Finish AFTER the project data date
#   (b) Scheduled Start BEFORE the data date with no actual start recorded
#   (b2) Scheduled Finish BEFORE the data date with no actual finish (for in-progress tasks)
#   (c) Missing early start or early finish dates
#   (d) Finish date before start date
#   TARGET: 0% — no invalid dates
#
# Denominator: incomplete tasks only (excludes completed tasks per spec)

from datetime import datetime


def _parse_date(d):
    if not d or str(d).strip() in ('', 'None', 'nan'):
        return None
    s = str(d).strip()[:16]
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def check_invalid_dates(activities, data_date_str=None, threshold_pct=None):
    thresh = threshold_pct if threshold_pct is not None else 0
    # DCMA spec: denominator = incomplete tasks excluding WBS summaries and LOE.
    # WBS/LOE dates are calculated from children, not entered directly, so
    # flagging them for date issues produces false positives.
    incomplete = [a for a in activities.values()
                  if a.is_incomplete and not a.is_summary]
    data_date  = _parse_date(data_date_str)
    violations = []

    for act in incomplete:
        start      = _parse_date(act.start)
        finish     = _parse_date(act.finish)
        act_start  = _parse_date(act.act_start)
        act_finish = _parse_date(act.act_finish)

        # (c) Missing scheduled dates
        if not start and not finish:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : 'Missing both early start and early finish dates',
            })
            continue   # no further checks meaningful without dates

        if not start:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : 'Missing early start date',
            })

        if not finish:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : 'Missing early finish date',
            })

        # (d) Finish before start
        if start and finish and finish < start:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : f'Finish date precedes start date: {act.start} → {act.finish}',
            })

        if data_date:
            # (a) Actual dates recorded AFTER data date (future actuals = invalid)
            if act_start and act_start > data_date:
                violations.append({
                    'task_code': act.task_code,
                    'task_name': act.task_name,
                    'issue'    : f'Actual start ({act.act_start}) is after data date ({data_date_str})',
                })

            if act_finish and act_finish > data_date:
                violations.append({
                    'task_code': act.task_code,
                    'task_name': act.task_name,
                    'issue'    : f'Actual finish ({act.act_finish}) is after data date ({data_date_str})',
                })

            # (b) Scheduled start is in the past but no actual start recorded
            if start and start < data_date and not act_start:
                violations.append({
                    'task_code': act.task_code,
                    'task_name': act.task_name,
                    'issue'    : f'Scheduled start ({act.start[:10]}) is before data date but no actual start recorded',
                })

            # (b2) Task has started but scheduled finish is past data date with no actual finish
            if act_start and finish and finish < data_date and not act_finish:
                violations.append({
                    'task_code': act.task_code,
                    'task_name': act.task_name,
                    'issue'    : f'Scheduled finish ({act.finish[:10] if act.finish else "?"}) is before data date but task is still in progress (no actual finish)',
                })

    total      = len(incomplete)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #9 - Invalid/Missing Dates',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}%',
        'details'    : violations,
    }
