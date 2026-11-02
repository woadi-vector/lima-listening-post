"""Explicit daily Notion notes. No email execution, scheduled publishing or overwrite."""
import ctypes
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlencode
from urllib.request import Request, build_opener, ProxyHandler
from zoneinfo import ZoneInfo

from . import drafts
from .interpret import NoRedirect
from .store import _now
from .workspace import fingerprint

LOCK = threading.RLock()
VERSION = '2025-09-03'


def page_id(value):
    if not isinstance(value, str): raise ValueError('Enter a Notion page link or ID')
    parsed=urlparse(value)
    if parsed.scheme:
        if parsed.scheme!='https' or parsed.hostname not in {'notion.so','www.notion.so','notion.com','www.notion.com','app.notion.com'}:
            raise ValueError('Use an HTTPS Notion page link')
        match=re.search(r'([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$',parsed.path.rstrip('/'))
        if not match:raise ValueError('Use a Notion page link containing its page ID')
        value=match.group(1)
    try:return str(uuid.UUID(value))
    except (ValueError,AttributeError):raise ValueError('Use a Notion page link containing its page ID') from None


def _crypt(data, decrypt=False):
    if os.name!='nt': raise ValueError('On this platform, set LIMA_NOTION_TOKEN before starting Lima.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));result=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    call=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    call.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    call.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if not call(ctypes.byref(source),None,None,None,None,1,ctypes.byref(result)):
        raise ValueError('Windows could not protect or unlock the Notion credential.')
    try:return ctypes.string_at(result.data,result.size)
    finally:kernel.LocalFree(result.data)


def credential_path(ws):return Path(ws.db.execute('PRAGMA database_list').fetchone()[2]+'.notion.dpapi')


def token(ws):
    configured=os.environ.get('LIMA_NOTION_TOKEN')
    if configured:return configured
    path=credential_path(ws)
    if path.exists():return _crypt(path.read_bytes(),True).decode()
    raise ValueError('Connect your dedicated Lima Notion integration first.')


class Client:
    def __init__(self, secret):self.secret=secret
    def request(self, method, path, data=None):
        if not path.startswith('/') or '://' in path:raise ValueError('Invalid Notion API path')
        req=Request('https://api.notion.com/v1'+path,
            data=json.dumps(data).encode() if data is not None else None,method=method,
            headers={'Authorization':'Bearer '+self.secret,'Notion-Version':VERSION,'Content-Type':'application/json'})
        try:
            with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=30) as response:body=response.read(2000001)
            if len(body)>2000000:raise ValueError('Notion response exceeded the size limit')
            result=json.loads(body)
            if not isinstance(result,dict):raise ValueError('Invalid Notion response')
            return result
        except HTTPError as error:
            raise ValueError({401:'Notion rejected the credential.',403:'Notion denied access; check connection capabilities.',
                404:'The Lima connection cannot access this page. Add it through the page Connections menu.',
                429:'Notion rate limit reached; try later.'}.get(error.code,f'Notion request failed (HTTP {error.code}).')) from None
        except (URLError,OSError,TimeoutError,json.JSONDecodeError):
            raise ValueError('Notion is unavailable or returned an unreadable response.') from None

    def page(self, identity):
        result=self.request('GET','/pages/'+page_id(identity))
        if result.get('archived') or result.get('in_trash'):raise ValueError('This Notion page is archived or in Trash.')
        return result

    def children(self, identity):
        result=[];cursor=None
        for _ in range(20):
            query={'page_size':100}
            if cursor:query['start_cursor']=cursor
            page=self.request('GET','/blocks/'+page_id(identity)+'/children?'+urlencode(query))
            result.extend(page['results'])
            if not page.get('has_more'):return result
            cursor=page['next_cursor']
        raise ValueError('This destination is too large to check safely. Use a dedicated Lima parent page.')


def schema(ws):
    ws.db.executescript('''CREATE TABLE IF NOT EXISTS notion_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), parent_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notion_plans (
        id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, version_id TEXT NOT NULL,
        parent_id TEXT NOT NULL, day TEXT NOT NULL, payload TEXT NOT NULL,
        status TEXT NOT NULL, created_at TEXT NOT NULL, page_id TEXT);
        CREATE TABLE IF NOT EXISTS notion_days (
        parent_id TEXT NOT NULL, day TEXT NOT NULL, page_id TEXT, status TEXT NOT NULL,
        PRIMARY KEY(parent_id,day));''')


def title(page):
    return ''.join(t.get('plain_text',t.get('text',{}).get('content','')) for prop in page.get('properties',{}).values()
                   if prop.get('type')=='title' for t in prop.get('title',[])) or 'Untitled page'


