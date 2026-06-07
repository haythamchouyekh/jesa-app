# metrics/leads.py
# Metric #2: Leads (Negative Lags)
#
# DCMA SPEC:
#   % = (relationships with negative lag on incomplete tasks)
#         / (total relationships) × 100
#   TARGET: 0%  — no leads allowed in the schedule
#
# Leads distort the critical path and are forbidden.

def check_leads(activities, relationships, threshold_pct=None):
    thresh = threshold_pct if threshold_pct is not None else 0
    # Denominator = relationships whose successor is any incomplete task
    # (consistent with Metrics #3 and #4 — DCMA spec does not exclude milestones)
    incomplete_ids  = {a.task_id for a in activities.values() if a.is_incomplete}
    incomplete_rels = [r for r in relationships if r.succ_task_id in incomplete_ids]
    violations = []

    for rel in incomplete_rels:
        if rel.lag < 0:
            pred = activities.get(rel.pred_task_id)
            succ = activities.get(rel.succ_task_id)
            violations.append({
                'pred_code': pred.task_code if pred else rel.pred_task_id,
                'pred_name': pred.task_name if pred else 'Unknown',
                'succ_code': succ.task_code if succ else rel.succ_task_id,
                'succ_name': succ.task_name if succ else 'Unknown',
                'lag'      : rel.lag,
                'rel_type' : rel.pred_type,
                'issue'    : (f'Negative lag of {rel.lag}h between '
                              f'{(pred.task_name or pred.task_code) if pred else rel.pred_task_id} → '
                              f'{(succ.task_name or succ.task_code) if succ else rel.succ_task_id}'),
            })

    total_rels = len(incomplete_rels)
    count      = len(violations)
    percentage = round((count / total_rels) * 100, 1) if total_rels > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #2 - Leads (Negative Lags)',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total_rels,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}%',
        'details'    : violations,
    }
