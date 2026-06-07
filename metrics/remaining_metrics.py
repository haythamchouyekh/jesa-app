# metrics/remaining_metrics.py
# Metrics #11 – #14  (per DCMA 14-Point Schedule Assessment PDF)
#   11 — Missed Tasks
#   12 — Critical Path Test
#   13 — CPLI  (Critical Path Length Index)
#   14 — BEI   (Baseline Execution Index)

from collections import defaultdict
from datetime import datetime


# ── Date helper ─────────────────────────────────────────────────────────────
def _parse_date(d):
    if not d or str(d).strip() in ('', 'None', 'nan'):
        return None
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(d).strip()[:16], fmt)
        except ValueError:
            pass
    return None


def _working_days_between(start_dt, end_dt):
    """
    Approximate working-day count between two datetimes.
    Uses calendar days × (5/7) — good enough for CPLI ratio purposes.
    """
    if not start_dt or not end_dt or end_dt <= start_dt:
        return 0.0
    calendar_days = (end_dt - start_dt).total_seconds() / 86400
    return max(0.0, calendar_days * (5 / 7))


# ── Metric #11: Missed Tasks ─────────────────────────────────────────────────
# DCMA SPEC:
#   % = (# Incomplete Tasks with Baseline Finish ≤ Status Date)
#         / (# Total Incomplete Tasks) × 100
#   TARGET: should not exceed 5%
#
# A "missed" task is one that was planned to be complete by now
# (its Baseline Finish ≤ data date) but is still not finished.

MISSED_THRESHOLD_PCT = 5


def check_missed_tasks(activities, data_date_str=None, threshold_pct=None):
    thresh     = threshold_pct if threshold_pct is not None else MISSED_THRESHOLD_PCT
    incomplete = [a for a in activities.values() if a.is_incomplete and a.is_normal]
    total      = len(incomplete)

    if not data_date_str:
        return {
            'metric'    : 'Metric #11 - Missed Tasks',
            'status'    : 'PASS',
            'total'     : total,
            'violations': 0,
            'percentage': 0.0,
            'threshold' : f'Max {thresh}%',
            'details'   : [{'task_code': 'N/A', 'task_name': 'N/A',
                             'issue': 'No data date provided — metric could not be evaluated'}],
        }

    data_date = _parse_date(data_date_str)
    if not data_date:
        return {
            'metric'    : 'Metric #11 - Missed Tasks',
            'status'    : 'PASS',
            'total'     : total,
            'violations': 0,
            'percentage': 0.0,
            'threshold' : f'Max {thresh}%',
            'details'   : [{'task_code': 'N/A', 'task_name': 'N/A',
                             'issue': 'Invalid data date format — metric could not be evaluated'}],
        }

    violations = []
    for act in incomplete:
        bl_finish = _parse_date(act.bl_finish)
        if bl_finish and bl_finish <= data_date:
            violations.append({
                'task_code': act.task_code,
                'task_name': act.task_name,
                'issue'    : (f'Baseline finish {act.bl_finish} has passed '
                              f'but task is still incomplete'),
            })

    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0
    passed     = percentage <= thresh

    return {
        'metric'    : 'Metric #11 - Missed Tasks',
        'status'    : 'PASS' if passed else 'FAIL',
        'total'     : total,
        'violations': count,
        'percentage': percentage,
        'threshold' : f'Max {thresh}%',
        'details'   : violations,
    }


# ── Metric #12: Critical Path Test ──────────────────────────────────────────
# DCMA SPEC:
#   Add 600 days to remaining duration of a CP task; verify project finish
#   moves by the same amount. Target: Pass / Fail only.
#
# Approximation (no live CPM scheduler available):
#   Verify that the critical path forms a continuous connected chain from at
#   least one start-point to at least one end-point.  Disconnected CP segments
#   indicate broken logic — same root cause the DCMA test is designed to catch.

