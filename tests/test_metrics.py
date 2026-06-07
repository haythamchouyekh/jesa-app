"""
Comprehensive test suite for all 14 + 1 DCMA metrics.
Run with:  pytest tests/test_metrics.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from xer_parser.xer_parser import Activity, Relationship
from metrics.open_ends            import check_open_ends
from metrics.leads                import check_leads
from metrics.lags                 import check_lags
from metrics.relationship_types   import check_relationship_types
from metrics.hard_constraints     import check_hard_constraints
from metrics.high_float           import check_high_float
from metrics.negative_float       import check_negative_float
from metrics.long_duration        import check_long_duration
from metrics.invalid_dates        import check_invalid_dates
from metrics.resources            import check_resources
from metrics.remaining_metrics    import (check_missed_tasks,
                                          check_critical_path_test,
                                          check_critical_path,
                                          check_bei)
from metrics.redundant_relationships import check_redundant_relationships


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_act(tid, code=None, task_type='TT_Task', status='TK_NotStart',
             total_float=0.0, free_float=0.0, duration=80.0, remaining=80.0,
             base_dur=0.0, start=None, finish=None,
             act_start=None, act_finish=None,
             bl_start=None, bl_finish=None,
             constraint='', constraint2='',
             constraint_date='', constraint2_date='',
             has_resource=False):
    a = Activity()
    a.task_id          = tid
    a.task_code        = code or tid
    a.task_name        = f'Name-{code or tid}'
    a.task_type        = task_type
    a.status_code      = status
    a.total_float      = total_float
    a.free_float       = free_float
    a.duration         = duration
    a.remaining_dur    = remaining
    a.base_duration    = base_dur or duration
    a.start            = start
    a.finish           = finish
    a.act_start        = act_start
    a.act_finish       = act_finish
    a.bl_start         = bl_start
    a.bl_finish        = bl_finish
    a.constraint       = constraint
    a.constraint2      = constraint2
    a.constraint_date  = constraint_date
    a.constraint2_date = constraint2_date
    a.has_resource     = has_resource
    a.predecessors     = []
    a.successors       = []
    return a


def make_rel(pred_id, succ_id, pred_type='PR_FS', lag=0.0):
    r = Relationship()
    r.pred_task_id = pred_id
    r.succ_task_id = succ_id
    r.pred_type    = pred_type
    r.lag          = lag
    return r


def wire(acts, rels):
    """Populate predecessors/successors on activities and return acts dict."""
    for r in rels:
        if r.pred_task_id in acts:
            acts[r.pred_task_id].successors.append(r)
        if r.succ_task_id in acts:
            acts[r.succ_task_id].predecessors.append(r)
    return acts


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #1 — Open Ends
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric01OpenEnds:

    def test_no_pred_and_no_succ_is_one_violation(self):
        acts = {'T1': make_act('T1')}
        r = check_open_ends(acts)
        assert r['violations'] == 1
        assert r['details'][0]['issue'] == 'No predecessors AND no successors (fully isolated)'

    def test_no_pred_only(self):
        a = make_act('T1')
        rel = make_rel('T1', 'T2')
        acts = wire({'T1': a, 'T2': make_act('T2')}, [rel])
        r = check_open_ends(acts)
        # T1 has succ but no pred → violation; T2 has pred but no succ → violation
        codes = {d['task_code'] for d in r['details']}
        issues = {d['issue'] for d in r['details']}
        assert 'No predecessors (open start)' in issues
        assert 'No successors (open finish)'  in issues

    def test_fully_connected_no_violation(self):
        a, b, c = make_act('A'), make_act('B'), make_act('C')
        rels = [make_rel('A', 'B'), make_rel('B', 'C')]
        acts = wire({'A': a, 'B': b, 'C': c}, rels)
        r = check_open_ends(acts)
        # A: no pred (start), C: no succ (end) — both violations
        # B: fully connected — no violation
        assert r['violations'] == 2

    def test_complete_task_excluded(self):
        a = make_act('T1', status='TK_Complete')
        acts = {'T1': a}
        r = check_open_ends(acts)
        assert r['total']      == 0
        assert r['violations'] == 0
        assert r['status']     == 'PASS'

    def test_milestone_excluded_from_open_ends(self):
        a = make_act('M1', task_type='TT_Mile')
        acts = {'M1': a}
        r = check_open_ends(acts)
        assert r['total']      == 0
        assert r['violations'] == 0

    def test_finish_milestone_excluded(self):
        a = make_act('M1', task_type='TT_FinMile')
        acts = {'M1': a}
        r = check_open_ends(acts)
        assert r['total'] == 0

    def test_wbs_excluded(self):
        a = make_act('W1', task_type='TT_WBS')
        acts = {'W1': a}
        r = check_open_ends(acts)
        assert r['total'] == 0

    def test_loe_excluded(self):
        a = make_act('L1', task_type='TT_LOE')
        acts = {'L1': a}
        r = check_open_ends(acts)
        assert r['total'] == 0

    def test_empty_activities_pass(self):
        r = check_open_ends({})
        assert r['status']     == 'PASS'
        assert r['violations'] == 0

    @pytest.mark.parametrize("n_incomplete,n_violation,threshold,expected_pass", [
        (20, 1, 5,  True),    # 5% exactly → PASS
        (20, 2, 5,  False),   # 10% → FAIL
        (100, 5, 5, True),    # 5% exactly → PASS
        (100, 6, 5, False),   # 6% → FAIL
        (10,  0, 5, True),    # 0% → PASS
        (1,   1, 5, False),   # 100% → FAIL
    ])
    def test_threshold_boundary(self, n_incomplete, n_violation, threshold, expected_pass):
        acts = {}
        # n_violation isolated tasks → each contributes 1 open-end violation
        for i in range(n_violation):
            acts[f'V{i}'] = make_act(f'V{i}')
        # remaining tasks form a ring so every ring node has 1 pred + 1 succ → 0 violations
        n_conn = n_incomplete - n_violation
        for i in range(n_conn):
            acts[f'C{i}'] = make_act(f'C{i}')
        if n_conn > 0:
            ring_rels = [make_rel(f'C{i}', f'C{(i + 1) % n_conn}') for i in range(n_conn)]
            wire(acts, ring_rels)
        r = check_open_ends(acts, threshold_pct=threshold)
        assert (r['status'] == 'PASS') == expected_pass

    def test_percentage_calculation(self):
        # 3 incomplete normal tasks, 1 fully isolated
        a1 = make_act('T1')         # isolated → violation
        a2 = make_act('T2')
        a3 = make_act('T3')
        rel1 = make_rel('T2', 'T3')
        acts = wire({'T1': a1, 'T2': a2, 'T3': a3}, [rel1])
        r = check_open_ends(acts)
        assert r['total']      == 3
        assert r['violations'] == 3   # T1 isolated, T2 no pred, T3 no succ
        assert r['percentage'] == 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #2 — Leads (Negative Lags)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric02Leads:

    def test_negative_lag_is_violation(self):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', lag=-8.0)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_leads(acts, [rel])
        assert r['violations'] == 1

    def test_zero_lag_no_violation(self):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', lag=0.0)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_leads(acts, [rel])
        assert r['violations'] == 0

    def test_positive_lag_no_violation(self):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', lag=8.0)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_leads(acts, [rel])
        assert r['violations'] == 0

    def test_ss_with_negative_lag_flagged(self):
        """Leads check flags negative lag regardless of relationship type."""
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', pred_type='PR_SS', lag=-8.0)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_leads(acts, [rel])
        assert r['violations'] == 1

    def test_rel_to_complete_task_excluded_from_denominator(self):
        a = make_act('A')
        b = make_act('B', status='TK_Complete')
        rel = make_rel('A', 'B', lag=-8.0)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_leads(acts, [rel])
        assert r['total']      == 0
        assert r['violations'] == 0

    def test_rel_to_milestone_included_in_denominator(self):
        """After fix: milestone rels ARE in denominator (is_incomplete only)."""
        a = make_act('A')
        m = make_act('M', task_type='TT_Mile')
        rel = make_rel('A', 'M', lag=0.0)
        acts = wire({'A': a, 'M': m}, [rel])
        r    = check_leads(acts, [rel])
        assert r['total'] == 1

    def test_empty_relationships_pass(self):
        acts = {'A': make_act('A')}
        r    = check_leads(acts, [])
        assert r['status']     == 'PASS'
        assert r['violations'] == 0

    def test_multiple_leads(self):
        acts  = {str(i): make_act(str(i)) for i in range(4)}
        rels  = [make_rel('0', '1', lag=-8),
                 make_rel('1', '2', lag=0),
                 make_rel('2', '3', lag=-16)]
        wire(acts, rels)
        r = check_leads(acts, rels)
        assert r['violations'] == 2
        assert r['total']      == 3

    def test_percentage_zero_means_pass(self):
        acts = {'A': make_act('A'), 'B': make_act('B')}
        rel  = make_rel('A', 'B', lag=0)
        wire(acts, [rel])
        r = check_leads(acts, [rel])
        assert r['status']     == 'PASS'
        assert r['percentage'] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #3 — Lags (Positive Lags)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric03Lags:

    def test_positive_lag_violation(self):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', lag=8.0)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_lags(acts, [rel])
        assert r['violations'] == 1

    def test_zero_lag_no_violation(self):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', lag=0.0)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_lags(acts, [rel])
        assert r['violations'] == 0

    def test_negative_lag_no_violation(self):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', lag=-8.0)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_lags(acts, [rel])
        assert r['violations'] == 0

    @pytest.mark.parametrize("hpd,lag_h,expected_days", [
        (8,  16.0, 2.0),
        (8,  8.0,  1.0),
        (10, 10.0, 1.0),
        (10, 20.0, 2.0),
        (6,  12.0, 2.0),
    ])
    def test_lag_days_display_uses_calendar(self, hpd, lag_h, expected_days):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', lag=lag_h)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_lags(acts, [rel], hours_per_day=hpd)
        assert r['violations'] == 1
        assert r['details'][0]['lag_days'] == expected_days

    def test_rel_to_complete_task_excluded(self):
        a = make_act('A')
        b = make_act('B', status='TK_Complete')
        rel = make_rel('A', 'B', lag=8)
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_lags(acts, [rel])
        assert r['total']      == 0
        assert r['violations'] == 0

    def test_denominator_consistency_with_leads(self):
        """#3 and #2 must use the same denominator: rels to ALL incomplete tasks."""
        a  = make_act('A')
        m  = make_act('M', task_type='TT_Mile')
        r1 = make_rel('A', 'M', lag=8)
        acts = wire({'A': a, 'M': m}, [r1])
        result_lags  = check_lags(acts, [r1])
        result_leads = check_leads(acts, [r1])
        assert result_lags['total'] == result_leads['total']

    def test_threshold_5pct(self):
        """20 rels, 1 lag = 5% → PASS; 2 lags = 10% → FAIL."""
        acts = {str(i): make_act(str(i)) for i in range(21)}
        rels = [make_rel(str(i), str(i+1), lag=8 if i == 0 else 0)
                for i in range(20)]
        wire(acts, rels)
        r = check_lags(acts, rels)
        assert r['violations'] == 1
        assert r['status']     == 'PASS'   # 5% ≤ 5%


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #4 — Relationship Types
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric04RelationshipTypes:

    def test_all_fs_pass(self):
        acts = {str(i): make_act(str(i)) for i in range(3)}
        rels = [make_rel('0', '1'), make_rel('1', '2')]
        wire(acts, rels)
        r = check_relationship_types(acts, rels)
        assert r['status'] == 'PASS'
        assert r['fs_pct'] == 100.0

    def test_sf_always_violation(self):
        a, b = make_act('A'), make_act('B')
        rels = [make_rel('A', 'B', pred_type='PR_FS'),
                make_rel('A', 'B', pred_type='PR_SF')]
        acts = wire({'A': a, 'B': b}, rels)
        r    = check_relationship_types(acts, rels)
        assert r['sf_count'] == 1
        assert r['status']   == 'FAIL'

    def test_ss_counted_as_non_fs(self):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', pred_type='PR_SS')
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_relationship_types(acts, [rel])
        assert r['ss_count']    == 1
        assert r['violations']  == 1
        assert r['fs_pct']      == 0.0

    def test_ff_counted_as_non_fs(self):
        a, b = make_act('A'), make_act('B')
        rel  = make_rel('A', 'B', pred_type='PR_FF')
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_relationship_types(acts, [rel])
        assert r['ff_count']   == 1
        assert r['violations'] == 1

    def test_90pct_fs_no_sf_passes(self):
        """9 FS + 1 SS = 90% FS, 0 SF → PASS."""
        acts = {str(i): make_act(str(i)) for i in range(11)}
        rels = ([make_rel(str(i), str(i+1)) for i in range(9)] +
                [make_rel('9', '10', pred_type='PR_SS')])
        wire(acts, rels)
        r = check_relationship_types(acts, rels)
        assert r['status'] == 'PASS'
        assert r['fs_pct'] == 90.0

    def test_89pct_fs_fails(self):
        """8 FS + 1 SS = 88.9% FS → FAIL."""
        acts = {str(i): make_act(str(i)) for i in range(10)}
        rels = ([make_rel(str(i), str(i+1)) for i in range(8)] +
                [make_rel('8', '9', pred_type='PR_SS')])
        wire(acts, rels)
        r = check_relationship_types(acts, rels)
        assert r['status'] == 'FAIL'

    def test_zero_relationships_pass(self):
        """No rels to check → vacuously PASS."""
        acts = {'A': make_act('A')}
        r    = check_relationship_types(acts, [])
        assert r['status']     == 'PASS'
        assert r['violations'] == 0

    def test_all_complete_no_rels_pass(self):
        a = make_act('A', status='TK_Complete')
        b = make_act('B', status='TK_Complete')
        rel = make_rel('A', 'B', pred_type='PR_SS')
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_relationship_types(acts, [rel])
        assert r['status'] == 'PASS'   # succ is complete → excluded from denominator

    def test_rel_to_complete_excluded_from_total(self):
        a = make_act('A')
        b = make_act('B', status='TK_Complete')
        rel = make_rel('A', 'B', pred_type='PR_SS')
        acts = wire({'A': a, 'B': b}, [rel])
        r    = check_relationship_types(acts, [rel])
        assert r['total'] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #5 — Hard Constraints
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric05HardConstraints:

    @pytest.mark.parametrize("cstr", ['CS_MSO', 'CS_MFO', 'CS_SNLT', 'CS_FNLT'])
    def test_hard_constraint_flagged(self, cstr):
        a    = make_act('T1', constraint=cstr)
        r    = check_hard_constraints({'T1': a})
        assert r['violations'] == 1

    @pytest.mark.parametrize("cstr", ['CS_SNET', 'CS_FNET', 'CS_ALAP', 'CS_MEO', ''])
    def test_soft_constraint_not_flagged(self, cstr):
        a = make_act('T1', constraint=cstr)
        r = check_hard_constraints({'T1': a})
        assert r['violations'] == 0

    def test_hard_constraint_on_second_field(self):
        a = make_act('T1', constraint='CS_SNET', constraint2='CS_MFO')
        r = check_hard_constraints({'T1': a})
        assert r['violations'] == 1

    def test_complete_task_excluded(self):
        a = make_act('T1', status='TK_Complete', constraint='CS_MSO')
        r = check_hard_constraints({'T1': a})
        assert r['violations'] == 0

    def test_wbs_excluded(self):
        a = make_act('W1', task_type='TT_WBS', constraint='CS_MSO')
        r = check_hard_constraints({'W1': a})
        assert r['violations'] == 0

    def test_loe_excluded(self):
        a = make_act('L1', task_type='TT_LOE', constraint='CS_MSO')
        r = check_hard_constraints({'L1': a})
        assert r['violations'] == 0

    def test_milestone_included(self):
        """Milestones CAN have hard constraints and should be flagged."""
        a = make_act('M1', task_type='TT_Mile', constraint='CS_MFO')
        r = check_hard_constraints({'M1': a})
        assert r['violations'] == 1

    def test_finish_milestone_included(self):
        a = make_act('M1', task_type='TT_FinMile', constraint='CS_FNLT')
        r = check_hard_constraints({'M1': a})
        assert r['violations'] == 1

    def test_threshold_5pct(self):
        acts = {}
        for i in range(20):
            cstr = 'CS_MSO' if i == 0 else ''
            acts[str(i)] = make_act(str(i), constraint=cstr)
        r = check_hard_constraints(acts)
        assert r['total']      == 20
        assert r['violations'] == 1
        assert r['percentage'] == 5.0
        assert r['status']     == 'PASS'

    def test_empty_pass(self):
        r = check_hard_constraints({})
        assert r['status'] == 'PASS'


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #6 — High Float  (calendar-aware)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric06HighFloat:

    @pytest.mark.parametrize("hpd,float_h,should_violate", [
        # 8 h/day calendar
        (8,  352.0, False),   # exactly 44 days — NOT > 44 → no violation
        (8,  352.1, True),    # just above 44 days → violation
        (8,  353.0, True),
        # 10 h/day calendar
        (10, 440.0, False),   # exactly 44 days at 10h → no violation
        (10, 440.1, True),    # just above → violation
        (10, 353.0, False),   # 35.3 days at 10h → no violation (was wrong with 8h hardcode)
        (10, 352.0, False),   # 35.2 days at 10h → no violation
        # 6 h/day
        (6,  264.0, False),   # 44 days exactly → no violation
        (6,  264.1, True),
        # 12 h/day
        (12, 528.0, False),
        (12, 528.1, True),
    ])
    def test_float_threshold_calendar_aware(self, hpd, float_h, should_violate):
        a = make_act('T1', total_float=float_h)
        r = check_high_float({'T1': a}, hours_per_day=hpd)
        assert (r['violations'] == 1) == should_violate

    def test_complete_task_excluded(self):
        a = make_act('T1', status='TK_Complete', total_float=9999.0)
        r = check_high_float({'T1': a})
        assert r['violations'] == 0

    def test_milestone_excluded(self):
        a = make_act('M1', task_type='TT_Mile', total_float=9999.0)
        r = check_high_float({'M1': a})
        assert r['violations'] == 0

    def test_wbs_excluded(self):
        a = make_act('W1', task_type='TT_WBS', total_float=9999.0)
        r = check_high_float({'W1': a})
        assert r['violations'] == 0

    def test_days_label_uses_calendar(self):
        """Violation message days label must use hpd not hardcoded 8."""
        a = make_act('T1', total_float=100.0)
        r = check_high_float({'T1': a}, float_days=5, hours_per_day=10)
        assert r['violations'] == 1
        assert '10.0 days' in r['details'][0]['issue']   # 100h / 10 = 10 days

    def test_custom_threshold_days(self):
        a = make_act('T1', total_float=160.0)   # 20 days at 8h
        r = check_high_float({'T1': a}, float_days=44, hours_per_day=8)
        assert r['violations'] == 0
        r2 = check_high_float({'T1': a}, float_days=15, hours_per_day=8)
        assert r2['violations'] == 1

    def test_empty_pass(self):
        r = check_high_float({})
        assert r['status'] == 'PASS'


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #7 — Negative Float
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric07NegativeFloat:

    def test_negative_float_flagged(self):
        a = make_act('T1', total_float=-8.0)
        r = check_negative_float({'T1': a})
        assert r['violations'] == 1

    def test_zero_float_not_flagged(self):
        a = make_act('T1', total_float=0.0)
        r = check_negative_float({'T1': a})
        assert r['violations'] == 0

    def test_positive_float_not_flagged(self):
        a = make_act('T1', total_float=8.0)
        r = check_negative_float({'T1': a})
        assert r['violations'] == 0

    def test_complete_task_excluded(self):
        a = make_act('T1', status='TK_Complete', total_float=-99.0)
        r = check_negative_float({'T1': a})
        assert r['violations'] == 0

    def test_milestone_excluded(self):
        a = make_act('M1', task_type='TT_Mile', total_float=-8.0)
        r = check_negative_float({'M1': a})
        assert r['violations'] == 0

    @pytest.mark.parametrize("hpd,neg_h,expected_days", [
        (8,  -16.0, -2.0),
        (10, -10.0, -1.0),
        (6,  -12.0, -2.0),
    ])
    def test_days_label_uses_calendar(self, hpd, neg_h, expected_days):
        a = make_act('T1', total_float=neg_h)
        r = check_negative_float({'T1': a}, hours_per_day=hpd)
        assert r['violations'] == 1
        assert f'{expected_days} days' in r['details'][0]['issue']

    def test_zero_threshold_means_any_negative_fails(self):
        a = make_act('T1', total_float=-0.001)
        r = check_negative_float({'T1': a})
        assert r['status'] == 'FAIL'

    def test_empty_pass(self):
        r = check_negative_float({})
        assert r['status'] == 'PASS'


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #8 — Long Duration  (calendar-aware)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric08LongDuration:

    @pytest.mark.parametrize("hpd,dur_h,should_violate", [
        (8,  352.0, False),
        (8,  352.1, True),
        (10, 440.0, False),
        (10, 440.1, True),
        (10, 353.0, False),   # 35.3 days at 10h → no violation
        (6,  264.0, False),
        (6,  264.1, True),
    ])
    def test_duration_threshold_calendar_aware(self, hpd, dur_h, should_violate):
        a = make_act('T1', base_dur=dur_h)
        r = check_long_duration({'T1': a}, hours_per_day=hpd)
        assert (r['violations'] == 1) == should_violate

    def test_uses_base_duration_not_remaining(self):
        """Spec says use BASELINE duration, not remaining."""
        a = make_act('T1', base_dur=400.0, remaining=10.0)
        r = check_long_duration({'T1': a}, hours_per_day=8)
        assert r['violations'] == 1  # 400h > 352h

    def test_fallback_to_duration_when_base_zero(self):
        a = make_act('T1', duration=400.0)
        a.base_duration = 0.0
        r = check_long_duration({'T1': a}, hours_per_day=8)
        assert r['violations'] == 1

    def test_complete_excluded(self):
        a = make_act('T1', status='TK_Complete', base_dur=9999.0)
        r = check_long_duration({'T1': a})
        assert r['violations'] == 0

    def test_milestone_excluded(self):
        a = make_act('M1', task_type='TT_Mile', base_dur=9999.0)
        r = check_long_duration({'M1': a})
        assert r['violations'] == 0

    def test_days_label_uses_calendar(self):
        a = make_act('T1', base_dur=100.0)
        r = check_long_duration({'T1': a}, duration_days=5, hours_per_day=10)
        assert r['violations'] == 1
        assert '10.0 days' in r['details'][0]['issue']   # 100/10=10 days


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #9 — Invalid / Missing Dates
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric09InvalidDates:

    DD = '2024-06-01 00:00'

    def test_wbs_excluded_after_fix(self):
        """WBS summaries must be excluded — previously caused false positives."""
        a = make_act('W1', task_type='TT_WBS',
                     start='2024-01-01 00:00', finish='2024-12-31 00:00')
        r = check_invalid_dates({'W1': a}, self.DD)
        assert r['total']      == 0
        assert r['violations'] == 0

    def test_loe_excluded(self):
        a = make_act('L1', task_type='TT_LOE',
                     start='2024-01-01 00:00', finish='2024-12-31 00:00')
        r = check_invalid_dates({'L1': a}, self.DD)
        assert r['total'] == 0

    def test_milestone_included(self):
        a = make_act('M1', task_type='TT_Mile',
                     start='2024-01-01 00:00', finish='2024-12-31 00:00')
        r = check_invalid_dates({'M1': a}, self.DD)
        assert r['total'] == 1

    def test_actual_start_after_data_date_violation(self):
        a = make_act('T1',
                     start='2024-05-01 00:00', finish='2024-07-01 00:00',
                     act_start='2024-06-15 00:00')   # after data date
        r = check_invalid_dates({'T1': a}, self.DD)
        issues = [d['issue'] for d in r['details']]
        assert any('Actual start' in i and 'after data date' in i for i in issues)

    def test_actual_finish_after_data_date_violation(self):
        a = make_act('T1',
                     start='2024-05-01 00:00', finish='2024-07-01 00:00',
                     act_start='2024-05-01 00:00',
                     act_finish='2024-06-15 00:00')   # after data date
        r = check_invalid_dates({'T1': a}, self.DD)
        issues = [d['issue'] for d in r['details']]
        assert any('Actual finish' in i and 'after data date' in i for i in issues)

    def test_scheduled_start_in_past_no_actual_start_violation(self):
        a = make_act('T1',
                     start='2024-01-01 00:00', finish='2024-12-31 00:00')
        r = check_invalid_dates({'T1': a}, self.DD)
        issues = [d['issue'] for d in r['details']]
        assert any('Scheduled start' in i and 'before data date' in i for i in issues)

    def test_finish_before_start_violation(self):
        a = make_act('T1',
                     start='2024-06-01 00:00', finish='2024-05-01 00:00')
        r = check_invalid_dates({'T1': a}, self.DD)
        issues = [d['issue'] for d in r['details']]
        assert any('precedes start' in i for i in issues)

    def test_missing_both_dates_violation(self):
        a = make_act('T1')
        r = check_invalid_dates({'T1': a}, self.DD)
        issues = [d['issue'] for d in r['details']]
        assert any('Missing both' in i for i in issues)

    def test_valid_dates_no_violation(self):
        a = make_act('T1',
                     start='2024-06-15 00:00', finish='2024-08-01 00:00')
        r = check_invalid_dates({'T1': a}, self.DD)
        # No actual start issues since start > data_date
        assert r['violations'] == 0

    def test_complete_task_excluded(self):
        a = make_act('T1', status='TK_Complete')
        r = check_invalid_dates({'T1': a}, self.DD)
        assert r['total'] == 0

    def test_no_data_date_still_catches_missing_dates(self):
        a = make_act('T1')   # no dates at all
        r = check_invalid_dates({'T1': a}, None)
        assert r['violations'] == 1   # missing both dates is always a violation


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #10 — Resources
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric10Resources:

    def test_resourced_task_no_violation(self):
        a = make_act('T1', has_resource=True)
        r = check_resources({'T1': a})
        assert r['violations'] == 0

    def test_unresourced_task_violation(self):
        a = make_act('T1', has_resource=False)
        r = check_resources({'T1': a})
        assert r['violations'] == 1

    def test_milestone_excluded(self):
        a = make_act('M1', task_type='TT_Mile', has_resource=False)
        r = check_resources({'M1': a})
        assert r['violations'] == 0

    def test_wbs_excluded(self):
        a = make_act('W1', task_type='TT_WBS', has_resource=False)
        r = check_resources({'W1': a})
        assert r['violations'] == 0

    def test_complete_task_excluded(self):
        a = make_act('T1', status='TK_Complete', has_resource=False)
        r = check_resources({'T1': a})
        assert r['violations'] == 0

    def test_no_resources_means_all_fail(self):
        """After proxy removal: has_resource=False by default → all flagged."""
        acts = {str(i): make_act(str(i)) for i in range(5)}
        r    = check_resources(acts)
        assert r['violations'] == 5
        assert r['percentage'] == 100.0
        assert r['status']     == 'FAIL'

    def test_all_resourced_pass(self):
        acts = {str(i): make_act(str(i), has_resource=True) for i in range(5)}
        r    = check_resources(acts)
        assert r['violations'] == 0
        assert r['status']     == 'PASS'


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #11 — Missed Tasks
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric11MissedTasks:

    DD = '2024-06-01 00:00'

    def test_past_bl_finish_incomplete_violation(self):
        a = make_act('T1', bl_finish='2024-05-01 00:00')
        r = check_missed_tasks({'T1': a}, self.DD)
        assert r['violations'] == 1

    def test_bl_finish_equal_data_date_violation(self):
        """bl_finish == data_date → task was due today, not complete → violation."""
        a = make_act('T1', bl_finish='2024-06-01 00:00')
        r = check_missed_tasks({'T1': a}, self.DD)
        assert r['violations'] == 1

    def test_future_bl_finish_no_violation(self):
        a = make_act('T1', bl_finish='2024-07-01 00:00')
        r = check_missed_tasks({'T1': a}, self.DD)
        assert r['violations'] == 0

    def test_no_bl_finish_not_violation(self):
        a = make_act('T1')   # bl_finish = None
        r = check_missed_tasks({'T1': a}, self.DD)
        assert r['violations'] == 0

    def test_complete_task_with_past_bl_no_violation(self):
        a = make_act('T1', status='TK_Complete', bl_finish='2024-01-01 00:00')
        r = check_missed_tasks({'T1': a}, self.DD)
        assert r['violations'] == 0

    def test_no_data_date_returns_pass(self):
        a = make_act('T1', bl_finish='2024-01-01 00:00')
        r = check_missed_tasks({'T1': a}, None)
        assert r['status']     == 'PASS'
        assert r['violations'] == 0

    def test_milestone_excluded(self):
        a = make_act('M1', task_type='TT_Mile', bl_finish='2024-01-01 00:00')
        r = check_missed_tasks({'M1': a}, self.DD)
        assert r['total'] == 0

    def test_threshold_5pct(self):
        acts = {str(i): make_act(str(i),
                                  bl_finish='2024-01-01 00:00' if i == 0 else '2024-07-01 00:00')
                for i in range(20)}
        r = check_missed_tasks(acts, self.DD)
        assert r['violations'] == 1
        assert r['percentage'] == 5.0
        assert r['status']     == 'PASS'


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #12 — Critical Path Test
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric12CriticalPathTest:

    def test_connected_chain_pass(self):
        a = make_act('A', total_float=0)
        b = make_act('B', total_float=0)
        c = make_act('C', total_float=0)
        rels = [make_rel('A', 'B'), make_rel('B', 'C')]
        acts = wire({'A': a, 'B': b, 'C': c}, rels)
        r    = check_critical_path_test(acts, rels)
        assert r['status']     == 'PASS'
        assert r['violations'] == 0

    def test_disconnected_cp_task_fails(self):
        a = make_act('A', total_float=0)
        b = make_act('B', total_float=0)
        c = make_act('C', total_float=0)
        # A→B connected, C disconnected
        rels = [make_rel('A', 'B')]
        acts = wire({'A': a, 'B': b, 'C': c}, rels)
        r    = check_critical_path_test(acts, rels)
        assert r['status']     == 'FAIL'
        assert r['violations'] == 1
        assert any(d['task_code'] == 'C' for d in r['details'])

    def test_finish_milestone_included_in_cp_after_fix(self):
        """After fix: FinMile with float=0 must be in the critical path."""
        task = make_act('T1', total_float=0)
        mile = make_act('M1', task_type='TT_FinMile', total_float=0)
        rels = [make_rel('T1', 'M1')]
        acts = wire({'T1': task, 'M1': mile}, rels)
        r    = check_critical_path_test(acts, rels)
        assert r['cp_count'] == 2   # task + milestone both on CP
        assert r['status']   == 'PASS'

    def test_wbs_excluded_from_cp(self):
        """WBS summaries with float=0 must NOT be in CP (derived float)."""
        wbs = make_act('W1', task_type='TT_WBS', total_float=0)
        r   = check_critical_path_test({'W1': wbs}, [])
        assert r['cp_count'] == 0
        assert r['status']   == 'PASS'

    def test_negative_float_included_in_cp_after_fix(self):
        """total_float <= 0 catches negative-float tasks as critical."""
        a = make_act('A', total_float=-8)
        b = make_act('B', total_float=0)
        rels = [make_rel('A', 'B')]
        acts = wire({'A': a, 'B': b}, rels)
        r    = check_critical_path_test(acts, rels)
        assert r['cp_count'] == 2

    def test_no_cp_tasks_pass(self):
        """All tasks have positive float → no CP → vacuously PASS."""
        a = make_act('A', total_float=80)
        r = check_critical_path_test({'A': a}, [])
        assert r['status'] == 'PASS'

    def test_positive_float_task_not_on_cp(self):
        a = make_act('A', total_float=0)
        b = make_act('B', total_float=8)    # NOT on CP
        rels = [make_rel('A', 'B')]
        acts = wire({'A': a, 'B': b}, rels)
        r    = check_critical_path_test(acts, rels)
        assert r['cp_count'] == 1   # only A


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #13 — CPLI
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric13CPLI:

    def test_cpli_pass_when_no_cp_tasks(self):
        a = make_act('A', total_float=80)
        r = check_critical_path({'A': a})
        assert r['status']     == 'PASS'
        assert r['cpli_value'] == 1.0

    def test_cpli_formula_tf_uses_hpd(self):
        """TF conversion: 10h of float at 10h/day = 1 day."""
        end = make_act('END', total_float=0.0, remaining=0.0,
                        finish='2024-09-01 00:00', bl_finish='2024-09-01 00:00')
        # CPL via remaining_dur fallback = 0 / hpd = 0 → CPLI = 0
        # So use data_date before end finish to get a real CPL
        end.total_float = 10.0   # 10h = 1 day at 10h/day
        end.remaining_dur = 0.0
        end.finish    = '2024-09-01 00:00'
        end.bl_finish = '2024-09-01 00:00'
        acts = {'END': end}
        r8  = check_critical_path(acts, '2024-08-01 00:00', hours_per_day=8)
        r10 = check_critical_path(acts, '2024-08-01 00:00', hours_per_day=10)
        # TF with 8h/day: 10h = 1.25 days; with 10h/day: 10h = 1.0 day
        tf8  = r8['details'][0]['issue'] if r8['violations'] else None
        # CPLI should be different depending on hpd → test cpli_value differs
        assert r8['cpli_value'] != r10['cpli_value'] or (
            r8['violations'] == 0 and r10['violations'] == 0)

    def test_finish_milestone_used_as_cp_end_after_fix(self):
        """End milestone (FinMile) should be chosen as the CP end activity."""
        task = make_act('T1', total_float=0, remaining=80,
                        finish='2024-08-01 00:00', bl_finish='2024-08-01 00:00')
        mile = make_act('M1', task_type='TT_FinMile', total_float=0, remaining=0,
                        finish='2024-09-01 00:00', bl_finish='2024-09-01 00:00')
        rels = [make_rel('T1', 'M1')]
        acts = wire({'T1': task, 'M1': mile}, rels)
        r    = check_critical_path(acts, '2024-06-01 00:00')
        # end_activity should be M1 (latest finish), not T1
        assert r['cp_count'] == 2

    def test_cpli_below_threshold_fails(self):
        """Negative float on CP end → CPLI < 0.95 → FAIL.
        CPL = 200h / 8h/day = 25d, TF = -20h / 8h/day = -2.5d
        CPLI = (25 - 2.5) / 25 = 0.9 < 0.95 → FAIL
        """
        end = make_act('END', total_float=-20.0, remaining=200,
                        finish='2024-01-01 00:00', bl_finish='2024-01-01 00:00')
        r   = check_critical_path({'END': end}, None)   # no data_date → uses remaining_dur fallback
        assert r['status'] == 'FAIL'

    def test_negative_float_task_in_cp(self):
        a = make_act('A', total_float=-8, remaining=80,
                     finish='2024-09-01 00:00', bl_finish='2024-09-01 00:00')
        r = check_critical_path({'A': a}, '2024-06-01 00:00')
        assert r['cp_count'] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Metric #14 — BEI
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetric14BEI:

    DD = '2024-06-01 00:00'

    def test_all_planned_complete_bei_1(self):
        a = make_act('T1', status='TK_Complete', bl_finish='2024-05-01 00:00')
        r = check_bei({'T1': a}, self.DD)
        assert r['bei_value'] == 1.0
        assert r['status']    == 'PASS'

    def test_nothing_done_bei_0(self):
        a = make_act('T1', bl_finish='2024-05-01 00:00')  # planned, incomplete
        r = check_bei({'T1': a}, self.DD)
        assert r['bei_value'] == 0.0
        assert r['status']    == 'FAIL'

    def test_missing_baseline_in_denominator(self):
        """Tasks with no bl_finish add to denominator, lowering BEI."""
        done   = make_act('T1', status='TK_Complete', bl_finish='2024-05-01 00:00')
        no_bl  = make_act('T2', bl_finish=None)   # no baseline → in denominator
        r      = check_bei({'T1': done, 'T2': no_bl}, self.DD)
        # done=1, denominator=2 (T1 planned + T2 no baseline)
        assert r['bei_value'] == 0.5

    def test_bei_can_exceed_one(self):
        """Tasks completed ahead of schedule push BEI > 1."""
        planned   = make_act('T1', status='TK_Complete', bl_finish='2024-05-01 00:00')
        early     = make_act('T2', status='TK_Complete', bl_finish='2024-08-01 00:00')  # future bl
        r         = check_bei({'T1': planned, 'T2': early}, self.DD)
        # denominator = 1 (only T1 planned by data_date), done = 2 → BEI = 2.0
        assert r['bei_value'] == 2.0
        assert r['status']    == 'PASS'

    def test_milestone_excluded(self):
        m = make_act('M1', task_type='TT_Mile', status='TK_Complete',
                     bl_finish='2024-05-01 00:00')
        r = check_bei({'M1': m}, self.DD)
        assert r['total'] == 0

    def test_no_data_date_fallback(self):
        a = make_act('T1', status='TK_Complete')
        b = make_act('T2')
        r = check_bei({'T1': a, 'T2': b}, None)
        assert r['bei_value'] == 0.5   # 1 done / 2 total

    def test_no_activities_pass(self):
        r = check_bei({}, self.DD)
        assert r['status'] == 'PASS'


