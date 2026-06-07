# xer_parser/xer_parser.py
# Primavera P6 .xer file parser
# Uses the canonical Read_XER_File function as requested,
# then builds Activity and Relationship objects with ALL fields
# needed by the 14-point DCMA assessment.

import pandas as pd


def _with_time(date_str):
    """Ensure a date string always carries a time component.
    If it looks like bare YYYY-MM-DD (no space), append ' 00:00'.
    """
    if date_str and ' ' not in date_str:
        return date_str + ' 00:00'
    return date_str


# ── Low-level XER reader (provided by user, unchanged) ─────────────────────
def Read_XER_File(xer_file_path):
    tables = {}
    current_table = None
    columns = None

    try:
        with open(xer_file_path, 'r', encoding='latin-1') as file:
            for line in file:
                line = line.strip()

                if line.startswith('%T'):
                    current_table = line.split('\t')[1].strip()
                    tables[current_table] = []
                    continue

                if line.startswith('%F') and current_table:
                    columns = line.split('\t')[1:]
                    continue

                if current_table and columns and (
                        line.startswith('%R') or not line.startswith('%')):
                    data = line.split('\t')[1 if line.startswith('%R') else 0:]
                    tables[current_table].append(
                        dict(zip(
                            columns,
                            data[:len(columns)] + [None] * (
                                len(columns) - len(data)
                                if len(data) < len(columns) else 0
                            )
                        ))
                    )

    except UnicodeDecodeError:
        return {}

    dataframes = {}
    target = ['PROJECT', 'TASK', 'TASKPRED', 'CALENDAR', 'TASKRSRC', 'PROJWBS']
    for table, rows in tables.items():
        if table in target and rows:
            dataframes[table] = pd.DataFrame(rows)

    # ── Index each table ──────────────────────────────────────────────────
    if 'CALENDAR' in dataframes:
        dataframes['CALENDAR'].set_index('clndr_id', inplace=True)

    if 'TASKPRED' in dataframes and 'task_pred_id' in dataframes['TASKPRED'].columns:
        dataframes['TASKPRED'].set_index('task_pred_id', inplace=True)

    if 'PROJECT' in dataframes:
        dataframes['PROJECT'].set_index('proj_id', inplace=True)

    if 'TASK' in dataframes:
        df = dataframes['TASK']
        if 'proj_id' in df.columns and 'task_code' in df.columns:
            dataframes['TASK'].index = (
                df['proj_id'].astype(str) + "__" + df['task_code'].astype(str)
            )
        # Numeric coercion
        numeric_cols = [
            'target_drtn_hr_cnt', 'remain_drtn_hr_cnt',
            'total_float_hr_cnt',  'free_float_hr_cnt',
            'base_drtn_hr_cnt',
        ]
        for col in numeric_cols:
            if col in dataframes['TASK'].columns:
                dataframes['TASK'][col] = pd.to_numeric(
                    dataframes['TASK'][col], errors='coerce').fillna(0.0)

    if 'TASKPRED' in dataframes and 'lag_hr_cnt' in dataframes['TASKPRED'].columns:
        dataframes['TASKPRED']['lag_hr_cnt'] = pd.to_numeric(
            dataframes['TASKPRED']['lag_hr_cnt'], errors='coerce').fillna(0.0)

    return dataframes


