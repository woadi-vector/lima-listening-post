import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch
from lima_next.workspace import Workspace
from lima_next import google_connection as google


class GoogleConnectionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.ws=Workspace(Path(self.folder.name)/'google.db')
        self.crypto=patch('lima_next.google_connection._crypt',side_effect=lambda data,decrypt=False:data);self.crypto.start()
        self.client={'installed':{'client_id':'synthetic.apps.googleusercontent.com','client_secret':'synthetic-desktop-client-secret'}}
        self.oauth=google.GoogleOAuth(Path(self.folder.name)/'google.db','http://127.0.0.1:8765')
    def tearDown(self):self.crypto.stop();self.ws.close();self.folder.cleanup()

    def test_client_configuration_is_desktop_only_and_metadata_never_exposes_secret(self):
        with self.assertRaisesRegex(ValueError,'Desktop'):google.save_client(self.ws,{'web':self.client['installed']})
        with self.assertRaisesRegex(ValueError,'JSON'):google.save_client(self.ws,'bad json')
        result=google.save_client(self.ws,self.client)
        self.assertTrue(result['configured']);self.assertFalse(result['connected'])
        self.assertNotIn('secret',str(result))

    def test_pkce_fixed_endpoint_state_and_no_outward_google_actions_during_connection(self):
        google.save_client(self.ws,self.client)
        url=self.oauth.start(self.ws)['url'];parsed=urlparse(url);values=parse_qs(parsed.query)
        self.assertEqual(parsed.hostname,'accounts.google.com')
        self.assertEqual(values['code_challenge_method'],['S256'])
        self.assertEqual(values['redirect_uri'],['http://127.0.0.1:8765/google/callback'])
        self.assertNotIn('client_secret',url)
        with patch('lima_next.google_connection._request') as request:
            with self.assertRaisesRegex(ValueError,'not started'):self.oauth.callback(self.ws,'state=forged&code=wrong')
            request.assert_not_called()
            request.side_effect=[{'access_token':'synthetic-access','refresh_token':'synthetic-refresh','expires_in':3600,'scope':' '.join(google.SCOPES)},
                                 {'sub':'synthetic-account','email':'owner@example.com','email_verified':True}]
            result=self.oauth.callback(self.ws,'state='+values['state'][0]+'&code=synthetic-code')
            self.assertEqual(result['email'],'owner@example.com');self.assertTrue(result['connected'])
            self.assertEqual(request.call_count,2)
            self.assertIn('code_verifier',request.call_args_list[0].args[2])
            self.assertNotIn('synthetic-refresh',str(result))
        with self.assertRaises(ValueError):self.oauth.callback(self.ws,'state='+values['state'][0]+'&code=synthetic-code')

    def test_contacts_are_an_explicit_optional_authorization(self):
        google.save_client(self.ws,self.client)
        basic=parse_qs(urlparse(self.oauth.start(self.ws)['url']).query)
        self.assertNotIn(google.CONTACT_SCOPE,basic['scope'][0])
        extended=parse_qs(urlparse(self.oauth.start(self.ws,include_contacts=True)['url']).query)
        self.assertIn(google.CONTACT_SCOPE,extended['scope'][0])
        self.assertNotIn(google.CONTACT_SCOPE,google.SCOPES)
        with patch('lima_next.google_connection._request',return_value={'access_token':'synthetic-access','scope':' '.join(google.SCOPES)}):
            with self.assertRaisesRegex(ValueError,'permissions'):self.oauth.callback(self.ws,'state='+extended['state'][0]+'&code=synthetic')
        self.assertFalse(google.state(self.ws)['connected'])

    def test_denied_or_partial_authorization_does_not_connect(self):
        google.save_client(self.ws,self.client)
        values=parse_qs(urlparse(self.oauth.start(self.ws)['url']).query)
        with self.assertRaisesRegex(ValueError,'not authorized'):
            self.oauth.callback(self.ws,'state='+values['state'][0]+'&error=access_denied')
        values=parse_qs(urlparse(self.oauth.start(self.ws)['url']).query)
        with patch('lima_next.google_connection._request',return_value={'access_token':'synthetic-access','scope':'openid email'}):
            with self.assertRaisesRegex(ValueError,'permissions'):self.oauth.callback(self.ws,'state='+values['state'][0]+'&code=synthetic')
        self.assertFalse(google.state(self.ws)['connected'])

    def test_client_pins_account_and_refuses_arbitrary_host(self):
        client=google.Client(self.ws)
        with patch('lima_next.google_connection.state',return_value={'connected':True,'account_id':'one'}):client.account()
        with patch('lima_next.google_connection.state',return_value={'connected':True,'account_id':'two'}):
            with self.assertRaisesRegex(ValueError,'account changed'):client.account()
        with self.assertRaisesRegex(ValueError,'Unsupported'):google._request('https://example.com/token')

    def test_refresh_is_persisted_and_does_not_leak_into_connection_metadata(self):
        google.save_client(self.ws,self.client)
        saved=google._load(self.ws);saved.update(access_token='synthetic-expired',refresh_token='synthetic-refresh',expires_at=0,
            account_id='one',email='owner@example.com',scopes=google.SCOPES);google._save(self.ws,saved)
        with patch('lima_next.google_connection._request',return_value={'access_token':'synthetic-renewed','expires_in':3600}) as request:
            self.assertEqual(google.access_token(self.ws),'synthetic-renewed')
            self.assertEqual(google.access_token(self.ws),'synthetic-renewed')
            self.assertEqual(request.call_count,1)
            self.assertEqual(request.call_args.args[2]['grant_type'],'refresh_token')
            self.assertNotIn('synthetic-refresh',str(google.state(self.ws)))

    def test_expired_sign_in_cannot_exchange_an_authorization_code(self):
        google.save_client(self.ws,self.client)
        values=parse_qs(urlparse(self.oauth.start(self.ws)['url']).query)
        state=values['state'][0];self.oauth.flows[state]['expires']=0
        with patch('lima_next.google_connection._request') as request:
            with self.assertRaisesRegex(ValueError,'expired'):self.oauth.callback(self.ws,'state='+state+'&code=synthetic')
            request.assert_not_called()
