# metrics/redundant_relationships.py
# Bonus Check: Redundant Relationships (Transitive Closure Detection)
#
# NOT part of the original DCMA 14-point spec.
# A relationship A --FS--> C is redundant if C is already reachable from A
# through another all-FS chain (A --FS--> B --FS--> ... --FS--> C).
#
# Only FS→FS chains are considered. SS, FF, and SF relationships have
# different timing semantics and cannot substitute for an FS relationship.

from collections import deque


def _build_fs_reachability(activities):
    """
    Build adjacency and transitive reachability using ONLY FS relationships.
    Returns:
        fs_adj    : task_id → set of direct FS successor task_ids
        reachable : task_id → set of ALL task_ids reachable via FS chains
    """
    fs_adj = {tid: set() for tid in activities}
    for act in activities.values():
        for rel in act.successors:
            if rel.pred_type == 'PR_FS' and rel.succ_task_id in activities:
                fs_adj[act.task_id].add(rel.succ_task_id)

    def dfs(start):
        visited = set()
        stack   = list(fs_adj.get(start, []))
        while stack:
            node = stack.pop()
            if node not in visited:
                visited.add(node)
                stack.extend(fs_adj.get(node, []))
        return visited

    reachable = {tid: dfs(tid) for tid in activities}
    return fs_adj, reachable


def _find_fs_path(start, target, fs_adj):
    """
    BFS for the shortest FS path from start toward target.
    Returns a list of node IDs from start up to (but NOT including) target.
    e.g. path A→B→C→D returns [A, B, C] when called as _find_fs_path(A, D, …)
    """
    if target in fs_adj.get(start, set()):
        return [start]                    # direct one-hop
    queue   = deque([(start, [start])])
    visited = {start}
    while queue:
        node, path = queue.popleft()
        for nxt in fs_adj.get(node, []):
            if nxt == target:
                return path               # found — return path without target
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, path + [nxt]))
    return [start]                        # fallback (shouldn't happen in valid DAG)


def check_redundant_relationships(activities, relationships):
    fs_adj, reachable = _build_fs_reachability(activities)
    violations = []

    for rel in relationships:
        # Only FS relationships can be redundant
        if rel.pred_type != 'PR_FS':
            continue

        pred_id = rel.pred_task_id
        succ_id = rel.succ_task_id

        if pred_id not in activities or succ_id not in activities:
            continue

        # Is succ reachable from pred via FS chains WITHOUT this direct link?
        other_fs_successors = [s for s in fs_adj.get(pred_id, []) if s != succ_id]
        indirect = set()
        for other in other_fs_successors:
            indirect.add(other)
            indirect.update(reachable.get(other, set()))

        if succ_id not in indirect:
            continue

        pred_act = activities[pred_id]
        succ_act = activities[succ_id]

        # Find the full alternative FS path to show in the message
        path_nodes = []
        for other in other_fs_successors:
            if other == succ_id or succ_id in reachable.get(other, set()):
                path_ids  = _find_fs_path(other, succ_id, fs_adj)
                path_nodes = [activities[pid] for pid in path_ids if pid in activities]
                break

        if path_nodes:
            labels   = [a.task_name or a.task_code for a in path_nodes]
            path_str = ' via ' + ' → '.join(labels)
        else:
            path_str = ''

        pred_label = pred_act.task_name or pred_act.task_code
        succ_label = succ_act.task_name or succ_act.task_code

        violations.append({
            'pred_code': pred_act.task_code,
            'pred_name': pred_act.task_name,
            'succ_code': succ_act.task_code,
            'succ_name': succ_act.task_name,
            'rel_type' : 'FS',
            'issue'    : (f'Redundant FS: {pred_label} → {succ_label}'
                          f'{path_str}. Remove this relationship.'),
        })

    # Denominator = FS relationships only (the only ones that can be redundant)
    fs_rels    = [r for r in relationships if r.pred_type == 'PR_FS']
    total      = len(fs_rels)
    count      = len(violations)
    percentage = round((count / total) * 100, 1) if total > 0 else 0.0

    return {
        'metric'     : 'Bonus – Redundant Relationships',
        'status'     : 'PASS' if count == 0 else 'FAIL',
        'total'      : total,
        'violations' : count,
        'percentage' : percentage,
        'threshold'  : '0% redundant FS relationships',
        'details'    : violations,
    }
