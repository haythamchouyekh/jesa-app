#!/usr/bin/env python3
"""
generate_ocp_xer.py
Generates OCP_PIPE_2024.xer — DN-250-PAC (DN 250 Acid Delivery System)
OCP Jorf Lasfar Phosphoric Acid Unit, Morocco
Primavera P6 XER format v22.12

Usage:  python generate_ocp_xer.py
Output: OCP_PIPE_2024.xer  (~60 KB, ready for Primavera P6 import)
"""

import os
from datetime import datetime, timedelta

# ─── Working calendar: Mon-Fri 07:00-17:00, 10 h/day ─────────────────────────

def _next_workday(dt):
    nxt = (dt + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt

def add_wh(start: datetime, hours: float) -> datetime:
    """Add working hours (Mon-Fri 07:00-17:00) to a datetime."""
    cur, rem = start, float(hours)
    while rem > 0:
        if cur.weekday() >= 5:
            cur = _next_workday(cur - timedelta(days=1))
        if cur.hour < 7:
            cur = cur.replace(hour=7, minute=0, second=0, microsecond=0)
        day_end = cur.replace(hour=17, minute=0, second=0, microsecond=0)
        if cur >= day_end:
            cur = _next_workday(cur)
            continue
        avail = (day_end - cur).total_seconds() / 3600
        take  = min(avail, rem)
        rem  -= take
        cur  += timedelta(hours=take)
        if rem > 0:
            cur = _next_workday(cur)
    return cur

def fmt(dt):
    return dt.strftime('%Y-%m-%d %H:%M') if dt else ''

# ─── Project constants ────────────────────────────────────────────────────────

PS = datetime(2026,  2, 10,  7, 0)   # project start
DD = datetime(2026,  4, 15,  7, 0)   # status / data date
PE = datetime(2026,  6, 30, 17, 0)   # planned finish

PROJ_ID  = 'OBJ_1001'
CLNDR_ID = 'OBJ_2001'

WBS_IDS = {
    'ROOT': 'OBJ_3001', 'JAL': 'OBJ_3002', 'PREP': 'OBJ_3003',
    'FAB':  'OBJ_3004', 'INST':'OBJ_3005', 'MANI': 'OBJ_3006',
    'TEST': 'OBJ_3007', 'HAND':'OBJ_3008',
}

RSRC_IDS = {
    'TUY':'OBJ_4001', 'AT' :'OBJ_4002', 'MON':'OBJ_4003', 'AM' :'OBJ_4004',
    'SOU':'OBJ_4005', 'AS' :'OBJ_4006', 'CHA':'OBJ_4007', 'AC' :'OBJ_4008',
    'GRU':'OBJ_4009', 'MAN':'OBJ_4010',
}

RSRC_INFO = [
    ('TUY', 'Tuyauteur',           'RT_Labor'),
    ('AT',  'Aide Tuyauteur',      'RT_Labor'),
    ('MON', 'Monteur',             'RT_Labor'),
    ('AM',  'Aide Monteur',        'RT_Labor'),
    ('SOU', 'Soudeur',             'RT_Labor'),
    ('AS',  'Aide Soudeur',        'RT_Labor'),
    ('CHA', 'Chaudronnier',        'RT_Labor'),
    ('AC',  'Aide Chaudronnier',   'RT_Labor'),
    ('GRU', 'Grutier',             'RT_Labor'),
    ('MAN', 'Conducteur Manitou',  'RT_Labor'),
]

# ─── Task definitions ─────────────────────────────────────────────────────────
# (task_code, task_name, wbs_key, dur_h,
#  [(pred_code, 'FS'|'SS', lag_h), ...],
#  [rsrc_code, ...])

TASKS_DEF = [
    # ── MILESTONES ────────────────────────────────────────────────────────────
    ('JAL001', 'Démarrage Projet',          'JAL',  0, [],                      []),
    ('JAL002', 'Préparation Achevée',       'JAL',  0, [('A1240','FS',0)],      []),
    ('JAL003', 'Fabrication Achevée',       'JAL',  0, [('A2270','FS',0)],      []),
    ('JAL004', 'Installation Achevée',      'JAL',  0, [('A3440','FS',0)],      []),
    ('JAL005', 'Tests Achevés',             'JAL',  0, [('A5220','FS',0)],      []),
    ('JAL006', 'Remise Finale Projet',      'JAL',  0, [('A6130','FS',0)],      []),

    # ── PREPARATION ──────────────────────────────────────────────────────────
    ('A1000', 'Relevé & Investigation Site',            'PREP',  48, [('JAL001','FS',0)],          ['TUY','MON']),
    ('A1010', 'Détection Clash 3D',                    'PREP',  36, [('A1000', 'FS',0)],          ['TUY']),
    ('A1020', 'Préparation Isométriques',              'PREP',  72, [('A1010', 'FS',0)],          ['TUY']),
    ('A1030', 'Approbation Procédures ISO',            'PREP',  24, [('A1020', 'FS',0)],          ['TUY']),
    ('A1040', 'Spécification Equipements',             'PREP',  48, [('A1010', 'FS',0)],          ['MON']),
    ('A1050', 'Approvisionnement Equipements',         'PREP', 120, [('A1040', 'FS',0)],          ['MON']),
    ('A1060', 'Demande Achat Tuyauterie',              'PREP',  72, [('A1030', 'FS',0)],          ['TUY']),
    ('A1070', 'Livraison Tuyauterie',                  'PREP', 144, [('A1060', 'FS',0)],          ['MON','MAN']),
    ('A1080', 'Demande Achat Raccords',                'PREP',  60, [('A1030', 'FS',0)],          ['TUY']),
    ('A1090', 'Livraison Raccords',                    'PREP', 120, [('A1080', 'FS',0)],          ['MON','MAN']),
    ('A1100', 'Demande Achat Vannes',                  'PREP',  48, [('A1040', 'FS',0)],          ['TUY']),
    ('A1110', 'Livraison Vannes',                      'PREP', 144, [('A1100', 'FS',0)],          ['MON','MAN']),
    ('A1120', 'Installation Base Vie & Chantier',      'PREP',  36, [('A1000', 'FS',0)],          ['MON','AM']),
    ('A1130', 'Induction Securite & Causerie',         'PREP',  18, [('A1120', 'FS',0)],          ['MON']),
    ('A1140', 'Approvisionnement Echafaudages',        'PREP',  48, [('A1120', 'FS',0)],          ['MON']),
    ('A1150', 'Montage Echafaudages',                  'PREP',  60, [('A1140', 'FS',0)],          ['MON','AM']),
    ('A1160', 'Qualification CND',                     'PREP',  36, [('A1130', 'FS',0)],          ['SOU']),
    ('A1170', 'Qualification Procedure Soudage',       'PREP',  48, [('A1160', 'FS',0)],          ['SOU','AS']),
    ('A1180', 'Preparation Plan HSE',                  'PREP',  24, [('JAL001','FS',0)],          ['MON']),
    ('A1190', 'Approbation Plan HSE',                  'PREP',  18, [('A1180', 'FS',0)],          ['MON']),
    ('A1200', 'Procedures Permis de Travail',          'PREP',  30, [('A1190', 'FS',0)],          ['MON']),
    ('A1210', 'Inspection Outillage & Equipements',    'PREP',  24, [('A1120', 'FS',0)],          ['MON']),
    ('A1220', 'Tracage & Marquage Site',               'PREP',  36, [('A1150', 'FS',0)],          ['TUY','AT']),
    ('A1230', 'Travaux Genie Civil Supports',          'PREP',  72, [('A1220', 'FS',0)],          ['MON','AM','GRU']),
    ('A1240', 'Inspection Genie Civil',                'PREP',  24, [('A1230', 'FS',0)],          ['TUY']),

    # ── FABRICATION ──────────────────────────────────────────────────────────
    ('A2100', 'Coupe Tuyaux - Ligne Principale',       'FAB',  60, [('A1070','FS',0)],            ['TUY','AT','CHA']),
    ('A2110', 'Biseautage - Ligne Principale',         'FAB',  48, [('A2100','FS',0)],            ['TUY','CHA','AC']),
    ('A2120', 'Fabrication Supports - Principale',     'FAB',  72, [('A1230','FS',0)],            ['CHA','AC','SOU']),
    ('A2130', 'Coupe Tuyaux - Branche A',              'FAB',  54, [('A1070','FS',0)],            ['TUY','AT','CHA']),
    ('A2140', 'Biseautage - Branche A',                'FAB',  42, [('A2130','FS',0)],            ['TUY','CHA','AC']),
    ('A2150', 'Fabrication Supports - Branche A',      'FAB',  60, [('A2120','SS',0)],            ['CHA','AC','SOU']),
    ('A2160', 'Coupe Tuyaux - Branche B',              'FAB',  54, [('A1070','FS',0)],            ['TUY','AT','CHA']),
    ('A2170', 'Biseautage - Branche B',                'FAB',  42, [('A2160','FS',0)],            ['TUY','CHA','AC']),
    ('A2180', 'Fabrication Supports - Branche B',      'FAB',  60, [('A2120','SS',0)],            ['CHA','AC','SOU']),
    ('A2190', 'Prep. Joints Soudes - Principale',      'FAB',  36, [('A2110','FS',0)],            ['SOU','AS']),
    ('A2200', 'Prep. Joints Soudes - Branche A',       'FAB',  30, [('A2140','FS',0)],            ['SOU','AS']),
    ('A2210', 'Prep. Joints Soudes - Branche B',       'FAB',  30, [('A2170','FS',0)],            ['SOU','AS']),
    ('A2220', 'Inspection Revetement Entrant',         'FAB',  24, [('A1090','FS',0)],            ['TUY']),
    ('A2230', 'Revetement Anticorrosion - Principale', 'FAB',  60, [('A2190','FS',0)],            ['TUY','AT']),
    ('A2240', 'Revetement Anticorrosion - Branche A',  'FAB',  48, [('A2200','FS',0)],            ['TUY','AT']),
    ('A2250', 'Revetement Anticorrosion - Branche B',  'FAB',  48, [('A2210','FS',0)],            ['TUY','AT']),
    ('A2260', 'Identification & Marquage Spools',      'FAB',  30, [('A2110','FS',0)],            ['TUY']),
    ('A2270', 'Inspection & Controle Qualite FAB',     'FAB',  36, [('A2230','FS',0),
                                                                     ('A2240','FS',0),
                                                                     ('A2250','FS',0)],            ['TUY']),
    # ── INSTALLATION – Ligne Principale ──────────────────────────────────────
    ('A3100', 'Pose Supports - Ligne Principale',      'INST',  60, [('A2120','FS',0)],           ['MON','AM','GRU']),
    ('A3110', 'Pose Tuyauterie - Ligne Principale',    'INST',  72, [('A3100','FS',  0),
                                                                      ('A2230','SS',168)],          ['TUY','AT','GRU','MAN']),
    ('A3120', 'Alignement - Ligne Principale',         'INST',  48, [('A3110','FS',0)],           ['TUY','AT']),
    ('A3130', 'Soudage - Ligne Principale',            'INST',  96, [('A3120','FS',0)],           ['SOU','AS']),
    ('A3140', 'Montage Vannes - Principale',           'INST',  36, [('A3130','FS',0)],           ['MON','AM']),
    ('A3150', 'Boulonnage Brides - Principale',        'INST',  24, [('A3140','FS',0)],           ['TUY','AT']),
    ('A3160', 'Isolation Thermique - Principale',      'INST',  48, [('A3150','FS',0)],           ['TUY','AT']),

    # ── INSTALLATION – Branche A ─────────────────────────────────────────────
    ('A3200', 'Pose Supports - Branche A',             'INST',  54, [('A2150','FS',  0)],         ['MON','AM','GRU']),
    ('A3210', 'Pose Tuyauterie - Branche A',           'INST',  66, [('A3200','FS',  0),
                                                                      ('A2240','SS',168)],          ['TUY','AT','GRU','MAN']),
    ('A3220', 'Alignement - Branche A',                'INST',  42, [('A3210','FS',0)],           ['TUY','AT']),
    ('A3230', 'Soudage - Branche A',                   'INST',  84, [('A3220','FS',0)],           ['SOU','AS']),
    ('A3240', 'Montage Vannes - Branche A',            'INST',  30, [('A3230','FS',0)],           ['MON','AM']),
    ('A3250', 'Boulonnage Brides - Branche A',         'INST',  18, [('A3240','FS',0)],           ['TUY','AT']),
    ('A3260', 'Isolation Thermique - Branche A',       'INST',  42, [('A3250','FS',0)],           ['TUY','AT']),

    # ── INSTALLATION – Branche B ─────────────────────────────────────────────
    ('A3300', 'Pose Supports - Branche B',             'INST',  54, [('A2180','FS',  0)],         ['MON','AM','GRU']),
    ('A3310', 'Pose Tuyauterie - Branche B',           'INST',  66, [('A3300','FS',  0),
                                                                      ('A2250','SS',168)],          ['TUY','AT','GRU','MAN']),
    ('A3320', 'Alignement - Branche B',                'INST',  42, [('A3310','FS',0)],           ['TUY','AT']),
    ('A3330', 'Soudage - Branche B',                   'INST',  84, [('A3320','FS',0)],           ['SOU','AS']),
    ('A3340', 'Montage Vannes - Branche B',            'INST',  30, [('A3330','FS',0)],           ['MON','AM']),
    ('A3350', 'Boulonnage Brides - Branche B',         'INST',  18, [('A3340','FS',0)],           ['TUY','AT']),
    ('A3360', 'Isolation Thermique - Branche B',       'INST',  42, [('A3350','FS',0)],           ['TUY','AT']),

    # ── INSTALLATION – Connexions & Controle ──────────────────────────────────
    ('A3400', 'Connexion Principale - Branche A',      'INST',  48, [('A3160','FS',0),
                                                                      ('A3260','FS',0)],            ['TUY','AT','SOU','AS']),
    ('A3410', 'Connexion Principale - Branche B',      'INST',  48, [('A3160','FS',0),
                                                                      ('A3360','FS',0)],            ['TUY','AT','SOU','AS']),
    ('A3420', 'Verification Integration Systeme',      'INST',  36, [('A3400','FS',0),
                                                                      ('A3410','FS',0)],            ['TUY','MON']),
    ('A3430', 'Inspection Visuelle Soudures',          'INST',  30, [('A3420','FS',0)],           ['SOU']),
    ('A3440', 'Controle Radiographique (RT)',          'INST',  60, [('A3430','FS',0)],           ['SOU','AS']),

    # ── MANIFOLD ACQUISITION ─────────────────────────────────────────────────
    ('A4100', 'Fabrication Chassis Manifold-Acq',      'MANI',  48, [('A2120','FS',0)],           ['CHA','AC']),
    ('A4110', 'Assemblage Corps Manifold-Acq',         'MANI',  60, [('A4100','FS',0)],           ['TUY','AT','SOU']),
    ('A4120', 'Installation Vannes Manifold-Acq',      'MANI',  36, [('A4110','FS',0)],           ['MON','AM']),
    ('A4130', 'Instrumentation Manifold-Acq',          'MANI',  42, [('A4120','FS',0)],           ['MON']),
    ('A4140', 'Controle Pre-Test Manifold-Acq',        'MANI',  24, [('A4130','FS',0)],           ['TUY']),
    ('A4150', 'Mise en Place Manifold-Acq Site',       'MANI',  36, [('A4140','FS',0),
                                                                      ('A3420','FS',0)],            ['MON','AM','GRU']),
    ('A4160', 'Raccordement Manifold-Acq/Principale',  'MANI',  30, [('A4150','FS',0)],           ['TUY','AT','SOU']),

    # ── MANIFOLD DISTRIBUTION ────────────────────────────────────────────────
    ('A4200', 'Fabrication Chassis Manifold-Dist',     'MANI',  48, [('A2120','SS',0)],           ['CHA','AC']),
    ('A4210', 'Assemblage Corps Manifold-Dist',        'MANI',  60, [('A4200','FS',0)],           ['TUY','AT','SOU']),
    ('A4220', 'Installation Vannes Manifold-Dist',     'MANI',  36, [('A4210','FS',0)],           ['MON','AM']),
    ('A4230', 'Instrumentation Manifold-Dist',         'MANI',  42, [('A4220','FS',0)],           ['MON']),
    ('A4240', 'Controle Pre-Test Manifold-Dist',       'MANI',  24, [('A4230','FS',0)],           ['TUY']),
    ('A4250', 'Mise en Place Manifold-Dist Site',      'MANI',  36, [('A4240','FS',0),
                                                                      ('A3420','FS',0)],            ['MON','AM','GRU']),
    ('A4260', 'Raccordement Manifold-Dist/Systeme',    'MANI',  30, [('A4250','FS',0)],           ['TUY','AT','SOU']),
    ('A4310', 'Verification Interface Manifolds',      'MANI',  24, [('A4160','FS',0),
                                                                      ('A4260','FS',0)],            ['TUY','MON']),

    # ── ESSAIS SOUS PRESSION ─────────────────────────────────────────────────
    ('A5100', 'Preparation Dossier Test',              'TEST',  36, [('A3440','FS',0),
                                                                      ('A4310','FS',0)],            ['TUY']),
    ('A5110', 'Pose Obturateurs Provisoires',          'TEST',  24, [('A5100','FS',0)],           ['TUY','AT']),
    ('A5120', 'Remplissage Eau Systeme',               'TEST',  18, [('A5110','FS',0)],           ['MON','AM']),
    ('A5130', 'Essai Pression Hydrostatique',          'TEST',  54, [('A5120','FS',0)],           ['TUY','MON','SOU']),
    ('A5140', 'Surveillance Essai Pression',           'TEST',  18, [('A5130','SS',0)],           ['TUY','MON']),
    ('A5150', 'Documentation Essai Pression',          'TEST',  24, [('A5130','FS',0)],           ['TUY']),
    ('A5160', 'Vidange Systeme',                       'TEST',  18, [('A5150','FS',0)],           ['MON','AM']),
    ('A5170', 'Rincage a l Eau',                       'TEST',  36, [('A5160','FS',0)],           ['MON','AM']),
    ('A5180', 'Nettoyage Chimique',                    'TEST',  48, [('A5170','FS',0)],           ['TUY','AT','MON']),
    ('A5190', 'Verification Rincage',                  'TEST',  24, [('A5180','FS',0)],           ['TUY']),
    ('A5200', 'Etablissement Punch List',              'TEST',  18, [('A5190','FS',0)],           ['TUY','MON']),
    ('A5210', 'Levee Punch List',                      'TEST',  72, [('A5200','FS',0)],           ['TUY','AT','MON','AM','SOU','AS']),
    ('A5220', 'Inspection Finale Systeme',             'TEST',  30, [('A5210','FS',0)],           ['TUY','MON']),

    # ── REMISE ET CLOTURE ────────────────────────────────────────────────────
    ('A6100', 'Plans Execution As-Built',              'HAND',  60, [('A5220','FS',0)],           ['TUY']),
    ('A6110', 'Manuels Exploitation & Maintenance',   'HAND',  48, [('A6100','FS',0)],           ['TUY','MON']),
    ('A6120', 'Formation Operateurs',                  'HAND',  36, [('A6110','FS',0)],           ['MON']),
    ('A6130', 'Rehabilitation Site & Demobilisation', 'HAND',  48, [('A6120','FS',0)],           ['MON','AM','GRU','MAN']),
]


# ─── Forward-pass scheduler ───────────────────────────────────────────────────

def schedule_tasks(tasks_def, project_start):
    tasks = {}
    for td in tasks_def:
        code, name, wbs, dur, preds, rsrc = td
        tasks[code] = dict(code=code, name=name, wbs=wbs, dur=dur,
                           preds=preds, rsrc=rsrc, start=None, end=None)

    tasks['JAL001']['start'] = project_start
    tasks['JAL001']['end']   = project_start
    resolved = {'JAL001'}

    for _ in range(len(tasks) * 3):
        for code, t in tasks.items():
            if code in resolved:
                continue
            if not all(p[0] in resolved for p in t['preds']):
                continue

            if not t['preds']:
                es = project_start
            else:
                es = project_start
                for pc, pt, lag in t['preds']:
                    p = tasks[pc]
                    ref = p['end'] if pt == 'FS' else p['start']
                    cand = add_wh(ref, lag) if lag > 0 else ref
                    if cand > es:
                        es = cand

            # Snap to working day start
            if es.weekday() >= 5:
                while es.weekday() >= 5:
                    es += timedelta(days=1)
                es = es.replace(hour=7, minute=0)
            if es.hour < 7:
                es = es.replace(hour=7, minute=0)

            t['start'] = es
            t['end']   = es if t['dur'] == 0 else add_wh(es, t['dur'])
            resolved.add(code)

        if len(resolved) == len(tasks):
            break

    return tasks


def get_status(t, data_date):
    """Return (status_code, pct, act_start, act_end, remain_h)."""
    ts, te, dur = t['start'], t['end'], t['dur']
    if te <= data_date or (dur == 0 and ts <= data_date):
        return 'TK_Complete', 100, fmt(ts), fmt(te), 0.0
    if ts >= data_date:
        return 'TK_NotStart', 0, '', '', float(dur)
    # In progress
    total_h = (te - ts).total_seconds() / 3600
    done_h  = (data_date - ts).total_seconds() / 3600
    pct     = min(int(done_h / total_h * 100), 99) if total_h > 0 else 50
    remain  = dur * (1 - pct / 100)
    return 'TK_Active', pct, fmt(ts), '', remain


# ─── XER builder ─────────────────────────────────────────────────────────────

SEP = '\t'

def hdr(table, *fields):
    return [f'%T{SEP}{table}',
            '%F' + SEP + SEP.join(fields)]

def rec(*vals):
    return '%R' + SEP + SEP.join('' if v is None else str(v) for v in vals)


def build_xer(tasks, tasks_def):
    lines = [
        SEP.join(['ERMHDR','22.12','ORA','OCP_PIPE_2024',
                  fmt(datetime.now()),'Admin','Project','Project',''])
    ]

    # ── PROJECT ──────────────────────────────────────────────────────────────
    lines += hdr('PROJECT',
        'proj_id','fy_start_month_num','rsrc_self_add_flag','allow_complete_flag',
        'rsrc_multi_assign_flag','checkout_flag','project_flag','step_complete_flag',
        'cost_qty_recalc_flag','batch_sum_flag','name_sep_char','def_complete_pct_type',
        'checkout_date','last_checksum','critical_drtn_hr_cnt','def_cost_per_qty',
        'last_recalc_date','plan_start_date','plan_end_date','scd_end_date','add_date',
        'last_task_id','base_clndr_id','proj_short_name','clndr_id',
        'task_code_base','task_code_step','task_code_prefix',
    )
    lines.append(rec(
        PROJ_ID, 1, 'N','N','N','N','Y','N','N','N','.','CP_Phys',
        '','', 0, 0.0,
        fmt(DD), fmt(PS), fmt(PE), fmt(PE), fmt(PS),
        'OBJ_9999', CLNDR_ID, 'OCP-PIPE-24', CLNDR_ID,
        1000, 10, 'A',
    ))

    # ── PROJWBS ──────────────────────────────────────────────────────────────
    wbs_defs = [
        ('ROOT', None,   0, 'Y', 'DN-250-PAC', 'DN 250 Acid Delivery System'),
        ('JAL',  'ROOT', 1, 'N', 'JALONS',     'Jalons Projet'),
        ('PREP', 'ROOT', 2, 'N', 'PREP',       'Preparation'),
        ('FAB',  'ROOT', 3, 'N', 'FAB',        'Fabrication'),
        ('INST', 'ROOT', 4, 'N', 'INST',       'Installation'),
        ('MANI', 'ROOT', 5, 'N', 'MANI',       'Assemblage Manifolds'),
        ('TEST', 'ROOT', 6, 'N', 'TEST',       'Essais sous Pression'),
        ('HAND', 'ROOT', 7, 'N', 'HAND',       'Remise et Cloture'),
    ]
    lines += hdr('PROJWBS',
        'wbs_id','proj_id','obs_id','seq_num','est_wt','proj_node_flag',
        'sum_data_flag','status_code','wbs_short_name','wbs_name',
        'phase_id','parent_wbs_id',
    )
    for wkey, parent, seq, is_root, short, name in wbs_defs:
        lines.append(rec(
            WBS_IDS[wkey], PROJ_ID, '', seq, 1.0, is_root,
            'N', 'WS_Open', short, name, '',
            WBS_IDS[parent] if parent else '',
        ))

    # ── CALENDAR ─────────────────────────────────────────────────────────────
    # Mon-Fri 07:00-17:00 (0=Sun, 1=Mon, …, 6=Sat)
    wk = (
        '(0||)'
        '(1|s(0,0,0,0,0,7,0)f(0,0,0,0,0,17,0))'
        '(2|s(0,0,0,0,0,7,0)f(0,0,0,0,0,17,0))'
        '(3|s(0,0,0,0,0,7,0)f(0,0,0,0,0,17,0))'
        '(4|s(0,0,0,0,0,7,0)f(0,0,0,0,0,17,0))'
        '(5|s(0,0,0,0,0,7,0)f(0,0,0,0,0,17,0))'
        '(6||)'
    )
    lines += hdr('CALENDAR',
        'clndr_id','default_flag','clndr_name','proj_id','base_clndr_flag',
        'last_chng_date','clndr_type',
        'period_hrs_per_day','period_hrs_per_week','period_hrs_per_month','period_hrs_per_year',
        'clndr_data',
    )
    lines.append(rec(
        CLNDR_ID, 'N', 'Standard 5j/sem 10h', '', 'Y',
        fmt(PS), 'CA_Base',
        10, 50, 200, 2400,
        wk,
    ))

    # ── RSRC ─────────────────────────────────────────────────────────────────
    lines += hdr('RSRC',
        'rsrc_id','parent_rsrc_id','clndr_id','rsrc_seq_num',
        'rsrc_name','rsrc_short_name','rsrc_type','active_flag',
        'auto_compute_act_flag','def_qty_per_hr','cost_qty_type',
    )
    for code, name, rtype in RSRC_INFO:
        lines.append(rec(
            RSRC_IDS[code], '', CLNDR_ID, RSRC_IDS[code][-4:],
            name, code, rtype, 'Y', 'Y', 1.0, 'QT_Hour',
        ))

    # ── TASK ─────────────────────────────────────────────────────────────────
    lines += hdr('TASK',
        'task_id','proj_id','wbs_id','clndr_id',
        'phys_complete_pct','rev_fdbk_flag','est_wt','lock_plan_flag',
        'auto_compute_act_flag','complete_pct_type','task_type','duration_type',
        'status_code','task_code','task_name','rsrc_id',
        'total_float_hr_cnt','free_float_hr_cnt',
        'remain_drtn_hr_cnt','act_start_date','act_end_date',
        'late_start_date','late_end_date','expect_end_date',
        'early_start_date','early_end_date',
        'target_start_date','target_end_date',
        'target_drtn_hr_cnt',
        'cstr_type','cstr_date','cstr_type2','cstr_date2',
    )
    TASK_ID_BASE = 5000
    task_id_map  = {}

    for i, td in enumerate(tasks_def):
        code, name, wbs_key, dur, preds, rsrc = td
        t   = tasks[code]
        tid = f'OBJ_{TASK_ID_BASE + i}'
        task_id_map[code] = tid

        ttype = 'TT_Mile' if dur == 0 else 'TT_Task'
        status, pct, act_s, act_e, remain = get_status(t, DD)

        lines.append(rec(
            tid, PROJ_ID, WBS_IDS[wbs_key], CLNDR_ID,
            pct, 'N', 1.0, 'N',
            'Y', 'CP_Phys', ttype, 'DT_FixedDrtn',
            status, code, name, '',
            0, 0,
            remain, act_s, act_e,
            '','','',
            fmt(t['start']), fmt(t['end']),
            fmt(t['start']), fmt(t['end']),
            float(dur),
            '','','','',
        ))

    # ── TASKPRED ─────────────────────────────────────────────────────────────
    lines += hdr('TASKPRED',
        'task_pred_id','task_id','pred_task_id',
        'proj_id','pred_proj_id','pred_type','lag_hr_cnt',
    )
    pred_ctr = 7000
    for td in tasks_def:
        code = td[0]
        for pc, pt, lag in td[4]:
            if code not in task_id_map or pc not in task_id_map:
                continue
            p6type = 'PR_FS' if pt == 'FS' else 'PR_SS'
            lines.append(rec(
                f'OBJ_{pred_ctr}',
                task_id_map[code], task_id_map[pc],
                PROJ_ID, PROJ_ID, p6type, float(lag),
            ))
            pred_ctr += 1

    # ── TASKRSRC ─────────────────────────────────────────────────────────────
    lines += hdr('TASKRSRC',
        'taskrsrc_id','task_id','proj_id','rsrc_id',
        'rsrc_type','remain_qty','target_qty','act_reg_qty',
        'target_start_date','target_end_date',
        'act_start_date','act_end_date',
        'rollup_dates_flag','rate_type',
    )
    rsrc_ctr = 8000
    for td in tasks_def:
        code, _, _, dur, _, rsrc_codes = td
        if not rsrc_codes or dur == 0:
            continue
        t = tasks[code]
        tid = task_id_map[code]
        status, pct, act_s, act_e, _ = get_status(t, DD)
        for rc in rsrc_codes:
            if rc not in RSRC_IDS:
                continue
            tgt = float(dur)
            act = tgt * pct / 100
            rem = tgt - act
            lines.append(rec(
                f'OBJ_{rsrc_ctr}', tid, PROJ_ID, RSRC_IDS[rc],
                'RT_Labor', rem, tgt, act,
                fmt(t['start']), fmt(t['end']),
                act_s, act_e,
                'N', 'RT_CostPerQty',
            ))
            rsrc_ctr += 1

    lines.append('%E')
    return '\n'.join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print('DN-250-PAC — OCP Jorf Lasfar Acid Delivery Pipeline')
    print('Scheduling tasks (Mon-Fri 07:00-17:00 calendar)...')

    tasks = schedule_tasks(TASKS_DEF, PS)

    unresolved = [c for c, t in tasks.items() if t['start'] is None]
    if unresolved:
        print(f'  WARNING: {len(unresolved)} unresolved task(s): {unresolved}')

    counts = {'TK_Complete': 0, 'TK_Active': 0, 'TK_NotStart': 0}
    for t in tasks.values():
        st, *_ = get_status(t, DD)
        counts[st] += 1

    print(f'  {len(tasks)} activities scheduled:')
    print(f'    Complete    : {counts["TK_Complete"]}')
    print(f'    In progress : {counts["TK_Active"]}')
    print(f'    Not started : {counts["TK_NotStart"]}')

    # Show critical path end
    proj_end = max(t['end'] for t in tasks.values() if t['end'] is not None)
    print(f'  Calculated finish: {fmt(proj_end)}')
    print(f'  Data date        : {fmt(DD)}')

    print('Building XER...')
    xer = build_xer(tasks, TASKS_DEF)

    out = 'OCP_PIPE_2024.xer'
    with open(out, 'w', encoding='latin-1') as f:
        f.write(xer)

    size = os.path.getsize(out)
    rels = sum(len(td[4]) for td in TASKS_DEF)
    print(f'  Written: {out}  ({size:,} bytes)')
    print(f'  Activities : {len(TASKS_DEF)}')
    print(f'  Relationships: {rels}')
    print(f'  Resources  : {len(RSRC_INFO)} types')
    print()
    print('Import into Primavera P6:')
    print('  File > Import > Primavera XER > select OCP_PIPE_2024.xer')
