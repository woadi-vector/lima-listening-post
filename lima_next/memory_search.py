"""Literal local retrieval with explicit current/history status; no invented answers."""

import re


def search(ws, query, project_id=None, limit=40):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 200:
        raise ValueError('Search using 2–200 characters')
    terms = list(dict.fromkeys(re.findall(r'\w+', query.casefold())))
    if not terms or len(terms) > 12:
        raise ValueError('Use up to twelve search words')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Choose a result limit from 1 to 100')
    projects = {r['id']: r['name'] for r in ws.db.execute('SELECT id,name FROM projects')}
    if project_id and project_id not in projects:
        raise ValueError('Choose an existing project')
    claims = ws.claims(project_id)
    current, conflicts = ws.current_state(claims) if project_id else ([], [])
    if not project_id:
        for pid in projects:
            c, f = ws.current_state([claim for claim in claims if claim['project_id'] == pid])
            current.extend(c)
            conflicts.extend(f)
    current_ids = {c['id'] for c in current}
    conflict_ids = {c['id'] for group in conflicts for c in group['claims']}
    hits = []
    for claim in claims:
        haystack = ' '.join(claim[k] for k in ('subject', 'value', 'quote', 'owner')).casefold()
        if not all(t in haystack for t in terms):
            continue
        status = (claim['review'] if claim['review'] != 'accepted' else
                  'current' if claim['id'] in current_ids else
                  'conflicted' if claim['id'] in conflict_ids else 'superseded')
        hits.append({'type': 'claim', 'status': status, 'kind': claim['kind'],
                     'project_id': claim['project_id'], 'project': projects[claim['project_id']],
                     **{key: claim[key] for key in ('id', 'record_id', 'external_id', 'subject', 'value',
                                                  'quote', 'start_offset', 'end_offset')}})
    records = ws.db.execute('SELECT * FROM evidence_records ORDER BY created_at DESC').fetchall()
    for record in records:
        linked = [r[0] for r in ws.db.execute('SELECT project_id FROM project_records WHERE record_id=? ORDER BY project_id', (record['id'],))]
        if project_id and project_id not in linked:
            continue
        content = record['content']
        # Match the source name as well; a title match is explicitly distinguished.
        combined = (record['external_id'] + '\n' + content).casefold()
        if not all(t in combined for t in terms):
            continue
        folded = content.casefold()
        positions = [folded.find(term) for term in terms if term in folded]
        location = 0
        if positions:
            target, offset = min(positions), 0
            for index, char in enumerate(content):
                if offset + len(char.casefold()) > target:
                    location = index
                    break
                offset += len(char.casefold())
        start, end = max(0, location-80), min(len(content), location+240)
        hits.append({'type': 'source', 'status': 'source material', 'kind': record['kind'],
                     'record_id': record['id'], 'external_id': record['external_id'],
                     'project_id': project_id or (linked[0] if linked else None),
                     'projects': [{'id': pid, 'name': projects[pid]} for pid in linked],
                     'quote': content[start:end], 'start_offset': start, 'end_offset': end,
                     'title_match': not positions, 'captured_at': record['captured_at']})
    order = {'current': 0, 'conflicted': 1, 'pending': 2, 'superseded': 3, 'rejected': 4, 'source material': 5}
    hits.sort(key=lambda hit: order[hit['status']])
    return {'query': query, 'project_id': project_id, 'total': len(hits),
            'results': hits[:limit], 'more': len(hits) > limit,
            'scope': 'Imported sources and project claims; unimported Bee inbox items are excluded.',
            'method': 'Literal word matching; results are evidence, not an AI answer.'}