# ── Domain model ────────────────────────────────────────────────────────────
class Activity:
    """
    Represents a single Primavera task / activity.
    Fields map directly to TASK table columns.
    """
    __slots__ = (
        'task_id', 'task_code', 'task_name',
        'proj_id', 'wbs_id', 'calendar_id',
        'task_type', 'status_code',
        # Scheduled dates (early dates from CPM)
        'start', 'finish',
        # Actual dates
        'act_start', 'act_finish',
        # Baseline dates
        'bl_start', 'bl_finish',
        # Float / duration
        'duration',        # target (baseline) duration hours
        'base_duration',   # alias for baseline duration
        'remaining_dur',
        'total_float',
        'free_float',
        # Constraints
        'constraint',      # cstr_type
        'constraint_date', # cstr_date
        'constraint2',     # cstr_type2
        'constraint2_date',# cstr_date2
        # Resource flag (set after TASKRSRC join)
        'has_resource',
        # Relationship lists
        'predecessors',
        'successors',
    )

    def __init__(self):
        for s in self.__slots__:
            setattr(self, s, None if s not in (
                'predecessors', 'successors') else [])
        self.duration      = 0.0
        self.base_duration = 0.0
        self.remaining_dur = 0.0
        self.total_float   = 0.0
        self.free_float    = 0.0
        self.has_resource  = False

    @property
    def is_complete(self):
        return self.status_code == 'TK_Complete'

    @property
    def is_incomplete(self):
        return self.status_code != 'TK_Complete'

    @property
    def is_milestone(self):
        return self.task_type in ('TT_Mile', 'TT_FinMile')

    @property
    def is_summary(self):
        return self.task_type in ('TT_WBS', 'TT_LOE')

    @property
    def is_normal(self):
        """Normal discrete work task — excludes milestones (start+finish), WBS summary, LOE."""
        return self.task_type not in ('TT_Mile', 'TT_FinMile', 'TT_WBS', 'TT_LOE')


class Relationship:
    """
    Represents a TASKPRED row (a dependency between two activities).
    """
    __slots__ = ('pred_task_id', 'succ_task_id', 'pred_type', 'lag')

    def __init__(self):
        self.pred_task_id = ''
        self.succ_task_id = ''
        self.pred_type    = 'PR_FS'
        self.lag          = 0.0


