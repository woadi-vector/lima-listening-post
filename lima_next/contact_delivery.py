"""Personal Google contact creation with exact previews and duplicate holds."""
import re
from urllib.parse import urlencode,quote


def phone(value):
    if not value:return ''
    if not isinstance(value,str) or not re.fullmatch(r'\+[1-9][0-9]{6,14}',value):
        raise ValueError('Use an explicit international phone number, such as +15551234567. Do not guess its country code.')
    return value


def body(value):
    if not value.get('contact_name') or not (value.get('contact_email') or value.get('phone')):
        raise ValueError('Confirm the contact name and at least one email or international phone number.')
    result={'names':[{'givenName':value['contact_name']}]}
    if value['contact_email']:result['emailAddresses']=[{'value':value['contact_email']}]
    if value['phone']:result['phoneNumbers']=[{'value':phone(value['phone'])}]
    return result


def check_duplicates(client,value):
    body(value);cursor=None
    for _ in range(10):
        params={'personFields':'names,emailAddresses,phoneNumbers','pageSize':1000,'sources':'READ_SOURCE_TYPE_CONTACT'}
        if cursor:params['pageToken']=cursor
        result=client.request('contacts','GET','/people/me/connections?'+urlencode(params))
        for person in result.get('connections',[]):
            names={n.get('displayName','').casefold() for n in person.get('names',[])}|{n.get('givenName','').casefold() for n in person.get('names',[])}
            emails={e.get('value','').casefold() for e in person.get('emailAddresses',[])}
            phones={re.sub(r'\D','',p.get('canonicalForm') or p.get('value','')) for p in person.get('phoneNumbers',[])}
            if (value['contact_name'].casefold() in names or value['contact_email'] and value['contact_email'].casefold() in emails
                    or value['phone'] and re.sub(r'\D','',value['phone']) in phones):
                raise ValueError('A matching name, email or phone already exists in Google Contacts. Inspect it there; Lima will not create or merge a duplicate.')
        cursor=result.get('nextPageToken')
        if not cursor:return
    raise ValueError('The contact duplicate check was incomplete. Inspect Google Contacts before creating this contact.')


def verify(client,result,value):
    identity=result.get('resourceName','')
    if not re.fullmatch(r'people/[A-Za-z0-9_-]+',identity):raise ValueError('Google did not return a usable contact receipt.')
    returned=client.request('contacts','GET','/'+quote(identity,safe='/')+'?personFields=names,emailAddresses,phoneNumbers')
    names={n.get('givenName','') for n in returned.get('names',[])}|{n.get('displayName','') for n in returned.get('names',[])}
    if value['contact_name'] not in names:raise ValueError('Contact name read-back differs from the approved name.')
    if value['contact_email'] and value['contact_email'].casefold() not in {e.get('value','').casefold() for e in returned.get('emailAddresses',[])}:raise ValueError('Contact email read-back differs.')
    if value['phone'] and re.sub(r'\D','',value['phone']) not in {re.sub(r'\D','',p.get('canonicalForm') or p.get('value','')) for p in returned.get('phoneNumbers',[])}:raise ValueError('Contact phone read-back differs.')
    return identity
