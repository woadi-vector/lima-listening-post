"""Editable local email/calendar proposals with destination-bound execution previews."""
import base64
import json
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email import policy
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import drafts, contact_delivery
from .store import _now
from .workspace import fingerprint
from .google_connection import Client, GoogleAPIError

LOCK=threading.RLock()
KINDS={'email','calendar_create','calendar_update','contact','text'}


def schema(ws):
    ws.db.executescript('''CREATE TABLE IF NOT EXISTS outgoing_actions (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, record_id TEXT NOT NULL,
        evidence TEXT NOT NULL, source_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outgoing_versions (
        id TEXT PRIMARY KEY, action_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outgoing_plans (
        id TEXT PRIMARY KEY, action_id TEXT NOT NULL, version_id TEXT NOT NULL,
        operation TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, result TEXT);
        CREATE TABLE IF NOT EXISTS outgoing_dismissals (version_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);''')


def _text(value, maximum, required=False):
    if not isinstance(value,str) or len(value)>maximum or required and not value.strip():raise ValueError('Check the action text and required fields.')
    return value.strip()


def addresses(value, required=False):
    if isinstance(value,str):value=[v.strip() for v in value.split(',') if v.strip()]
    if not isinstance(value,list) or len(value)>20:raise ValueError('Use up to 20 explicit email addresses.')
    if any(not isinstance(v,str) or len(v)>254 or not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}',v) for v in value):
        raise ValueError('Enter complete email addresses, separated by commas. Names alone are not enough.')
    if required and not value:raise ValueError('Choose an explicit email recipient before previewing.')
    return list(dict.fromkeys(value))


def clean(value):
    if not isinstance(value,dict) or value.get('kind') not in KINDS:raise ValueError('Choose email, new personal calendar event, or update personal event.')
    result={'kind':value['kind'],'subject':_text(value.get('subject',''),200,True),'body':_text(value.get('body',''),30000,value['kind'] in {'email','text'}),
        'to':addresses(value.get('to',[])),'cc':addresses(value.get('cc',[])),'bcc':addresses(value.get('bcc',[])),
        **{k:_text(value.get(k,''),300) for k in ('calendar_id','event_id','start','end','timezone')}}
    if any(c in result['subject'] for c in '\r\n'):raise ValueError('Use a single-line subject.')
    result['timezone']=result['timezone'] or 'America/Chicago'
    try:ZoneInfo(result['timezone'])
    except ZoneInfoNotFoundError:raise ValueError('Choose a valid time zone, such as America/Chicago.') from None
    if value['kind'] in {'contact','text'}:
        result.update(contact_name=_text(value.get('contact_name',''),200),contact_email=_text(value.get('contact_email',''),254),phone=contact_delivery.phone(value.get('phone','')))
        if result['contact_email']:addresses([result['contact_email']],True)
    return result


def time_range(start, end, zone):
    try:tz=ZoneInfo(zone)
    except ZoneInfoNotFoundError:raise ValueError('Choose a valid time zone.') from None
    def parse(value):
        if not isinstance(value,str) or not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',value):
            raise ValueError('Set an exact date and time, including hours and minutes.')
        try:dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        except (ValueError,AttributeError):raise ValueError('Set an exact start and end date/time before previewing.') from None
        if dt.tzinfo is None:
            first=dt.replace(tzinfo=tz,fold=0);second=dt.replace(tzinfo=tz,fold=1)
            if first.utcoffset()!=second.utcoffset() or first.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)!=dt:
                raise ValueError('This local time is ambiguous or does not exist because of daylight saving. Enter an ISO time with the correct offset.')
            dt=first
        elif dt.astimezone(tz).utcoffset()!=dt.utcoffset():raise ValueError('The time offset does not match the selected time zone.')
        return dt
    low,high=parse(start),parse(end)
    if not timedelta(0)<high.astimezone(timezone.utc)-low.astimezone(timezone.utc)<=timedelta(days=31):
        raise ValueError('End must be after start, within a 31-day window.')
    return low.isoformat(),high.isoformat()