def check_critical_path_test(activities, relationships):
    # Identify critical path tasks: incomplete, non-summary (includes milestones),
    # total_float <= 0 (catches both zero-float and negative-float tasks).
    # WBS summaries and LOE are excluded — their float is derived from children.
    critical_ids = {
        a.task_id for a in activities.values()
        if a.is_incomplete and not a.is_summary and a.total_float <= 0
    }

    if not critical_ids:
        return {
            'metric'    : 'Metric #12 - Critical Path Test',
            'status'    : 'PASS',
            'total'     : len(activities),
            'violations': 0,
            'percentage': 0.0,
            'threshold' : 'Critical path must form a continuous chain (Pass / Fail)',
            'cp_count'  : 0,
            'details'   : [],
        }

    # Build undirected CP adjacency for connected-component detection.
    # Directed reachability is insufficient: a node with no CP predecessors would
    # always be its own "start", making disconnected islands appear reachable from
    # themselves.  Connected components catch all fragmentation correctly.
    cp_adj = defaultdict(set)
    for rel in relationships:
        if rel.pred_task_id in critical_ids and rel.succ_task_id in critical_ids:
            cp_adj[rel.pred_task_id].add(rel.succ_task_id)
            cp_adj[rel.succ_task_id].add(rel.pred_task_id)

    # Find connected components (undirected DFS)
    remaining_nodes = set(critical_ids)
    components = []
    while remaining_nodes:
        start = next(iter(remaining_nodes))
        component = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node not in component:
                component.add(node)
                stack.extend(cp_adj[node] - component)
        components.append(component)
        remaining_nodes -= component

    # Tasks not in the largest component are disconnected from the main CP chain
    if len(components) <= 1:
        isolated = set()
    else:
        main_component = max(components, key=len)
        isolated = critical_ids - main_component

    passed = len(isolated) == 0

    violations = []
    if not passed:
        for tid in isolated:
            act = activities.get(tid)
            violations.append({
                'task_code': act.task_code if act else tid,
                'task_name': act.task_name if act else '',
                'issue'    : 'Critical path task is disconnected from the main CP chain',
            })

    return {
        'metric'    : 'Metric #12 - Critical Path Test',
        'status'    : 'PASS' if passed else 'FAIL',
        'total'     : len(activities),
        'violations': len(violations),
        'percentage': 0.0,
        'threshold' : 'Critical path must form a continuous chain (Pass / Fail)',
        'cp_count'  : len(critical_ids),
        'details'   : violations,
    }


# ── Metric #13: CPLI (Critical Path Length Index) ───────────────────────────
# DCMA FORMULA:
#   CPLI = (CPL + TF) / CPL
#     CPL = working days from Status Date to Baseline Finish of the completion
#           milestone (end of the critical path)
#     TF  = total float (working days) on that completion milestone
#   TARGET: CPLI ≥ 0.95

CPLI_THRESHOLD = 0.95
HOURS_PER_DAY  = 8


def check_critical_path(activities, data_date_str=None, cpli_threshold=None, hours_per_day=8):
    cpli_thresh = cpli_threshold if cpli_threshold is not None else CPLI_THRESHOLD
    hpd         = hours_per_day if hours_per_day and hours_per_day > 0 else HOURS_PER_DAY
    # Include milestones (TT_Mile / TT_FinMile) — the project-end milestone is
    # typically the canonical end of the critical path.
    # Exclude WBS summaries and LOE whose float is derived from children.
    critical = [
        a for a in activities.values()
        if a.is_incomplete and not a.is_summary and a.total_float <= 0
    ]

    if not critical:
        return {
            'metric'    : 'Metric #13 - CPLI (Critical Path Length Index)',
            'status'    : 'PASS',
            'total'     : len(activities),
            'violations': 0,
            'percentage': 0.0,
            'threshold' : f'CPLI >= {cpli_thresh}',
            'cpli_value': 1.0,
            'cp_count'  : 0,
            'details'   : [],
        }

    data_date = _parse_date(data_date_str)

    def _finish_dt(act):
        return _parse_date(act.bl_finish) or _parse_date(act.finish)

    end_activity = max(critical, key=lambda a: _finish_dt(a) or datetime.min)
    end_finish   = _finish_dt(end_activity)

    if data_date and end_finish and end_finish > data_date:
        CPL = _working_days_between(data_date, end_finish)
    else:
        CPL = sum(a.remaining_dur for a in critical) / hpd

    TF   = end_activity.total_float / hpd
    CPLI = round((CPL + TF) / CPL, 3) if CPL > 0 else 0.0

    passed = CPLI >= cpli_thresh
    violations = []
    if not passed:
        violations.append({
            'task_code': 'SCHEDULE',
            'task_name': 'Critical Path',
            'issue'    : (f'CPLI = {CPLI} — below {cpli_thresh} threshold. '
                          f'CPL = {round(CPL, 1)} working days, '
                          f'TF = {round(TF, 1)} days on end activity {end_activity.task_name or end_activity.task_code}. '
                          f'{len(critical)} activities on critical path.'),
        })

    return {
        'metric'    : 'Metric #13 - CPLI (Critical Path Length Index)',
        'status'    : 'PASS' if passed else 'FAIL',
        'total'     : len(activities),
        'violations': len(violations),
        'percentage': round((len(critical) / len(activities)) * 100, 1),
        'threshold' : f'CPLI >= {cpli_thresh}',
        'cpli_value': CPLI,
        'cp_count'  : len(critical),
        'details'   : violations,
    }