def setup(ws, parent, secret=None, client=None):
    identity=page_id(parent)
    if secret is not None and (not isinstance(secret,str) or not 10<=len(secret)<=500):raise ValueError('Enter the dedicated Notion integration secret.')
    client=client or Client(secret or token(ws))
    me=client.request('GET','/users/me')
    destination=client.page(identity)
    if secret is not None:
        encrypted=_crypt(secret.encode())
        path=credential_path(ws);temporary=path.with_suffix('.tmp');temporary.write_bytes(encrypted);temporary.replace(path)
    schema(ws)
    with ws.db:ws.db.execute('INSERT INTO notion_settings VALUES (1,?) ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id',(identity,))
    return {'connected':True,'connection':me.get('name'),'parent_id':identity,'parent_title':title(destination)}


def state(ws):
    schema(ws)
    row=ws.db.execute('SELECT parent_id FROM notion_settings WHERE id=1').fetchone()
    return {'configured':bool(row),'parent_id':row[0] if row else '',
            'credential_available':bool(os.environ.get('LIMA_NOTION_TOKEN') or credential_path(ws).exists())}


def paragraph(text):return {'object':'block','type':'paragraph','paragraph':{'rich_text':[{'type':'text','text':{'content':text}}]}}


def bundle(plan):
    body=plan['body']
    pieces=[body[i:i+1800] for i in range(0,len(body),1800)]
    if len(pieces)>90:raise ValueError('This note is too long for one safe Notion update. Shorten it first.')
    result={'object':'block','type':'toggle','toggle':{'rich_text':[{'type':'text','text':{'content':plan['subject']+' · Lima receipt '+plan['receipt']}}],
            'children':[paragraph('Reviewed snapshot. Publishing this note does not send messages, create contacts or change calendars. Individual action statuses are recorded separately.'),*[paragraph(p) for p in pieces]]}}
    if len(json.dumps(result).encode())>400000:raise ValueError('This note is too large for one safe Notion update. Shorten it first.')
    return result


def prepare(ws, draft_id, version_id, client=None, now=None):
    schema(ws);draft=drafts.get(ws,draft_id)
    if draft['version_id']!=version_id or draft['status']!='approved' or draft['stale']:
        raise ValueError('Save and approve the current draft with fresh project evidence first.')
    parent=state(ws)['parent_id']
    if not parent:raise ValueError('Set up the Lima Notion destination first.')
    client=client or Client(token(ws));destination=client.page(parent)
    now=now or datetime.now(timezone.utc)
    day=now.astimezone(ZoneInfo('America/Chicago')).date().isoformat()
    receipt=fingerprint([parent,day,version_id])
    payload={'subject':draft['subject'],'body':draft['body'],'parent_title':title(destination),
             'daily_title':'Lima — Daily Review — '+day,'receipt':receipt,'expires_at':(now+timedelta(minutes=30)).isoformat()}
    bundle(payload) # Validate size before offering approval.
    identity=uuid.uuid4().hex
    with ws.db:ws.db.execute('INSERT INTO notion_plans VALUES (?,?,?,?,?,?,?,?,NULL)',
        (identity,draft_id,version_id,parent,day,json.dumps(payload),'prepared',now.isoformat()))
    return get(ws,identity)


def get(ws, identity):
    schema(ws)
    row=ws.db.execute('SELECT * FROM notion_plans WHERE id=?',(identity,)).fetchone()
    if not row:raise ValueError('Choose an existing Notion preview')
    result=dict(row);result.update(json.loads(result.pop('payload')))
    result['url']='https://www.notion.so/'+result['page_id'].replace('-','') if result['page_id'] else None
    return result


def _find_day(client, parent, daily_title):
    pages=[b['id'] for b in client.children(parent) if b.get('type')=='child_page' and b['child_page']['title']==daily_title]
    if len(pages)>1:raise ValueError('Multiple daily pages match. Resolve the duplicates in Notion before publishing.')
    return pages[0] if pages else None


def _delivered(client, page, payload):
    expected=bundle(payload)
    for block in client.children(page):
        if block.get('type')!='toggle':continue
        rich=block['toggle'].get('rich_text',[])
        text=''.join(t.get('plain_text',t.get('text',{}).get('content','')) for t in rich)
        if text!=expected['toggle']['rich_text'][0]['text']['content']:continue
        content=client.children(block['id'])
        actual=[''.join(t.get('plain_text',t.get('text',{}).get('content','')) for t in b.get('paragraph',{}).get('rich_text',[])) for b in content]
        wanted=[b['paragraph']['rich_text'][0]['text']['content'] for b in expected['toggle']['children']]
        if actual==wanted:return True
        raise ValueError('The delivered note was edited in Notion. It will not be overwritten or duplicated.')
    return False