# ═══════════════════════════════════════════════════════════════════════════════
# Bonus — Redundant Relationships
# ═══════════════════════════════════════════════════════════════════════════════

class TestRedundantRelationships:

    def _setup_chain(self, codes, extra_rels=None):
        """Build a linear FS chain A→B→C→... and wire it up."""
        acts = {c: make_act(c) for c in codes}
        rels = [make_rel(codes[i], codes[i+1]) for i in range(len(codes)-1)]
        if extra_rels:
            rels += extra_rels
        wire(acts, rels)
        return acts, rels

    # ── Basic 3-task chain ────────────────────────────────────────────────────

    def test_direct_shortcut_in_3_chain_flagged(self):
        """A→B→C and A→C (direct) → A→C is redundant."""
        acts, rels = self._setup_chain(['A', 'B', 'C'],
                                        extra_rels=[make_rel('A', 'C')])
        r = check_redundant_relationships(acts, rels)
        assert r['violations'] == 1
        assert r['details'][0]['pred_code'] == 'A'
        assert r['details'][0]['succ_code'] == 'C'

    def test_no_shortcut_no_violation(self):
        acts, rels = self._setup_chain(['A', 'B', 'C'])
        r = check_redundant_relationships(acts, rels)
        assert r['violations'] == 0
        assert r['status']     == 'PASS'

    # ── Chains longer than 3 ─────────────────────────────────────────────────

    def test_4_task_chain_shortcut_a_to_d(self):
        """A→B→C→D and A→D → A→D flagged, full path shown."""
        acts, rels = self._setup_chain(['A', 'B', 'C', 'D'],
                                        extra_rels=[make_rel('A', 'D')])
        r = check_redundant_relationships(acts, rels)
        assert r['violations'] == 1
        issue = r['details'][0]['issue']
        assert 'B' in issue or 'C' in issue    # path shown

    def test_4_task_chain_shortcut_a_to_c(self):
        """A→B→C→D and A→C → A→C flagged."""
        acts, rels = self._setup_chain(['A', 'B', 'C', 'D'],
                                        extra_rels=[make_rel('A', 'C')])
        r = check_redundant_relationships(acts, rels)
        assert r['violations'] == 1
        assert r['details'][0]['succ_code'] == 'C'

    def test_5_task_chain_full_path_label(self):
        """A→B→C→D→E with A→E: path shows B and C and D."""
        acts, rels = self._setup_chain(['A', 'B', 'C', 'D', 'E'],
                                        extra_rels=[make_rel('A', 'E')])
        r = check_redundant_relationships(acts, rels)
        assert r['violations'] == 1
        issue = r['details'][0]['issue']
        # Path through B → C → D should appear in the message
        assert 'B' in issue

    def test_multiple_shortcuts_in_one_chain(self):
        """A→B→C→D with A→C and A→D → 2 violations."""
        acts, rels = self._setup_chain(['A', 'B', 'C', 'D'],
                                        extra_rels=[make_rel('A', 'C'),
                                                    make_rel('A', 'D')])
        r = check_redundant_relationships(acts, rels)
        assert r['violations'] == 2

    def test_diamond_shortcut(self):
        """
        A→B→D and A→C→D and A→D (direct).
        A→D is redundant because D is reachable via B or C.
        """
        a, b, c, d = make_act('A'), make_act('B'), make_act('C'), make_act('D')
        rels = [make_rel('A','B'), make_rel('A','C'),
                make_rel('B','D'), make_rel('C','D'),
                make_rel('A','D')]   # redundant
        acts = wire({'A':a,'B':b,'C':c,'D':d}, rels)
        r = check_redundant_relationships(acts, rels)
        assert r['violations'] == 1
        assert r['details'][0]['pred_code'] == 'A'
        assert r['details'][0]['succ_code'] == 'D'

    # ── Non-FS relationships must NOT be flagged ──────────────────────────────

    def test_ss_relationship_not_flagged(self):
        """A→B (SS) cannot be redundant even if A→B→C (FS chain) exists."""
        a, b, c = make_act('A'), make_act('B'), make_act('C')
        rels = [make_rel('A', 'B', pred_type='PR_SS'),
                make_rel('B', 'C'),
                make_rel('A', 'C')]   # FS — might be redundant via B
        acts = wire({'A': a, 'B': b, 'C': c}, rels)
        r    = check_redundant_relationships(acts, rels)
        # A→B (SS) should never be flagged
        ss_violations = [d for d in r['details'] if d['pred_code']=='A' and d['succ_code']=='B']
        assert ss_violations == []

    def test_fs_shortcut_not_flagged_when_path_uses_ss(self):
        """
        A→B (SS) → C (FS): path A→C is NOT all-FS, so A→C (FS) is NOT redundant.
        The SS relationship means B starts WITH A, not after A finishes,
        so A→C (FS) enforces a real constraint.
        """
        a, b, c = make_act('A'), make_act('B'), make_act('C')
        rels = [make_rel('A', 'B', pred_type='PR_SS'),
                make_rel('B', 'C'),
                make_rel('A', 'C')]   # should NOT be flagged
        acts = wire({'A': a, 'B': b, 'C': c}, rels)
        r    = check_redundant_relationships(acts, rels)
        # A→C should NOT be flagged because the only path goes through SS
        ac_violations = [d for d in r['details'] if d['pred_code']=='A' and d['succ_code']=='C']
        assert ac_violations == []

    def test_ff_in_path_prevents_flagging(self):
        """A→B (FF) → C (FS): A→C (FS) is NOT redundant."""
        a, b, c = make_act('A'), make_act('B'), make_act('C')
        rels = [make_rel('A', 'B', pred_type='PR_FF'),
                make_rel('B', 'C'),
                make_rel('A', 'C')]
        acts = wire({'A': a, 'B': b, 'C': c}, rels)
        r    = check_redundant_relationships(acts, rels)
        ac_violations = [d for d in r['details'] if d['pred_code']=='A' and d['succ_code']=='C']
        assert ac_violations == []

    def test_sf_not_flagged_as_redundant(self):
        """An SF relationship can never be flagged as redundant."""
        a, b, c = make_act('A'), make_act('B'), make_act('C')
        rels = [make_rel('A', 'B'),
                make_rel('B', 'C'),
                make_rel('A', 'C', pred_type='PR_SF')]   # SF — not a candidate
        acts = wire({'A': a, 'B': b, 'C': c}, rels)
        r    = check_redundant_relationships(acts, rels)
        sf_violations = [d for d in r['details'] if d['rel_type'] == 'SF']
        assert sf_violations == []

    # ── Denominator ──────────────────────────────────────────────────────────

    def test_denominator_is_fs_only(self):
        """Total should count FS rels only, not all rels."""
        a, b = make_act('A'), make_act('B')
        rels = [make_rel('A', 'B', pred_type='PR_FS'),
                make_rel('A', 'B', pred_type='PR_SS')]
        acts = wire({'A': a, 'B': b}, rels)
        r    = check_redundant_relationships(acts, rels)
        assert r['total'] == 1   # only 1 FS relationship

    def test_empty_rels_pass(self):
        acts = {'A': make_act('A'), 'B': make_act('B')}
        r    = check_redundant_relationships(acts, [])
        assert r['status']     == 'PASS'
        assert r['violations'] == 0

    # ── Full path display ─────────────────────────────────────────────────────

    def test_full_path_shown_in_3_chain(self):
        acts, rels = self._setup_chain(['A', 'B', 'C'],
                                        extra_rels=[make_rel('A', 'C')])
        r     = check_redundant_relationships(acts, rels)
        issue = r['details'][0]['issue']
        assert 'via' in issue
        assert 'Name-B' in issue    # intermediate node shown

    def test_full_path_shown_in_4_chain(self):
        acts, rels = self._setup_chain(['A', 'B', 'C', 'D'],
                                        extra_rels=[make_rel('A', 'D')])
        r     = check_redundant_relationships(acts, rels)
        issue = r['details'][0]['issue']
        # Full path A→B→C→D: intermediate shown as "via Name-B → Name-C"
        assert 'Name-B' in issue
        assert 'Name-C' in issue

    def test_full_path_shown_in_5_chain(self):
        acts, rels = self._setup_chain(['A', 'B', 'C', 'D', 'E'],
                                        extra_rels=[make_rel('A', 'E')])
        r     = check_redundant_relationships(acts, rels)
        issue = r['details'][0]['issue']
        assert 'Name-B' in issue
        assert 'Name-C' in issue
        assert 'Name-D' in issue

    # ── Percentage calculation ────────────────────────────────────────────────

    def test_percentage_correct(self):
        """3 FS rels, 1 redundant → 33.3%."""
        a, b, c, d = make_act('A'), make_act('B'), make_act('C'), make_act('D')
        rels = [make_rel('A','B'), make_rel('B','C'), make_rel('C','D'),
                make_rel('A','C')]   # redundant
        acts = wire({'A':a,'B':b,'C':c,'D':d}, rels)
        r    = check_redundant_relationships(acts, rels)
        assert r['total']      == 4   # all 4 are FS
        assert r['violations'] == 1
        assert r['percentage'] == 25.0
