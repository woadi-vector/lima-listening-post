"""Project-local subject folders with evidence-derived, live contents and freshness."""
import re
import unicodedata
from datetime import datetime, date
from zoneinfo import ZoneInfo
from .workspace import fingerprint
from .store import _now


def key(name):
    if not isinstance(name,str) or not name.strip() or len(name)>200:raise ValueError('Use a subject name of 1–200 characters.')
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',name).strip()).casefold()


def schema(ws):
    ws.db.executescript('''CREATE TABLE IF NOT EXISTS subject_folders (
        id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),name TEXT NOT NULL,
        name_key TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(project_id,name_key));
        CREATE TABLE IF NOT EXISTS subject_members (
        claim_id TEXT PRIMARY KEY REFERENCES claims(id),folder_id TEXT NOT NULL REFERENCES subject_folders(id),basis TEXT NOT NULL);''')


def ensure(ws,project,name):
    if isinstance(name,str) and len(name)>200:name=name[:185]+'… '+fingerprint(name)[:12]
    normalized=key(name)
    identity=fingerprint(['subject-folder',project,normalized])
    ws.db.execute('INSERT OR IGNORE INTO subject_folders VALUES (?,?,?,?,?)',(identity,project,name.strip(),normalized,_now()))
    return identity


def file_claim(ws,project,claim_id,name):
    schema(ws)
    key(name)
    claim=ws.db.execute('SELECT project_id FROM claims WHERE id=?',(claim_id,)).fetchone()
    if not claim or claim['project_id']!=project:raise ValueError('Choose evidence in this project.')
    with ws.db:
        folder=ensure(ws,project,name)
        ws.db.execute('INSERT INTO subject_members VALUES (?,?,?) ON CONFLICT(claim_id) DO UPDATE SET folder_id=excluded.folder_id,basis=excluded.basis',
                      (claim_id,folder,'Filed by you'))
    return {'folder_id':folder,'work_changed':False}


def catalog(ws,project):
    schema(ws)
    with ws.db:
        for c in ws.claims(project):
            if c['review']=='rejected':continue
            folder=ensure(ws,project,c['subject'])
            ws.db.execute('INSERT OR IGNORE INTO subject_members VALUES (?,?,?)',(c['id'],folder,'Matched subject name'))
    return [r[0] for r in ws.db.execute('SELECT name FROM subject_folders WHERE project_id=? ORDER BY name_key LIMIT 100',(project,))]


def latest_stamp(values):
    valid=[]
    for value in values:
        if not value:continue
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=ZoneInfo('America/Chicago'))
            valid.append((parsed.timestamp(),value))
        except (ValueError,TypeError,AttributeError):continue
    return max(valid)[1] if valid else None


def listing(ws,report,*,as_of=None):
    schema(ws)
    today=date.fromisoformat(as_of) if as_of else datetime.now(ZoneInfo('America/Chicago')).date()
    claims=[c for p in report['projects'] for c in p['history']]
    with ws.db:
        for c in claims:
            if c['review']=='rejected':continue
            folder=ensure(ws,c['project_id'],c['subject'])
            ws.db.execute('INSERT OR IGNORE INTO subject_members VALUES (?,?,?)',(c['id'],folder,'Matched subject name'))
    members={r['claim_id']:dict(r) for r in ws.db.execute('SELECT * FROM subject_members')}
    projects={p['id']:p for p in report['projects']}
    folders=[]
    for row in ws.db.execute('SELECT * FROM subject_folders ORDER BY name_key'):
        folder=dict(row);project=projects.get(folder['project_id'])
        if not project:continue
        history=[c for c in project['history'] if members.get(c['id'],{}).get('folder_id')==folder['id']]
        active=[c for c in history if c['review']!='rejected']
        if not active:continue
        ids={c['id'] for c in active}
        current=[c for c in project['current'] if c['id'] in ids]
        pending=[c for c in active if c['review']=='pending']
        conflicts=[g for g in project['conflicts'] if any(c['id'] in ids for c in g['claims'])]
        source_dates=[c['captured_at'] for c in active if c['captured_at']]
        reviewed_dates=[c['reviewed_at'] for c in active if c['reviewed_at']]
        received_dates=[c['created_at'] for c in active]
        latest=latest_stamp(source_dates)
        latest_reviewed=latest_stamp([c['captured_at'] for c in current])
        # Capture dates, never a recent import/review, determine source age.
        try:age=(today-datetime.fromisoformat(latest.replace('Z','+00:00')).astimezone(ZoneInfo('America/Chicago')).date()).days if latest else None
        except (ValueError,TypeError):age=None
        folder.update(project=project['name'],current=current,pending=pending,conflicts=conflicts,
            history=history,source_count=len({c['record_id'] for c in active}),latest_source_at=latest,
            last_received_at=latest_stamp(received_dates),last_reviewed_at=latest_stamp(reviewed_dates),
            latest_reviewed_source_at=latest_reviewed,freshness_incomplete=any(not latest_stamp([c['captured_at']]) for c in active),
            source_age_days=age,needs_fresh_check=age is not None and age>=7,
            freshness='Source date unknown' if age is None else 'Source date is in the future' if age<0 else 'Source is '+str(age)+' days old',
            contexts=sorted({c.get('context_category') or 'uncertain' for c in active}),
            overview=[{'id':c['id'],'kind':c['kind'],'value':c['value'],'state':c['state']} for c in current],
            overview_basis='Current reviewed evidence; pending interpretations and conflicts kept separate')
        folders.append(folder)
    return folders