# ── Metric #14: BEI (Baseline Execution Index) ───────────────────────────────
# DCMA SPEC:
#   BEI = # Completed Tasks / BEI Baseline Count
#   BEI Baseline Count = tasks with bl_finish <= data_date
#                        PLUS tasks missing baseline finish dates
#   TARGET: BEI >= 0.95
#
# "Completed Tasks" = ALL completed tasks from the total task list,
# NOT restricted to those in the baseline count group.

BEI_THRESHOLD = 0.95


def check_bei(activities, data_date_str=None, bei_threshold=None):
    bei_thresh = bei_threshold if bei_threshold is not None else BEI_THRESHOLD
    normal     = [a for a in activities.values() if a.is_normal]

    if data_date_str:
        data_date = _parse_date(data_date_str)
        if data_date:
            # Baseline Count = tasks planned to be done by data_date
            planned    = [a for a in normal
                          if _parse_date(a.bl_finish) and
                          _parse_date(a.bl_finish) <= data_date]
            # Tasks missing baseline finish are included in denominator per spec
            missing_bl = [a for a in normal if not _parse_date(a.bl_finish)]

            bei_baseline_count = len(planned) + len(missing_bl)

            # Completed Tasks = ALL tasks actually completed (not just those in planned)
            all_completed = [a for a in normal if a.is_complete]
            done          = len(all_completed)

            BEI    = round(done / bei_baseline_count, 3) if bei_baseline_count > 0 else 1.0
            passed = BEI >= bei_thresh

            # Violations = planned tasks that are NOT yet completed
            not_done = [a for a in planned if not a.is_complete]
            violations = [{
                'task_code': a.task_code,
                'task_name': a.task_name,
                'issue'    : (f'Planned to finish by {data_date_str} '
                              f'(bl_finish: {a.bl_finish}) but not completed'),
            } for a in not_done]

            return {
                'metric'    : 'Metric #14 - BEI (Baseline Execution Index)',
                'status'    : 'PASS' if passed else 'FAIL',
                'total'     : bei_baseline_count,
                'violations': len(not_done),
                'percentage': round((done / bei_baseline_count) * 100, 1) if bei_baseline_count > 0 else 0.0,
                'threshold' : f'BEI >= {bei_thresh}',
                'bei_value' : BEI,
                'details'   : violations,
            }

    # Fallback when no data date: compute ratio of completed vs total tasks
    all_completed = [a for a in normal if a.is_complete]
    total         = len(normal)
    done          = len(all_completed)
    BEI           = round(done / total, 3) if total > 0 else 1.0
    passed        = BEI >= bei_thresh

    return {
        'metric'    : 'Metric #14 - BEI (Baseline Execution Index)',
        'status'    : 'PASS' if passed else 'FAIL',
        'total'     : total,
        'violations': 0,
        'percentage': round((done / total) * 100, 1) if total > 0 else 0.0,
        'threshold' : f'BEI >= {bei_thresh} (no data date — using overall completion rate)',
        'bei_value' : BEI,
        'details'   : [{'task_code': 'N/A', 'task_name': 'N/A',
                         'issue': 'No data date provided — BEI estimated from overall task completion rate'}],
    }