# ── High-level parser class ─────────────────────────────────────────────────
class XERParser:
    """
    Parses a Primavera .xer file and exposes:
        .activities    → dict  task_id → Activity
        .relationships → list  of Relationship  (actual project only)
        .project_info  → dict  of project-level metadata (data_date, etc.)

    When actual_proj_id and baseline_proj_id are provided:
        - Activities are filtered to the actual project only
        - Baseline dates (bl_start, bl_finish, base_duration) are populated
          from the matching activity (by task_code) in the baseline project
        - Activities with no baseline match get empty bl_start / bl_finish
    """

    def __init__(self, filepath):
        self.filepath      = filepath
        self.activities    = {}   # task_id → Activity
        self.relationships = []
        self.project_info  = {}
        self.hours_per_day = 8.0  # overridden from base calendar in _parse_project

    # ── Public API ──────────────────────────────────────────────────────────
    @staticmethod
    def get_projects(filepath):
        """
        Return list of projects found in the XER file.
        Each entry: {'proj_id', 'proj_name', 'wbs_name', 'data_date'}
        """
        dfs = Read_XER_File(filepath)
        if 'PROJECT' not in dfs or dfs['PROJECT'].empty:
            return []
        proj_df = dfs['PROJECT']

        # Build proj_id -> WBS root name map from PROJWBS table
        # The project root node is identified by proj_node_flag = 'Y'
        wbs_root = {}
        if 'PROJWBS' in dfs and not dfs['PROJWBS'].empty:
            for _, wrow in dfs['PROJWBS'].iterrows():
                pid  = str(wrow.get('proj_id', '') or '').strip()
                flag = str(wrow.get('proj_node_flag', '') or '').strip()
                wnam = str(wrow.get('wbs_name', '') or '').strip()
                if flag == 'Y' and pid and wnam:
                    wbs_root[pid] = wnam

        projects = []
        for proj_id, row in proj_df.iterrows():
            pid   = str(proj_id)
            name  = str(row.get('proj_short_name', '') or '').strip()
            wname = wbs_root.get(pid, name)
            dd    = _with_time(str(row.get('last_recalc_date', '') or '').strip())
            projects.append({
                'proj_id'  : pid,
                'proj_name': name or pid,
                'wbs_name' : wname or name or pid,
                'data_date': dd,
            })
        return projects

    def parse(self, actual_proj_id=None, baseline_proj_id=None):
        dfs = Read_XER_File(self.filepath)
        if not dfs:
            return

        self._parse_project(dfs, actual_proj_id)
        self._parse_activities(dfs, actual_proj_id)
        self._parse_relationships(dfs)
        self._link_resources(dfs)
        self._link_relationships()

        if baseline_proj_id:
            self._apply_baseline(dfs, baseline_proj_id)

        # Parse complete
        pass

    # ── Private helpers ─────────────────────────────────────────────────────
    def _safe(self, row, col, default=''):
        v = row.get(col, default)
        return default if (v is None or (isinstance(v, float) and
                                         str(v) == 'nan')) else str(v).strip()

    def _safe_float(self, row, col, default=0.0):
        try:
            return float(row.get(col) or default)
        except (TypeError, ValueError):
            return default

    def _parse_project(self, dfs, proj_id=None):
        if 'PROJECT' not in dfs:
            return
        proj_df = dfs['PROJECT']
        if proj_df.empty:
            return

        # Select the requested project row, fall back to first
        if proj_id and str(proj_id) in proj_df.index:
            row = proj_df.loc[str(proj_id)]
            idx = str(proj_id)
        else:
            row = proj_df.iloc[0]
            idx = str(proj_df.index[0])

        # Resolve WBS root name (the full project title in Primavera)
        # The project root node is identified by proj_node_flag = 'Y'
        wbs_name = ''
        if 'PROJWBS' in dfs and not dfs['PROJWBS'].empty:
            for _, wrow in dfs['PROJWBS'].iterrows():
                pid  = str(wrow.get('proj_id', '') or '').strip()
                flag = str(wrow.get('proj_node_flag', '') or '').strip()
                if pid == idx and flag == 'Y':
                    wbs_name = str(wrow.get('wbs_name', '') or '').strip()
                    break

        self.project_info = {
            'proj_id'        : idx,
            'proj_short_name': self._safe(row, 'proj_short_name'),
            'wbs_name'       : wbs_name,
            # data_date is the schedule status date
            'data_date'      : _with_time(self._safe(row, 'last_recalc_date') or
                               self._safe(row, 'plan_start_date')),
            'plan_end_date'  : self._safe(row, 'plan_end_date'),
            'sum_base_proj_id': self._safe(row, 'sum_base_proj_id'),
        }

        # Read hours-per-day from the project's base calendar (default 8)
        clndr_id = self._safe(row, 'clndr_id') or self._safe(row, 'base_clndr_id')
        if clndr_id and 'CALENDAR' in dfs and not dfs['CALENDAR'].empty:
            cal_df = dfs['CALENDAR']
            if clndr_id in cal_df.index and 'period_hrs_per_day' in cal_df.columns:
                try:
                    hpd = float(cal_df.loc[clndr_id, 'period_hrs_per_day'] or 0)
                    if 1.0 <= hpd <= 24.0:
                        self.hours_per_day = hpd
                except (TypeError, ValueError, KeyError):
                    pass

    def _parse_activities(self, dfs, proj_id=None):
        if 'TASK' not in dfs:
            return
        for _, row in dfs['TASK'].iterrows():
            # Filter to the actual project when specified
            if proj_id and str(self._safe(row, 'proj_id')) != str(proj_id):
                continue

            a = Activity()
            a.task_id        = self._safe(row, 'task_id')
            a.task_code      = self._safe(row, 'task_code')
            a.task_name      = self._safe(row, 'task_name')
            a.proj_id        = self._safe(row, 'proj_id')
            a.wbs_id         = self._safe(row, 'wbs_id')
            a.calendar_id    = self._safe(row, 'clndr_id')
            a.task_type      = self._safe(row, 'task_type')
            a.status_code    = self._safe(row, 'status_code')

            # Scheduled (CPM early) dates
            a.start          = self._safe(row, 'early_start_date')
            a.finish         = self._safe(row, 'early_end_date')

            # Actual dates
            a.act_start      = self._safe(row, 'act_start_date')
            a.act_finish     = self._safe(row, 'act_end_date')

            # Baseline dates (will be overridden by _apply_baseline if
            # a separate baseline project is provided)
            a.bl_start       = self._safe(row, 'target_start_date')
            a.bl_finish      = self._safe(row, 'target_end_date')

            # Constraint
            a.constraint      = self._safe(row, 'cstr_type')
            a.constraint_date = self._safe(row, 'cstr_date')
            a.constraint2     = self._safe(row, 'cstr_type2')
            a.constraint2_date= self._safe(row, 'cstr_date2')

            # Numeric fields
            a.duration        = self._safe_float(row, 'target_drtn_hr_cnt')
            a.base_duration   = self._safe_float(row, 'base_drtn_hr_cnt') or a.duration
            a.remaining_dur   = self._safe_float(row, 'remain_drtn_hr_cnt')
            a.total_float     = self._safe_float(row, 'total_float_hr_cnt')
            a.free_float      = self._safe_float(row, 'free_float_hr_cnt')

            self.activities[a.task_id] = a

    def _parse_relationships(self, dfs):
        if 'TASKPRED' not in dfs:
            return
        for _, row in dfs['TASKPRED'].iterrows():
            r = Relationship()
            r.pred_task_id = self._safe(row, 'pred_task_id')
            r.succ_task_id = self._safe(row, 'task_id')
            r.pred_type    = self._safe(row, 'pred_type') or 'PR_FS'
            r.lag          = self._safe_float(row, 'lag_hr_cnt')
            self.relationships.append(r)

    def _link_resources(self, dfs):
        """
        Mark activities that have at least one resource assignment.
        Uses TASKRSRC table; if absent, has_resource stays False (default).
        """
        if 'TASKRSRC' in dfs and not dfs['TASKRSRC'].empty:
            rsrc_df = dfs['TASKRSRC']
            if 'task_id' in rsrc_df.columns:
                tasks_with_rsrc = set(rsrc_df['task_id'].dropna().astype(str))
                for act in self.activities.values():
                    act.has_resource = act.task_id in tasks_with_rsrc

    def _link_relationships(self):
        """
        Populate predecessors / successors on each Activity.
        Only keeps relationships where BOTH ends belong to the actual project
        (i.e. both task_ids are in self.activities).
        """
        filtered = []
        for r in self.relationships:
            pred_in = r.pred_task_id in self.activities
            succ_in = r.succ_task_id in self.activities
            if succ_in:
                self.activities[r.succ_task_id].predecessors.append(r)
            if pred_in:
                self.activities[r.pred_task_id].successors.append(r)
            if pred_in and succ_in:
                filtered.append(r)
        self.relationships = filtered

    def _apply_baseline(self, dfs, baseline_proj_id):
        """
        Override bl_start, bl_finish, and base_duration on each actual activity
        using the matching activity (by task_code) from the baseline project.

        Activities with no baseline match get empty bl_start / bl_finish.
        All baseline-related fields come exclusively from the baseline project.
        """
        if 'TASK' not in dfs:
            return

        # Build task_code → row map for the baseline project
        baseline_map = {}
        for _, row in dfs['TASK'].iterrows():
            if str(self._safe(row, 'proj_id')) == str(baseline_proj_id):
                code = self._safe(row, 'task_code')
                if code:
                    baseline_map[code] = row

        # Apply to actual activities
        for act in self.activities.values():
            bl_row = baseline_map.get(act.task_code)
            if bl_row is not None:
                act.bl_start      = self._safe(bl_row, 'target_start_date')
                act.bl_finish     = self._safe(bl_row, 'target_end_date')
                bl_dur = self._safe_float(bl_row, 'target_drtn_hr_cnt')
                if bl_dur > 0:
                    act.base_duration = bl_dur
            else:
                # No baseline counterpart — clear inherited baseline fields
                act.bl_start      = ''
                act.bl_finish     = ''
