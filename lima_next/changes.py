"""Read-only comparisons. Only explicit reviewed supersession establishes a revision."""
from .workspace import Workspace


def project_changes(claims):
    by_id = {c['id']: c for c in claims}
    current, conflicts = Workspace.current_state(claims)
    active = current + [c for group in conflicts for c in group['claims']]
    rows = []
    for claim in claims:
        if claim['kind'] == 'reference' or claim['review'] == 'rejected':
            continue
        if claim['review'] == 'accepted' and claim.get('supersedes'):
            old = by_id.get(claim['supersedes'])
            if old:
                rows.append({'status': 'reviewed_revision', 'before': [old], 'after': claim,
                             'at': claim.get('reviewed_at') or claim['created_at']})
        elif claim['review'] == 'pending':
            # Topic matching is a comparison aid, never an inferred supersession edge.
            previous = [c for c in active if Workspace.work_key(c) == Workspace.work_key(claim)]
            rows.append({'status': 'proposed_comparison' if previous else 'proposed_new',
                         'before': previous, 'after': claim, 'at': claim['created_at']})
    return sorted(rows, key=lambda r: (r['at'], r['after']['id']), reverse=True)
