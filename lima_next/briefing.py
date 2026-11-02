"""Saved local briefings derived from reviewed state, without model embellishment."""

import json
from datetime import date

from .store import _now, _canonical
from .workspace import fingerprint


def _schema(ws):
    with ws.db:
        ws.db.execute('CREATE TABLE IF NOT EXISTS prepared_briefs '
                      '(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)')


def evidence(claim):
    return {key: claim[key] for key in ('id', 'record_id', 'external_id', 'quote',
                                       'start_offset', 'end_offset', 'subject', 'value')}


def prepare_brief(ws, as_of):
    # The browser supplies its America/Chicago calendar day explicitly.
    if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError('Choose a valid briefing date (YYYY-MM-DD)')
    report = ws.reconcile(as_of=as_of)
    projects = []
    for project in report['projects']:
        work = []
        for claim in project['work']:
            work.append({**evidence(claim), **{key: claim[key] for key in
                ('owner', 'state', 'due_date', 'date_basis', 'ready', 'waiting_on')},
                'overdue': claim['date_basis'] == 'verified' and claim['due_date'] < as_of})
        projects.append({'id': project['id'], 'name': project['name'], 'priority': project['priority'],
            'work': work, 'pending_count': project['pending_count'], 'questions': project['questions'],
            'decisions': [evidence(c) for c in project['current'] if c['kind'] == 'decision'],
            'completed': [evidence(c) for c in project['current']
                          if c['kind'] in {'commitment', 'deliverable'} and c['state'] == 'done'],
            'references': [evidence(c) for c in project['references']],
            'conflicts': [{'subject': c['subject'], 'kind': c['kind'],
                           'evidence': [evidence(v) for v in c['claims']]} for c in project['conflicts']]})
    brief = {'as_of': as_of, 'source_state_id': report['id'], 'projects': projects,
             'collisions': report['collisions'], 'external_execution': False}
    brief['id'] = fingerprint(brief)
    _schema(ws)
    with ws.db:
        ws.db.execute('INSERT OR IGNORE INTO prepared_briefs VALUES (?,?,?)',
                      (brief['id'], _canonical(brief), _now()))
    row = ws.db.execute('SELECT created_at FROM prepared_briefs WHERE id=?', (brief['id'],)).fetchone()
    brief['created_at'] = row[0]
    brief['text'] = brief_text(brief)
    brief['stale'] = False
    return brief


def latest_brief(ws):
    _schema(ws)
    row = ws.db.execute('SELECT payload,created_at FROM prepared_briefs ORDER BY rowid DESC LIMIT 1').fetchone()
    if row is None:
        return None
    brief = json.loads(row[0])
    brief['created_at'] = row[1]
    brief['text'] = brief_text(brief)
    brief['stale'] = ws.reconcile(as_of=brief['as_of'])['id'] != brief['source_state_id']
    return brief


def brief_text(brief):
    lines = [f"Lima daily brief — {brief['as_of']}",
             'Current reviewed project state, not a list of changes made today.',
             'Local preparation only. Nothing has been sent or published.', '']
    for collision in brief['collisions']:
        lines.append('Shared verified deadline ' + collision['date'] + ': ' +
                     '; '.join(i['project'] + ' / ' + i['subject'] for i in collision['items']))
    for project in brief['projects']:
        lines.extend(['', project['name'], f"Priority {project['priority']} · {project['pending_count']} interpretations still awaiting review"])
        if not any(project[k] for k in ('work', 'decisions', 'completed', 'references', 'conflicts')):
            lines.append('No reviewed project state yet.')
        for claim in project['work']:
            deadline = (f"{claim['date_basis']} deadline {claim['due_date']}" if claim['due_date'] else 'deadline unknown')
            lines.append(f"{'READY' if claim['ready'] else 'WAITING'}: {claim['subject']} — {claim['value']} "
                         f"(owner: {claim['owner']}; {claim['state']}; {deadline}{'; OVERDUE' if claim['overdue'] else ''})")
            if claim['waiting_on']:
                lines.append('Waiting for: ' + ', '.join(c['subject'] for c in claim['waiting_on']))
            lines.extend(source_lines(claim))
        for key, label in [('decisions', 'DECISION'), ('completed', 'COMPLETE'), ('references', 'REFERENCE / LEARNING')]:
            for claim in project[key]:
                lines.append(f"{label}: {claim['subject']} — {claim['value']}")
                lines.extend(source_lines(claim))
        for conflict in project['conflicts']:
            lines.append(f"NEEDS RESOLUTION: conflicting {conflict['kind']} about {conflict['subject']}; withheld from current work.")
            for claim in conflict['evidence']:
                lines.extend(source_lines(claim))
        if project['questions']:
            lines.append('Questions to resolve (not new assignments):')
            lines.extend('- ' + question for question in project['questions'])
    return '\n'.join(lines) + '\n'


def source_lines(claim):
    return [f"  Source: {claim['external_id']} · record {claim['record_id']} · span {claim['start_offset']}–{claim['end_offset']}",
            '  Evidence: ' + claim['quote']]