def publish(ws, identity, *, confirmed=False, client=None, now=None, recover_only=False):
    if confirmed is not True and not recover_only:raise ValueError('Confirm this exact note and Notion destination first.')
    with LOCK:
        plan=get(ws,identity);client=client or Client(token(ws))
        if plan['status']=='completed':return plan
        if recover_only:
            page=plan['page_id'] or _find_day(client,plan['parent_id'],plan['daily_title'])
            if not page or not _delivered(client,page,plan):raise ValueError('Delivery could not be verified. No write was retried; inspect Notion before trying a new preview.')
            return _complete(ws,identity,plan,page)
        if plan['status']!='prepared':raise ValueError('Delivery may already have occurred. Use Check delivery; Lima will not send it again automatically.')
        if datetime.fromisoformat(plan['expires_at']) < (now or datetime.now(timezone.utc)):
            raise ValueError('This preview expired. Prepare a fresh preview.')
        draft=drafts.get(ws,plan['draft_id'])
        parent=client.page(plan['parent_id'])
        if title(parent)!=plan['parent_title']:raise ValueError('The destination title changed. Prepare a fresh preview.')
        with ws.db:
            ws.db.execute('BEGIN IMMEDIATE')
            settings=ws.db.execute('SELECT parent_id FROM notion_settings WHERE id=1').fetchone()
            latest=ws.db.execute('SELECT id FROM local_draft_versions WHERE draft_id=? ORDER BY rowid DESC LIMIT 1',(plan['draft_id'],)).fetchone()
            from .daily_artifacts import is_stale
            if is_stale(ws,plan['draft_id']):raise ValueError('Follow-ups changed after this Notion preview. Prepare and approve a fresh daily note.')
            if not settings or settings[0]!=plan['parent_id'] or latest[0]!=plan['version_id'] or draft['status']!='approved' or drafts.project_stamp(ws,draft['project_id'])!=draft['source_hash']:
                raise ValueError('Draft, destination or project evidence changed. Prepare a fresh preview.')
            changed=ws.db.execute("UPDATE notion_plans SET status='sending' WHERE id=? AND status='prepared'",(identity,)).rowcount
            if not changed:raise ValueError('This preview is already being delivered.')
        page=None
        try:
            known=ws.db.execute('SELECT * FROM notion_days WHERE parent_id=? AND day=?',(plan['parent_id'],plan['day'])).fetchone()
            page=known['page_id'] if known else _find_day(client,plan['parent_id'],plan['daily_title'])
            if known and not page:raise ValueError('A prior daily page creation is unresolved. Check delivery first.')
            if page:
                existing=client.page(page)
                if existing.get('parent',{}).get('page_id')!=plan['parent_id']:raise ValueError('The daily page moved. It will not be modified.')
                if not _delivered(client,page,plan):client.request('PATCH','/blocks/'+page+'/children',{'children':[bundle(plan)]})
            else:
                with ws.db:ws.db.execute('INSERT INTO notion_days VALUES (?,?,NULL,?)',(plan['parent_id'],plan['day'],'sending'))
                result=client.request('POST','/pages',{'parent':{'page_id':plan['parent_id']},
                    'properties':{'title':{'type':'title','title':[{'type':'text','text':{'content':plan['daily_title']}}]}},'children':[bundle(plan)]})
                page=page_id(result['id'])
            with ws.db:ws.db.execute('UPDATE notion_plans SET page_id=? WHERE id=?',(page,identity))
            if not _delivered(client,page,plan):raise ValueError('Notion write was not verified. Check delivery before any retry.')
            return _complete(ws,identity,plan,page)
        except Exception:
            with ws.db:ws.db.execute("UPDATE notion_plans SET status='unknown',page_id=? WHERE id=?",(page,identity))
            raise ValueError('Delivery is unconfirmed. Use Check delivery before retrying; no automatic resend occurred.') from None


def _complete(ws, identity, plan, page):
    with ws.db:
        ws.db.execute("UPDATE notion_plans SET status='completed',page_id=? WHERE id=?",(page,identity))
        ws.db.execute("INSERT INTO notion_days VALUES (?,?,?,'completed') ON CONFLICT(parent_id,day) DO UPDATE SET page_id=excluded.page_id,status='completed'",(plan['parent_id'],plan['day'],page))
    return get(ws,identity)
