"""Local follow-up drafts with version-specific review. No sending capability."""

import json
import uuid
from datetime import date

from .briefing import evidence
from .store import _canonical, _now
from .workspace import fingerprint


def schema(ws):
    ws.db.executescript('''
        CREATE TABLE IF NOT EXISTS local_drafts (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
            as_of TEXT NOT NULL, source_hash TEXT NOT NULL, snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS local_draft_versions (
            id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, subject TEXT NOT NULL,
            body TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS local_draft_reviews (
            version_id TEXT PRIMARY KEY, decision TEXT NOT NULL, reviewed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS local_draft_batches (
            as_of TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL);
    ''')


def project_stamp(ws, project_id):
    project = ws.db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
    if project is None:
        raise ValueError('Choose an existing project')
    claims = [dict(r) for r in ws.db.execute('SELECT c.*,r.decision,r.supersedes,r.reviewed_at FROM claims c '
        'LEFT JOIN claim_reviews r ON r.claim_id=c.id WHERE c.project_id=? ORDER BY c.id', (project_id,))]
    deps = [dict(r) for r in ws.db.execute('SELECT * FROM dependencies WHERE project_id=? ORDER BY id', (project_id,))]
    snapshot={'project':dict(project),'claims':claims,'dependencies':deps}
    modes=[dict(r) for r in ws.db.execute("SELECT record_id,mode FROM interpretation_modes WHERE project_id=? AND mode!='mixed' ORDER BY record_id",(project_id,))]
    if modes:snapshot['source_modes']=modes
    return fingerprint(snapshot)


def assemble(project, kind, as_of):
    items, lines = [], [f"{project['name']} — {'project update' if kind == 'update' else 'project notes'}", f'As of {as_of}', '']

    def add(claim, text):
        items.append(evidence(claim))
        lines.append(f'- {text} [{len(items)}]')

    lines.append('Current work')
    if not project['work']:
        lines.append('No open work established from reviewed evidence.')
    for claim in project['work']:
        due = f"; {claim['date_basis']} deadline: {claim['due_date']}" if claim['due_date'] else '; deadline unknown'
        add(claim, f"{claim['subject']}: {claim['value']} (owner: {claim['owner']}; {claim['state']}{due})")
        if claim['waiting_on']:
            lines.append('  Waiting for: ' + ', '.join(i['subject'] for i in claim['waiting_on']))
    for title, claims in [
            ('Decisions', [c for c in project['current'] if c['kind'] == 'decision']),
            ('Completed work', [c for c in project['current'] if c['kind'] in {'commitment', 'deliverable'} and c['state'] == 'done']),
            ('Open questions', [c for c in project['current'] if c['kind'] == 'question' and c['state'] != 'done'])]:
        if claims:
            lines.extend(['', title])
            for claim in claims:
                add(claim, f"{claim['subject']}: {claim['value']}")
    if project['conflicts']:
        lines.extend(['', 'Needs clarification — conflicting reviewed statements'])
        for conflict in project['conflicts']:
            lines.append(f"- {conflict['subject']}: unresolved; withheld from current work.")
            items.extend(evidence(c) for c in conflict['claims'])
    if kind == 'notes' and project['references']:
        lines.extend(['', 'Reference and learning — what the source says, not independently verified facts'])
        for claim in project['references']:
            add(claim, f"{claim['subject']}: {claim['value']}")
    if not items:
        raise ValueError('Review useful evidence for this project before preparing a draft.')
    lines.extend(['', 'Supporting evidence'])
    for number, claim in enumerate(items, 1):
        lines.extend([f"[{number}] {claim['external_id']} · record {claim['record_id']} · span {claim['start_offset']}–{claim['end_offset']}",
                      '  ' + claim['quote']])
    return '\n'.join(lines) + '\n', items


def prepare(ws, project_id, kind, as_of):
    if kind not in {'update', 'notes'}:
        raise ValueError('Choose a project update or project notes')
    if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError('Choose a date in YYYY-MM-DD format')
    schema(ws)
    created = False
    with ws.db:
        ws.db.execute('BEGIN IMMEDIATE')
        stamp = project_stamp(ws, project_id)
        project = next(p for p in ws.reconcile(as_of=as_of, persist=False)['projects'] if p['id'] == project_id)
        body, sources = assemble(project, kind, as_of)
        body = body.strip()
        draft_id = fingerprint({'project': project_id, 'kind': kind, 'as_of': as_of, 'source_hash': stamp})
        if not ws.db.execute('SELECT 1 FROM local_drafts WHERE id=?', (draft_id,)).fetchone():
            created = True
            now = _now()
            ws.db.execute('INSERT INTO local_drafts VALUES (?,?,?,?,?,?,?)',
                          (draft_id, project_id, kind, as_of, stamp, _canonical(sources), now))
            ws.db.execute('INSERT INTO local_draft_versions VALUES (?,?,?,?,?)',
                          (uuid.uuid4().hex, draft_id, f"{project['name']} — {'Project update' if kind == 'update' else 'Project notes'}", body, now))
    draft = get(ws, draft_id)
    draft['newly_created'] = created
    return draft


