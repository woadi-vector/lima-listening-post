"""Dedicated desktop Google OAuth with PKCE and protected local credentials."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, urlparse, parse_qs
from urllib.request import Request, build_opener, ProxyHandler

from .interpret import NoRedirect
from .notion_delivery import _crypt

SCOPES=['openid','email','https://www.googleapis.com/auth/gmail.compose',
        'https://www.googleapis.com/auth/calendar.events.owned',
        'https://www.googleapis.com/auth/calendar.calendarlist.readonly']
CONTACT_SCOPE='https://www.googleapis.com/auth/contacts'
LOCK=threading.RLock()


class GoogleAPIError(ValueError):
    def __init__(self, message, status):
        super().__init__(message);self.status=status


def _path(ws):return Path(ws.db.execute('PRAGMA database_list').fetchone()[2]+'.google.dpapi')


def _load(ws):
    path=_path(ws)
    if not path.exists():return {}
    try:return json.loads(_crypt(path.read_bytes(),True).decode())
    except (ValueError,OSError,UnicodeError,json.JSONDecodeError):
        raise ValueError('Lima could not unlock its Google connection. Reconnect from Settings.') from None


def _save(ws, value):
    path=_path(ws);temporary=path.with_suffix('.tmp')
    try:encrypted=_crypt(json.dumps(value).encode())
    except ValueError:
        raise ValueError('Local Google credential setup currently requires Windows.' if os.name!='nt' else 'Windows could not protect the Google credential for this account.') from None
    temporary.write_bytes(encrypted);temporary.replace(path)


def _request(url, method='GET', data=None, headers=None, form=False):
    if urlparse(url).hostname not in {'oauth2.googleapis.com','openidconnect.googleapis.com','gmail.googleapis.com','www.googleapis.com','people.googleapis.com'}:
        raise ValueError('Unsupported Google API destination')
    body=urlencode(data).encode() if form else json.dumps(data).encode() if data is not None else None
    request=Request(url,data=body,method=method,headers={**(headers or {}),
        **({'Content-Type':'application/x-www-form-urlencoded' if form else 'application/json'} if body is not None else {})})
    try:
        with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=30) as response:
            body=response.read(3000001)
        if len(body)>3000000:raise ValueError('Google response exceeded the size limit')
        return json.loads(body) if body else {}
    except HTTPError as error:
        # Do not include provider bodies, URLs with codes, tokens, or message contents.
        raise GoogleAPIError({400:'Google rejected this request. Check setup or reconnect if authorization expired.',
            401:'Google authorization expired or was revoked. Reconnect Lima.',403:'Google denied this action. Check API enablement, account scopes and calendar ownership.',
            404:'The Google draft or event could not be found.',409:'That Google item already exists. Check delivery before retrying.',
            412:'The calendar event changed. Prepare a new preview.',429:'Google rate limit reached. Try later.'}.get(error.code,f'Google request failed (HTTP {error.code}).'),error.code) from None
    except (URLError,OSError,TimeoutError,json.JSONDecodeError):
        raise ValueError('Google is unavailable or returned an unreadable response.') from None


def state(ws):
    value=_load(ws)
    return {'configured':bool(value.get('client_id')),'connected':bool(value.get('refresh_token') or value.get('access_token')),
            'email':value.get('email',''),'account_id':value.get('account_id',''),'scopes':value.get('scopes',[])}


def save_client(ws, client_json):
    if isinstance(client_json,str):
        try:client_json=json.loads(client_json)
        except json.JSONDecodeError:raise ValueError('Choose the downloaded Google Desktop OAuth JSON file.') from None
    installed=client_json.get('installed') if isinstance(client_json,dict) else None
    if not isinstance(installed,dict):raise ValueError('Use a Desktop app OAuth client, not a web client or service account.')
    identity=installed.get('client_id');secret=installed.get('client_secret')
    if not isinstance(identity,str) or len(identity)>300 or not identity.endswith('.apps.googleusercontent.com') or not isinstance(secret,str) or not 8<=len(secret)<=500:
        raise ValueError('The Desktop OAuth client JSON is incomplete.')
    with LOCK:
        prior=_load(ws)
        if prior.get('client_id')!=identity:prior={}
        prior.update(client_id=identity,client_secret=secret)
        _save(ws,prior)
    return state(ws)


def access_token(ws):
    with LOCK:
        saved=_load(ws)
        if not saved.get('access_token'):raise ValueError('Connect Lima to Google first.')
        if saved.get('expires_at',0)<=time.time()+60:
            if not saved.get('refresh_token'):raise ValueError('Reconnect Google to continue.')
            result=_request('https://oauth2.googleapis.com/token','POST',{'grant_type':'refresh_token',
                'refresh_token':saved['refresh_token'],'client_id':saved['client_id'],'client_secret':saved['client_secret']},form=True)
            if not isinstance(result.get('access_token'),str):raise ValueError('Google did not refresh authorization. Reconnect Lima.')
            saved.update(access_token=result['access_token'],expires_at=time.time()+int(result.get('expires_in',3600)))
            _save(ws,saved)
        return saved['access_token']


class GoogleOAuth:
    def __init__(self, db_path, origin):
        self.path,self.origin=db_path,origin;self.flows={};self.lock=threading.RLock()

    def start(self, ws, *, include_contacts=False):
        if type(include_contacts) is not bool:raise ValueError("Choose whether to enable Google Contacts.")
        requested=SCOPES+([CONTACT_SCOPE] if include_contacts else [])
        saved=_load(ws)
        if not saved.get('client_id'):raise ValueError('Load your dedicated Lima Desktop OAuth JSON first.')
        verifier=secrets.token_urlsafe(48);state_value=secrets.token_urlsafe(32)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self.lock:
            self.flows={key:value for key,value in self.flows.items() if value['expires']>time.time()}
            self.flows[state_value]={'verifier':verifier,'expires':time.time()+600,'client_id':saved['client_id'],'required_scopes':requested}
        return {'url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode({'client_id':saved['client_id'],
            'redirect_uri':self.origin+'/google/callback','response_type':'code','scope':' '.join(requested),
            'state':state_value,'code_challenge':challenge,'code_challenge_method':'S256',
            'access_type':'offline','prompt':'consent','include_granted_scopes':'false'})}

    def callback(self, ws, query):
        values=parse_qs(query)
        received=values.get('state',[''])[0]
        with self.lock:
            matching=next((key for key in self.flows if hmac.compare_digest(received,key)),None)
            flow=self.flows.pop(matching,None) if matching else None
        if not flow or flow['expires']<time.time():raise ValueError('Google sign-in expired or was not started by this Lima window. Start again.')
        if values.get('error'):raise ValueError('Google connection was not authorized. Your local workspace is unchanged.')
        code=values.get('code',[''])[0]
        if not code or len(code)>5000:raise ValueError('Google did not return a usable authorization code.')
        with LOCK:
            saved=_load(ws)
            if saved.get('client_id')!=flow['client_id']:raise ValueError('Google client changed during sign-in. Start again.')
            result=_request('https://oauth2.googleapis.com/token','POST',{'grant_type':'authorization_code','code':code,
                'client_id':saved['client_id'],'client_secret':saved['client_secret'],'code_verifier':flow['verifier'],
                'redirect_uri':self.origin+'/google/callback'},form=True)
            if not isinstance(result.get('access_token'),str):raise ValueError('Google did not complete authorization.')
            granted=set(result.get('scope','').split())
            required=set(flow.get('required_scopes',SCOPES))-{'openid','email'}
            if not required<=granted:raise ValueError('The requested Google permissions were not all granted. Reconnect and review the requested scopes.')
            profile=_request('https://openidconnect.googleapis.com/v1/userinfo',headers={'Authorization':'Bearer '+result['access_token']})
            if not profile.get('sub') or not profile.get('email') or not profile.get('email_verified'):
                raise ValueError('Google did not verify the connected account.')
            # Do not carry a different account's refresh token into a new sign-in.
            refresh=result.get('refresh_token') or (saved.get('refresh_token') if saved.get('account_id')==profile['sub'] else None)
            if not refresh:raise ValueError('Google did not grant offline access. Reconnect with consent.')
            saved.update(access_token=result['access_token'],refresh_token=refresh,
                expires_at=time.time()+int(result.get('expires_in',3600)),email=profile['email'],account_id=profile['sub'],scopes=sorted(granted))
            _save(ws,saved)
        return state(ws)


class Client:
    def __init__(self, ws):self.ws=ws;self.expected_account=None
    def account(self):
        value=state(self.ws)
        if not value['connected']:raise ValueError('Connect Lima to Google first.')
        if self.expected_account and value['account_id']!=self.expected_account:raise ValueError('The connected Google account changed. Reopen the preview.')
        self.expected_account=value['account_id']
        return value
    def ensure_ready(self):
        with LOCK:
            self.account();access_token(self.ws)
    def request(self, service, method, path, data=None, headers=None):
        bases={'gmail':'https://gmail.googleapis.com/gmail/v1','calendar':'https://www.googleapis.com/calendar/v3','contacts':'https://people.googleapis.com/v1'}
        if service not in bases or not path.startswith('/') or '://' in path:raise ValueError('Invalid Google API request')
        with LOCK:
            self.account()
            if service=='contacts' and CONTACT_SCOPE not in state(self.ws)['scopes']:raise ValueError('Enable the People API and reconnect with Google Contacts permission on the Lima computer first.')
            return _request(bases[service]+path,method,data,{'Authorization':'Bearer '+access_token(self.ws),**(headers or {})})

    def calendars(self):
        result=self.request('calendar','GET','/users/me/calendarList?minAccessRole=owner&maxResults=250')
        return {'calendars':[{'id':c['id'],'name':c.get('summary','Calendar'),'timezone':c.get('timeZone','America/Chicago')}
            for c in result.get('items',[]) if c.get('accessRole')=='owner' and not c.get('deleted')],
            'more':bool(result.get('nextPageToken'))}

    def events(self, calendar_id, start, end, zone='America/Chicago'):
        from .outgoing_actions import time_range
        if calendar_id not in {c['id'] for c in self.calendars()['calendars']}:
            raise ValueError('Select a calendar you own for personal-event lookup.')
        start,end=time_range(start,end,zone)
        result=self.request('calendar','GET','/calendars/'+quote(calendar_id,safe='')+'/events?'+urlencode({
            'timeMin':start,'timeMax':end,'singleEvents':'true','orderBy':'startTime','maxResults':100}))
        return {'events':[{'id':e['id'],'title':e.get('summary','Untitled event'),'start':e.get('start'),
                'end':e.get('end'),'can_update':not e.get('attendees') and not e.get('recurrence') and not e.get('locked')}
            for e in result.get('items',[]) if e.get('status')!='cancelled'],'more':bool(result.get('nextPageToken'))}
