# metrics/lags.py
# Metric #3: Lags (Positive Lags)
#
# DCMA SPEC:
#   % = (relationships with positive lag on incomplete tasks)
#         / (total relationships on incomplete tasks) × 100
#   TARGET: should not exceed 5%

THRESHOLD_PCT = 5   # DCMA: max 5 %


def check_lags(activities, relationships, threshold_pct=None, hours_per_day=8):
    thresh = threshold_pct if threshold_pct is not None else THRESHOLD_PCT
    hpd    = hours_per_day if hours_per_day and hours_per_day > 0 else 8
    incomplete_ids = {a.task_id for a in activities.values() if a.is_incomplete}
    violations = []

    for rel in relationships:
        if rel.succ_task_id not in incomplete_ids:
            continue
        if rel.lag > 0:
            pred = activities.get(rel.pred_task_id)
            succ = activities.get(rel.succ_task_id)
            pred_code  = pred.task_code if pred else rel.pred_task_id
            succ_code  = succ.task_code if succ else rel.succ_task_id
            pred_label = (pred.task_name or pred_code) if pred else pred_code
            succ_label = (succ.task_name or succ_code) if succ else succ_code
            lag_days   = round(rel.lag / hpd, 1)
            violations.append({
                'pred_code': pred_code,
                'pred_name': pred.task_name if pred else 'Unknown',
                'succ_code': succ_code,
                'succ_name': succ.task_name if succ else 'Unknown',
                'lag'      : rel.lag,
                'lag_days' : lag_days,
                'rel_type' : rel.pred_type,
                'issue'    : (f'Positive lag of {rel.lag}h '
                              f'({lag_days} days) '
                              f'on {pred_label} → {succ_label}'),
            })

    rels_on_incomplete = [r for r in relationships
                          if r.succ_task_id in incomplete_ids]
    total      = len(rels_on_incomplete)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #3 - Lags (Positive Lags)',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}%',
        'details'    : violations,
    }