def propose(ws, project_id, record_id, candidate):
    schema(ws)
    if not ws.db.execute('SELECT 1 FROM project_records WHERE project_id=? AND record_id=?',(project_id,record_id)).fetchone():raise ValueError('Associate the source with this project first.')
    source=ws.record(record_id);quote_text=candidate.get('quote')
    if not isinstance(quote_text,str) or len(quote_text)<20 or source['content'].count(quote_text)!=1:
        raise ValueError('An action proposal needs one exact, distinctive source passage.')
    if candidate.get('kind') in {'contact','text'}:
        candidate=dict(candidate)
        try:contact_delivery.phone(candidate.get('phone',''))
        except ValueError:candidate['phone']=''
    payload=clean(candidate)
    # Only literal source addresses survive model generation. The user can supply missing ones later.
    source_addresses={v.casefold():v for v in re.findall(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}',quote_text)}
    for key in ('to','cc','bcc'):payload[key]=[source_addresses[v.casefold()] for v in payload[key] if v.casefold() in source_addresses]
    if payload['kind']!='email':
        payload['calendar_id']='';payload['event_id']=''
        for key in ('start','end'):
            if payload[key] and (payload[key][:10] not in quote_text or payload[key][11:16] not in quote_text):payload[key]=''
    if payload['kind'] in {'contact','text'}:
        for field in ('contact_name','contact_email','phone'):
            literal=payload[field]
            if literal and not re.search(r'(?<![\w@])'+re.escape(literal)+r'(?![\w@])',quote_text,re.I):payload[field]=''
    if payload['kind'] in {'contact','text'} and payload['contact_email']:
        payload['contact_email']=source_addresses.get(payload['contact_email'].casefold(),'')
    start=source['content'].index(quote_text)
    evidence={'record_id':record_id,'external_id':source['external_id'],'start_offset':start,'end_offset':start+len(quote_text),'quote':quote_text}
    stamp=drafts.project_stamp(ws,project_id)
    identity=fingerprint([project_id,record_id,start,quote_text,payload['kind'],payload['subject'],payload['to'],payload['start'],payload['end'],stamp]+([payload['contact_name'],payload['contact_email'],payload['phone']] if payload['kind'] in {'contact','text'} else []))
    with ws.db:
        if not ws.db.execute('SELECT 1 FROM outgoing_actions WHERE id=?',(identity,)).fetchone():
            ws.db.execute('INSERT INTO outgoing_actions VALUES (?,?,?,?,?,?)',(identity,project_id,record_id,json.dumps(evidence),stamp,_now()))
            ws.db.execute('INSERT INTO outgoing_versions VALUES (?,?,?,?)',(uuid.uuid4().hex,identity,json.dumps(payload),_now()))
    return get(ws,identity)


def get(ws, identity):
    schema(ws)
    row=ws.db.execute('SELECT a.*,p.name project FROM outgoing_actions a JOIN projects p ON p.id=a.project_id WHERE a.id=?',(identity,)).fetchone()
    if not row:raise ValueError('Choose an existing proposed action.')
    result=dict(row);result['evidence']=json.loads(result['evidence'])
    version=ws.db.execute('SELECT * FROM outgoing_versions WHERE action_id=? ORDER BY rowid DESC LIMIT 1',(identity,)).fetchone()
    result.update(json.loads(version['payload']));result['version_id']=version['id']
    result['stale']=drafts.project_stamp(ws,result['project_id'])!=result['source_hash']
    result['dismissed']=bool(ws.db.execute('SELECT 1 FROM outgoing_dismissals WHERE version_id=?',(version['id'],)).fetchone())
    result['receipts']=[{**dict(r),'result':json.loads(r['result']) if r['result'] else None} for r in ws.db.execute(
        'SELECT id,operation,status,result FROM outgoing_plans WHERE action_id=? AND version_id=? ORDER BY rowid DESC',(identity,version['id']))]
    return result


def listing(ws):
    schema(ws)
    return [get(ws,r[0]) for r in ws.db.execute('SELECT id FROM outgoing_actions ORDER BY rowid DESC LIMIT 200').fetchall()]


def edit(ws, identity, version_id, payload):
    current=get(ws,identity);value=clean(payload)
    if value["kind"]!=current["kind"]:raise ValueError("Keep the same action kind when amending a proposal.")
    if current['version_id']!=version_id:raise ValueError('This action changed. Reopen its current version.')
    if any(r['status'] in {'sending','unknown','completed'} for r in current['receipts']):raise ValueError('This version may already be delivered. Resolve it before preparing another action.')
    old={key:current[key] for key in value}
    if old!=value:
        with ws.db:
            ws.db.execute('BEGIN IMMEDIATE')
            latest=ws.db.execute('SELECT id FROM outgoing_versions WHERE action_id=? ORDER BY rowid DESC LIMIT 1',(identity,)).fetchone()[0]
            if latest!=version_id:raise ValueError('This action changed in another view.')
            ws.db.execute('INSERT INTO outgoing_versions VALUES (?,?,?,?)',(uuid.uuid4().hex,identity,json.dumps(value),_now()))
    return get(ws,identity)


def dismiss(ws, identity, version_id):
    current=get(ws,identity)
    if current['version_id']!=version_id or any(r['status'] in {'sending','unknown','completed'} for r in current['receipts']):raise ValueError('Check delivery before dismissing this version.')
    with ws.db:ws.db.execute('INSERT OR IGNORE INTO outgoing_dismissals VALUES (?,?)',(version_id,_now()))
    return get(ws,identity)


def _event_safe(event):
    if event.get('attendees') or event.get('recurrence') or event.get('locked') or event.get('status')=='cancelled' or event.get('eventType','default')!='default':
        raise ValueError('For this release, update only an unlocked personal event without attendees or a recurring series.')


def _busy(client, calendar_id, start, end, exclude=None):
    result=[];cursor=None
    for _ in range(10):
        query={'timeMin':start,'timeMax':end,'singleEvents':'true','maxResults':250}
        if cursor:query['pageToken']=cursor
        page=client.request('calendar','GET','/calendars/'+quote(calendar_id,safe='')+'/events?'+urlencode(query))
        result.extend({'calendar_id':calendar_id,'id':e['id'],'title':e.get('summary','Busy'),'start':e.get('start'),'end':e.get('end')}
            for e in page.get('items',[]) if e.get('id')!=exclude and e.get('status')!='cancelled' and e.get('transparency')!='transparent')
        if not page.get('nextPageToken'):return result
        cursor=page['nextPageToken']
    raise ValueError('Availability results are incomplete. Choose a smaller time window.')


def _availability(client, value):
    calendars=client.calendars()
    if calendars.get('more') or len(calendars['calendars'])>10:raise ValueError('Too many owned calendars to check completely in this preview.')
    if value['calendar_id'] not in {c['id'] for c in calendars['calendars']}:raise ValueError('Choose a calendar you own. Shared-calendar writes are not enabled.')
    conflicts=[]
    for cal in calendars['calendars']:
        conflicts.extend(_busy(client,cal['id'],value['start'],value['end'],value['event_id'] if cal['id']==value['calendar_id'] else None))
    return conflicts


def _prior_deliveries(ws, current):
    """Retain delivery awareness when fresh project context regenerates a proposal."""
    result=[]
    for row in ws.db.execute('SELECT a.id,a.evidence,p.id plan_id,p.operation,p.status,p.result FROM outgoing_actions a '
            'JOIN outgoing_plans p ON p.action_id=a.id WHERE a.project_id=? AND a.record_id=? AND a.id!=? '
            "AND p.status IN ('sending','unknown','completed') ORDER BY p.rowid",(current['project_id'],current['record_id'],current['id'])):
        if json.loads(row['evidence'])['quote']==current['evidence']['quote']:
            if (('email' if current['kind']=='email' else 'calendar' if current['kind'].startswith('calendar_') else current['kind'])!=('email' if row['operation'].startswith('gmail_') else 'calendar' if row['operation'].startswith('calendar_') else 'contact')):continue
            result.append({'plan_id':row['plan_id'],'operation':row['operation'],'status':row['status'],
                           'result':json.loads(row['result']) if row['result'] else None})
    return result


def preview(ws, identity, version_id, operation, client=None):
    current=get(ws,identity)
    if current['version_id']!=version_id or current['stale'] or current['dismissed']:raise ValueError('Use a current, undismissed action with fresh project context.')
    if any(r['status'] in {'sending','unknown','completed'} for r in current['receipts']):raise ValueError('This version may already be delivered. Check its receipt first.')
    client=client or Client(ws);account=client.account()
    value={key:current[key] for key in clean(current)}
    allowed={'email':{'gmail_draft','gmail_send'},'calendar_create':{'calendar_create'},'calendar_update':{'calendar_update'},'contact':{'contact_create'},'text':set()}
    if operation not in allowed[current['kind']]:raise ValueError('Choose an operation matching this proposal. Text messages are copyable drafts only.')
    payload={'account_id':account['account_id'],'account_email':account['email'],'value':value,
             'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat(),'conflicts':[],
             'prior_deliveries':_prior_deliveries(ws,current)}
    if any(r['status']!='completed' for r in payload['prior_deliveries']):
        raise ValueError('A prior follow-up from this passage has an uncertain delivery. Inspect it before preparing another.')
    if operation.startswith('gmail_'):
        addresses(value['to'],True)
        payload['message_id']='<lima.'+fingerprint([identity,version_id])+'@lima.local>'
    elif operation=='contact_create':
        contact_delivery.check_duplicates(client,value)
    else:
        value['start'],value['end']=time_range(value['start'],value['end'],value['timezone'])
        payload['conflicts']=_availability(client,value)
        if operation=='calendar_update':
            if not value['event_id']:raise ValueError('Select the exact personal calendar event to update.')
            before=client.request('calendar','GET','/calendars/'+quote(value['calendar_id'],safe='')+'/events/'+quote(value['event_id'],safe=''))
            _event_safe(before)
            if not before.get('etag'):raise ValueError('Google did not return an event version. Reopen this event.')
            payload['before']={k:before.get(k) for k in ('id','summary','description','start','end','etag')}
        else:payload['event_id']=fingerprint([identity,version_id])
    plan_id=uuid.uuid4().hex
    with ws.db:ws.db.execute('INSERT INTO outgoing_plans VALUES (?,?,?,?,?,?,?,NULL)',(plan_id,identity,version_id,operation,json.dumps(payload),'prepared',_now()))
    return plan(ws,plan_id)


def plan(ws, identity):
    schema(ws);row=ws.db.execute('SELECT * FROM outgoing_plans WHERE id=?',(identity,)).fetchone()
    if not row:raise ValueError('Choose an existing action preview.')
    result=dict(row);result.update(json.loads(result.pop('payload')));result['result']=json.loads(result['result']) if result['result'] else None
    return result


def _raw_email(value, account, message_id):
    message=EmailMessage(policy=policy.SMTP)
    message['From']=account;message['To']=', '.join(value['to'])
    if value['cc']:message['Cc']=', '.join(value['cc'])
    if value['bcc']:message['Bcc']=', '.join(value['bcc'])
    message['Subject']=value['subject'];message['Message-ID']=message_id;message.set_content(value['body'])
    return base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip('=')


def _event_body(value):
    return {'summary':value['subject'],'description':value['body'],
        'start':{'dateTime':value['start'],'timeZone':value['timezone']},'end':{'dateTime':value['end'],'timeZone':value['timezone']}}


def execute(ws, identity, *, confirmed=False, acknowledge_conflicts=False, acknowledge_prior=False, client=None):
    if confirmed is not True:raise ValueError('Confirm the exact content, account and destination first.')
    with LOCK:
        item=plan(ws,identity)
        if item['status']=='completed':return item
        if item['status']!='prepared':raise ValueError('This action may already have happened. Inspect its receipt; it will not be retried automatically.')
        if datetime.fromisoformat(item['expires_at'])<datetime.now(timezone.utc):raise ValueError('This preview expired. Prepare a fresh preview.')
        current=get(ws,item['action_id']);client=client or Client(ws)
        if client.account()['account_id']!=item['account_id']:raise ValueError('The connected Google account changed. Prepare a new preview.')
        if hasattr(client,'ensure_ready'):client.ensure_ready()
        if current['version_id']!=item['version_id'] or current['stale'] or current['dismissed']:raise ValueError('Action or project evidence changed. Prepare a fresh preview.')
        operation=item['operation'];value=item['value']
        if operation.startswith('calendar_'):
            conflicts=_availability(client,value)
            if conflicts and (acknowledge_conflicts is not True or fingerprint(conflicts)!=fingerprint(item['conflicts'])):
                raise ValueError('Calendar conflicts need an explicit acknowledgment in a current preview.')
            if operation=='calendar_update':
                before=client.request('calendar','GET','/calendars/'+quote(value['calendar_id'],safe='')+'/events/'+quote(value['event_id'],safe=''))
                _event_safe(before)
                if before.get('etag')!=item['before']['etag']:raise ValueError('The calendar event changed. Prepare a fresh preview.')
        if operation=='contact_create':contact_delivery.check_duplicates(client,value)
        with ws.db:
            ws.db.execute('BEGIN IMMEDIATE')
            latest=ws.db.execute('SELECT id FROM outgoing_versions WHERE action_id=? ORDER BY rowid DESC LIMIT 1',(item['action_id'],)).fetchone()[0]
            already=ws.db.execute("SELECT 1 FROM outgoing_plans WHERE action_id=? AND version_id=? AND status IN ('sending','unknown','completed')",(item['action_id'],item['version_id'])).fetchone()
            dismissed=ws.db.execute('SELECT 1 FROM outgoing_dismissals WHERE version_id=?',(item['version_id'],)).fetchone()
            prior=_prior_deliveries(ws,current)
            if fingerprint(prior)!=fingerprint(item.get('prior_deliveries',[])) or any(r['status']!='completed' for r in prior) or prior and acknowledge_prior is not True:
                raise ValueError('Earlier follow-ups need review in a current preview before another action from this passage.')
            if already or dismissed or latest!=item['version_id'] or drafts.project_stamp(ws,current['project_id'])!=current['source_hash']:
                raise ValueError('This version changed or may already be delivered. Reopen its receipt.')
            if not ws.db.execute("UPDATE outgoing_plans SET status='sending' WHERE id=? AND status='prepared'",(identity,)).rowcount:raise ValueError('This preview is already being used.')
        write_acknowledged=False
        try:
            if operation.startswith('gmail_'):
                raw=_raw_email(value,item['account_email'],item['message_id'])
                if operation=='gmail_draft':result=client.request('gmail','POST','/users/me/drafts',{'message':{'raw':raw}})
                else:result=client.request('gmail','POST','/users/me/messages/send',{'raw':raw})
                write_acknowledged=True
                receipt={'id':result['id'],'operation':operation,'account':item['account_email'],
                    'url':'https://mail.google.com/mail/?authuser='+quote(item['account_email'],safe='')+('#drafts' if operation=='gmail_draft' else '#sent')}
            elif operation=='contact_create':
                result=client.request('contacts','POST','/people:createContact?personFields=names,emailAddresses,phoneNumbers',contact_delivery.body(value))
                write_acknowledged=True
                resource=contact_delivery.verify(client,result,value)
                receipt={'id':resource,'operation':operation,'account':item['account_email'],'url':'https://contacts.google.com/?authuser='+quote(item['account_email'],safe='')}
            else:
                body=_event_body(value);base='/calendars/'+quote(value['calendar_id'],safe='')+'/events'
                if operation=='calendar_create':
                    body['id']=item['event_id'];body['extendedProperties']={'private':{'limaAction':item['action_id'],'limaVersion':item['version_id']}}
                    result=client.request('calendar','POST',base+'?sendUpdates=none',body)
                else:result=client.request('calendar','PATCH',base+'/'+quote(value['event_id'],safe='')+'?sendUpdates=none',body,headers={'If-Match':item['before']['etag']})
                write_acknowledged=True
                returned=client.request('calendar','GET',base+'/'+quote(result['id'],safe=''))
                if any(returned.get(k,'')!=body[k] for k in ('summary','description')):raise ValueError('Calendar read-back differs from the approved content.')
                for key in ('start','end'):
                    if datetime.fromisoformat(returned[key]['dateTime'].replace('Z','+00:00'))!=datetime.fromisoformat(value[key]):raise ValueError('Calendar read-back time differs.')
                receipt={'id':result['id'],'operation':operation,'account':item['account_email'],'url':'https://calendar.google.com/calendar/r?authuser='+quote(item['account_email'],safe='')}
            with ws.db:ws.db.execute("UPDATE outgoing_plans SET status='completed',result=? WHERE id=?",(json.dumps(receipt),identity))
            return plan(ws,identity)
        except GoogleAPIError as error:
            status='rejected' if not write_acknowledged and error.status in {400,401,403,404,412,429} else 'unknown'
            with ws.db:ws.db.execute('UPDATE outgoing_plans SET status=? WHERE id=?',(status,identity))
            if status=='rejected':raise ValueError(str(error)+' Prepare a fresh preview after fixing it.') from None
            raise ValueError('Delivery is unconfirmed. Inspect Google before any retry.') from None
        except Exception:
            with ws.db:ws.db.execute("UPDATE outgoing_plans SET status='unknown' WHERE id=?",(identity,))
            raise ValueError('Delivery is unconfirmed. Check the destination account before doing anything else. Lima will not resend or overwrite automatically.') from None
