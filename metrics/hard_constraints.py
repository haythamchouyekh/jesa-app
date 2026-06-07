# metrics/hard_constraints.py
# Metric #5: Hard Constraints
#
# DCMA SPEC:
#   Hard constraint types (Primavera P6 equivalents):
#     CS_MSO  = Must Start On
#     CS_MFO  = Must Finish On
#     CS_SNLT = Start No Later Than
#     CS_FNLT = Finish No Later Than
#   % = (incomplete tasks with hard constraint)
#         / (total incomplete tasks) × 100
#   TARGET: should not exceed 5%
#
# FIX vs original:
#   - Removed CS_ALAP, CS_FNET, CS_SNET — these are NOT DCMA hard constraints
#   - Denominator is now INCOMPLETE tasks only (not all tasks)
#   - Threshold unchanged at 5%

# Official DCMA hard constraint codes in Primavera P6
HARD_CONSTRAINTS = {'CS_MSO', 'CS_MFO', 'CS_SNLT', 'CS_FNLT'}
THRESHOLD_PCT    = 5   # DCMA: max 5 %


def check_hard_constraints(activities, threshold_pct=None):
    thresh = threshold_pct if threshold_pct is not None else THRESHOLD_PCT
    # PDF spec: "lowest-level tasks" — excludes WBS summaries and LOE.
    # Milestones can legitimately carry hard constraints so are kept.
    incomplete = [a for a in activities.values()
                  if a.is_incomplete and a.task_type not in ('TT_WBS', 'TT_LOE')]
    violations = []

    for act in incomplete:
        c1 = (act.constraint  or '').strip()
        c2 = (act.constraint2 or '').strip()
        hit = None

        if c1 in HARD_CONSTRAINTS:
            hit = c1
        elif c2 in HARD_CONSTRAINTS:
            hit = c2

        if hit:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : f'Hard constraint: {hit} '
                             f'(date: {act.constraint_date or act.constraint2_date or "N/A"})',
            })

    total      = len(incomplete)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'     : 'Metric #5 - Hard Constraints',
        'status'     : 'PASS' if passed else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : f'Max {thresh}%',
        'details'    : violations,
    }
