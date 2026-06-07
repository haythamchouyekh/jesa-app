# metrics/relationship_types.py
# Metric #4: Relationship Types
#
# DCMA SPEC:
#   Primary measure: % of relationships that are Finish-to-Start (FS)
#   TARGET: 90% or more should be FS relationships
#   SF relationships are always flagged (0% tolerance)
#
# FIX vs original:
#   - Primary check is now FS% >= 90 (not SF-only)
#   - SF is still flagged individually (always a violation)
#   - SS/FF reported as informational detail
#   - Denominator = relationships on incomplete tasks per spec

FS_MIN_PCT  = 90   # DCMA: at least 90% must be FS
SF_MAX_PCT  = 0    # DCMA: 0% SF allowed


def check_relationship_types(activities, relationships, fs_min_pct=None):
    fs_min = fs_min_pct if fs_min_pct is not None else FS_MIN_PCT
    incomplete_ids = {a.task_id for a in activities.values() if a.is_incomplete}

    # Only count relationships touching incomplete tasks
    rels = [r for r in relationships if r.succ_task_id in incomplete_ids]
    total = len(rels)

    fs_count   = 0
    sf_violations = []
    ss_list    = []
    ff_list    = []

    for rel in rels:
        pred = activities.get(rel.pred_task_id)
        succ = activities.get(rel.succ_task_id)
        pred_code = pred.task_code if pred else rel.pred_task_id
        succ_code = succ.task_code if succ else rel.succ_task_id
        rtype = rel.pred_type  # PR_FS / PR_SS / PR_FF / PR_SF

        pred_name = pred.task_name if pred else ''
        succ_name = succ.task_name if succ else ''

        p_label = pred_name if pred_name and pred_name != pred_code else pred_code
        s_label = succ_name if succ_name and succ_name != succ_code else succ_code

        if rtype == 'PR_FS':
            fs_count += 1

        elif rtype == 'PR_SF':
            sf_violations.append({
                'pred_code': pred_code, 'pred_name': pred_name,
                'succ_code': succ_code, 'succ_name': succ_name,
                'rel_type' : 'SF',
                'issue'    : f'Start-to-Finish (SF): {p_label} → {s_label}',
            })

        elif rtype == 'PR_SS':
            ss_list.append({
                'pred_code': pred_code, 'pred_name': pred_name,
                'succ_code': succ_code, 'succ_name': succ_name,
                'rel_type' : 'SS',
                'issue'    : f'Start-to-Start (SS): {p_label} → {s_label}',
            })

        elif rtype == 'PR_FF':
            ff_list.append({
                'pred_code': pred_code, 'pred_name': pred_name,
                'succ_code': succ_code, 'succ_name': succ_name,
                'rel_type' : 'FF',
                'issue'    : f'Finish-to-Finish (FF): {p_label} → {s_label}',
            })

    non_fs_count = len(sf_violations) + len(ss_list) + len(ff_list)
    fs_pct       = round((fs_count    / total) * 100, 1) if total > 0 else 0.0
    non_fs_pct   = round((non_fs_count / total) * 100, 1) if total > 0 else 0.0
    sf_pct       = round((len(sf_violations) / total) * 100, 1) if total > 0 else 0.0
    ssff_pct     = round(((len(ss_list) + len(ff_list)) / total) * 100, 1) if total > 0 else 0.0

    # PASS requires: FS% >= threshold AND SF% == 0
    # Vacuously true when there are no relationships to check
    passed = (total == 0) or ((fs_pct >= fs_min) and (len(sf_violations) == 0))

    # Violation list always includes all non-FS relationships for transparency
    all_violations = sf_violations + ss_list + ff_list

    return {
        'metric'     : 'Metric #4 - Relationship Types',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : non_fs_count,   # all non-FS relationships
        'percentage' : non_fs_pct,     # % of non-FS (so FAIL always shows > 0%)
        'threshold'  : f'≥{fs_min}% FS | 0% SF',
        'fs_count'   : fs_count,
        'fs_pct'     : fs_pct,
        'sf_count'   : len(sf_violations),
        'ss_count'   : len(ss_list),
        'ff_count'   : len(ff_list),
        'ssff_pct'   : ssff_pct,
        'details'    : all_violations,
    }