def get(ws, draft_id):
    schema(ws)
    row = ws.db.execute('SELECT d.*,p.name project FROM local_drafts d JOIN projects p ON p.id=d.project_id WHERE d.id=?', (draft_id,)).fetchone()
    if row is None:
        raise KeyError(draft_id)
    draft = dict(row)
    version = dict(ws.db.execute('SELECT v.*,r.decision,r.reviewed_at FROM local_draft_versions v '
        'LEFT JOIN local_draft_reviews r ON r.version_id=v.id WHERE v.draft_id=? ORDER BY v.rowid DESC LIMIT 1', (draft_id,)).fetchone())
    draft.update(version_id=version['id'], subject=version['subject'], body=version['body'],
                 status=version['decision'] or 'prepared', reviewed_at=version['reviewed_at'],
                 stale=project_stamp(ws, draft['project_id']) != draft['source_hash'],
                 evidence=json.loads(draft.pop('snapshot')), external_execution=False)
    from .daily_artifacts import is_stale
    draft['stale'] = draft['stale'] or is_stale(ws,draft_id)
    return draft


def listing(ws):
    schema(ws)
    return [{key: draft[key] for key in ('id', 'project', 'project_id', 'subject', 'kind', 'as_of', 'status', 'stale')}
            for draft in (get(ws, r[0]) for r in ws.db.execute('SELECT id FROM local_drafts ORDER BY rowid DESC LIMIT 100').fetchall())]


def prepare_all(ws, as_of):
    """Recoverable daily preparation; stable per-project IDs preserve edits/reviews."""
    if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError('Choose a date in YYYY-MM-DD format')
    schema(ws)
    projects = ws.reconcile(as_of=as_of, persist=False)['projects']
    result = {'as_of': as_of, 'created': 0, 'retained': 0, 'draft_ids': [], 'skipped': [],
              'external_execution': False}
    for project in projects:
        operational = bool(project['work'] or project['conflicts'] or any(
            c['kind'] == 'decision' or c['kind'] in {'commitment', 'deliverable'} and c['state'] == 'done' or
            c['kind'] == 'question' and c['state'] != 'done' for c in project['current']))
        kinds = (['update', 'notes'] if operational else ['notes'] if project['references'] else [])
        if not kinds:
            result['skipped'].append({'project_id': project['id'], 'project': project['name'],
                                      'reason': 'No applicable reviewed evidence yet.'})
        for kind in kinds:
            draft = prepare(ws, project['id'], kind, as_of)
            result['draft_ids'].append(draft['id'])
            result['created' if draft['newly_created'] else 'retained'] += 1
    with ws.db:
        ws.db.execute('INSERT INTO local_draft_batches VALUES (?,?,?) ON CONFLICT(as_of) '
                      'DO UPDATE SET payload=excluded.payload,created_at=excluded.created_at',
                      (as_of, _canonical(result), _now()))
    return result


def latest_batch(ws):
    schema(ws)
    row = ws.db.execute('SELECT payload FROM local_draft_batches ORDER BY created_at DESC LIMIT 1').fetchone()
    return json.loads(row[0]) if row else None


def edit(ws, draft_id, version_id, subject, body):
    if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= 200 or not isinstance(body, str) or not 1 <= len(body.strip()) <= 200000:
        raise ValueError('Use a subject up to 200 characters and a body up to 200,000 characters.')
    schema(ws)
    with ws.db:
        ws.db.execute('BEGIN IMMEDIATE')
        current = ws.db.execute('SELECT * FROM local_draft_versions WHERE draft_id=? ORDER BY rowid DESC LIMIT 1', (draft_id,)).fetchone()
        if current is None or current['id'] != version_id:
            raise ValueError('This draft changed in another view. Reopen it before editing.')
        if (current['subject'], current['body']) != (subject.strip(), body.strip()):
            ws.db.execute('INSERT INTO local_draft_versions VALUES (?,?,?,?,?)',
                          (uuid.uuid4().hex, draft_id, subject.strip(), body.strip(), _now()))
    return get(ws, draft_id)


def review(ws, draft_id, version_id, decision):
    if decision not in {'approved', 'dismissed'}:
        raise ValueError('Choose approved or dismissed')
    schema(ws)
    with ws.db:
        ws.db.execute('BEGIN IMMEDIATE')
        current = ws.db.execute('SELECT id FROM local_draft_versions WHERE draft_id=? ORDER BY rowid DESC LIMIT 1', (draft_id,)).fetchone()
        row = ws.db.execute('SELECT * FROM local_drafts WHERE id=?', (draft_id,)).fetchone()
        if current is None or current[0] != version_id:
            raise ValueError('This draft changed. Review its current version first.')
        if decision == 'approved' and project_stamp(ws, row['project_id']) != row['source_hash']:
            raise ValueError('Project evidence changed. Prepare and review a fresh draft before approving.')
        from .daily_artifacts import is_stale
        if decision=='approved' and is_stale(ws,draft_id):raise ValueError('Follow-ups changed. Refresh the Muse repository note before approving.')
        prior = ws.db.execute('SELECT decision FROM local_draft_reviews WHERE version_id=?', (version_id,)).fetchone()
        if prior and prior[0] != decision:
            raise ValueError('This version was already reviewed. Save an edited version for a new review.')
        ws.db.execute('INSERT OR IGNORE INTO local_draft_reviews VALUES (?,?,?)', (version_id, decision, _now()))
    return get(ws, draft_id)
