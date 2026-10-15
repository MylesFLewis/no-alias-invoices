import base64
import importlib
import io
import json
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from email import message_from_bytes
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import Request, urlopen

import app
import bootstrap
import invoice_mail
import microsoft_graph as graph

CLIENT='11111111-2222-3333-4444-555555555555'
OTHER_CLIENT='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
OWNER='a'*64
OTHER_OWNER='b'*64


def populate(cache,username='owner@example.com',identifier=CLIENT,home='home-one'):
    cache.deserialize(json.dumps({
        'Account':{'account':{'home_account_id':home,'username':username,'environment':'login.microsoftonline.com','realm':'consumers'}},
        'RefreshToken':{'refresh':{'home_account_id':home,'client_id':identifier,'secret':'PRIVATE-REFRESH-TOKEN'}},
        'AccessToken':{'access':{'home_account_id':home,'client_id':identifier,'secret':'PRIVATE-ACCESS-TOKEN'}}}))
    cache.has_state_changed=True


class FakeApplication:
    def __init__(self,identifier,cache):self.identifier=identifier;self.cache=cache;self.username='owner@example.com'
    def initiate_device_flow(self,scopes):
        return {'user_code':'ABCD-EFGH','device_code':'PRIVATE-DEVICE-CODE','verification_uri':graph.VERIFY_URL,
                'expires_in':900,'expires_at':time.time()+900,'interval':5}
    def acquire_token_by_device_flow(self,flow,**kwargs):
        populate(self.cache,self.username,self.identifier)
        return {'access_token':'PRIVATE-ACCESS-TOKEN','scope':'Mail.Send openid offline_access'}
    def get_accounts(self):return list(self.cache.search(graph.msal.TokenCache.CredentialType.ACCOUNT))
    def acquire_token_silent(self,scopes,account):return {'access_token':'PRIVATE-ACCESS-TOKEN'}


class ConnectionFixture(unittest.TestCase):
    def setUp(self):
        self.environment=dict(os.environ);self.temp=tempfile.TemporaryDirectory()
        os.environ.update(DATA_DIR=self.temp.name,EMAIL_PROVIDER='microsoft_graph',MICROSOFT_CLIENT_ID=CLIENT)
        os.environ.pop('MICROSOFT_SENDER',None)
        graph.FLOW=None;graph.LAST_START=0
        self.created=[]
        def factory(identifier,cache):
            application=FakeApplication(identifier,cache);self.created.append(application);return application
        self.factory=patch('microsoft_graph._app',side_effect=factory);self.factory.start()
    def tearDown(self):
        graph.FLOW=None;self.factory.stop();os.environ.clear();os.environ.update(self.environment);self.temp.cleanup()
    def ready(self,username='owner@example.com'):
        graph.start(CLIENT,OWNER);self.created[-1].username=username;graph.FLOW['next_poll']=0
        result=graph.poll(CLIENT,OWNER);self.assertEqual(result['status'],'ready');return result
    def connected(self,username='owner@example.com'):
        self.ready(username);return graph.confirm(CLIENT,OWNER,username)
    def legacy(self):
        cache=graph.msal.SerializableTokenCache();populate(cache)
        graph._cache_path().write_text(cache.serialize())

class MicrosoftConnectionTests(ConnectionFixture):
    def test_personal_account_uses_provider_link_for_code(self):
        original=FakeApplication.initiate_device_flow
        def personal(application,scopes):
            result=original(application,scopes)
            result['verification_uri']='https://www.microsoft.com/link'
            return result
        with patch.object(FakeApplication,'initiate_device_flow',personal):
            started=graph.start(CLIENT,OWNER)
        self.assertEqual(started['verification_uri'],'https://www.microsoft.com/link')
        self.assertEqual(graph.poll(CLIENT,OWNER)['verification_uri'],'https://www.microsoft.com/link')

    def test_untrusted_verification_links_are_rejected(self):
        original=FakeApplication.initiate_device_flow
        for uri in [None,'https://evil.example/link','javascript:alert(1)','http://www.microsoft.com/link',
                    'https://www.microsoft.com.evil.example/link','https://evil@www.microsoft.com/link',
                    'https://www.microsoft.com:443/link','https://www.microsoft.com/link?redirect=evil',
                    'https://www.microsoft.com/link#evil']:
            def bad(application,scopes):
                result=original(application,scopes);result['verification_uri']=uri;return result
            graph.LAST_START=0
            with patch.object(FakeApplication,'initiate_device_flow',bad):
                with self.assertRaises(ValueError):graph.start(CLIENT,OWNER)
            self.assertIsNone(graph.FLOW)
        self.assertFalse(graph._cache_path().exists())

    def test_connect_requires_explicit_mailbox_confirmation_and_hides_secrets(self):
        started=graph.start(CLIENT,OWNER)
        self.assertEqual(started['verification_uri'],'https://microsoft.com/devicelogin')
        self.assertEqual(started['user_code'],'ABCD-EFGH')
        self.assertNotIn('PRIVATE',json.dumps(started));self.assertFalse(graph._cache_path().exists())
        graph.FLOW['next_poll']=0;ready=graph.poll(CLIENT,OWNER)
        self.assertEqual(ready['username'],'owner@example.com');self.assertNotIn('PRIVATE',json.dumps(ready))
        self.assertFalse(graph._cache_path().exists())
        self.assertEqual(graph.confirm(CLIENT,OWNER,'owner@example.com')['username'],'owner@example.com')
        self.assertEqual(graph.connection_info()['username'],'owner@example.com')
        self.assertEqual(graph.access_token(CLIENT),'PRIVATE-ACCESS-TOKEN')
        self.assertEqual(stat.S_IMODE(graph._cache_path().stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE((Path(self.temp.name)/'microsoft-account.json').stat().st_mode),0o600)
        self.assertIsNone(graph.FLOW)

    def test_wrong_browser_cannot_read_code_confirm_or_cancel(self):
        graph.start(CLIENT,OWNER)
        self.assertEqual(graph.poll(CLIENT,OTHER_OWNER),{'status':'other_browser'})
        with self.assertRaises(ValueError):graph.start(CLIENT,OTHER_OWNER)
        with self.assertRaises(ValueError):graph.cancel(OTHER_OWNER)
        graph.FLOW['next_poll']=0;graph.poll(CLIENT,OWNER)
        with self.assertRaises(ValueError):graph.confirm(CLIENT,OTHER_OWNER,'owner@example.com')
        self.assertFalse(graph._cache_path().exists())
        with self.assertRaises(ValueError):graph.poll(CLIENT,'invalid')

    def test_poll_interval_slow_down_expiry_and_declined(self):
        graph.start(CLIENT,OWNER)
        application=self.created[-1]
        with patch.object(application,'acquire_token_by_device_flow',return_value={'error':'authorization_pending'}) as poll:
            self.assertEqual(graph.poll(CLIENT,OWNER)['status'],'pending');poll.assert_not_called()
            graph.FLOW['next_poll']=0
            self.assertEqual(graph.poll(CLIENT,OWNER)['status'],'pending');poll.assert_called_once()
            graph.poll(CLIENT,OWNER);poll.assert_called_once()
        def slow(flow,**kwargs):flow['interval']=10;return {'error':'slow_down'}
        graph.FLOW['next_poll']=0
        with patch.object(application,'acquire_token_by_device_flow',side_effect=slow):
            result=graph.poll(CLIENT,OWNER);self.assertGreaterEqual(result['retry_after'],10)
        graph.FLOW['next_poll']=0
        with patch.object(application,'acquire_token_by_device_flow',return_value={'error':'authorization_declined','error_description':'PRIVATE-ERROR'}):
            result=graph.poll(CLIENT,OWNER)
        self.assertEqual(result['status'],'failed');self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn('cache',graph.FLOW);graph.FLOW['expires_at']=0
        self.assertEqual(graph.poll(CLIENT,OWNER),{'status':'idle'})

    def test_cancel_and_restart_keep_existing_legacy_connection(self):
        self.legacy();original=graph._cache_path().read_bytes()
        self.ready('dad@example.com');graph.cancel(OWNER)
        self.assertEqual(graph._cache_path().read_bytes(),original)
        self.assertEqual(graph.connection_info()['username'],'owner@example.com')
        graph.LAST_START=0;self.ready('dad@example.com');graph.FLOW=None
        self.assertEqual(graph.poll(CLIENT,OWNER),{'status':'idle'})
        self.assertEqual(graph._cache_path().read_bytes(),original)
        self.assertEqual(graph.access_token(CLIENT),'PRIVATE-ACCESS-TOKEN')

    def test_disconnect_prevents_late_poll_from_restoring_tokens(self):
        self.legacy();graph.start(CLIENT,OWNER);graph.FLOW['next_poll']=0
        entered=threading.Event();release=threading.Event();application=self.created[-1]
        original=application.acquire_token_by_device_flow
        def delayed(*args,**kwargs):entered.set();release.wait(5);return original(*args,**kwargs)
        with patch.object(application,'acquire_token_by_device_flow',side_effect=delayed),ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(graph.poll,CLIENT,OWNER);self.assertTrue(entered.wait(2))
            graph.disconnect();release.set();self.assertEqual(pending.result(),{'status':'idle'})
        self.assertFalse(graph._cache_path().exists());self.assertIsNone(graph.connection_info())

    def test_generation_client_and_sender_changes_fail_closed(self):
        self.ready()
        with graph.storage_lock():graph._set_metadata({'generation':1})
        with self.assertRaises(ValueError):graph.confirm(CLIENT,OWNER,'owner@example.com')
        self.assertFalse(graph._cache_path().exists())
        graph.LAST_START=0;self.ready()
        with self.assertRaises(ValueError):graph.confirm(OTHER_CLIENT,OWNER,'owner@example.com')
        os.environ['MICROSOFT_SENDER']='different@example.com'
        with self.assertRaises(ValueError):graph.confirm(CLIENT,OWNER,'owner@example.com')
        self.assertFalse(graph._cache_path().exists())
        os.environ['MICROSOFT_SENDER']='OWNER@example.com'
        graph.confirm(CLIENT,OWNER,'owner@example.com')
        self.assertIsNone(graph.connection_info(OTHER_CLIENT))

    def test_missing_permissions_or_malformed_identity_never_persist(self):
        graph.start(CLIENT,OWNER);graph.FLOW['next_poll']=0
        with patch.object(self.created[-1],'acquire_token_by_device_flow',return_value={'access_token':'PRIVATE','scope':'User.Read'}):
            with self.assertRaises(ValueError):graph.poll(CLIENT,OWNER)
        self.assertFalse(graph._cache_path().exists());self.assertNotIn('cache',graph.FLOW)
        graph.cancel(OWNER);graph.LAST_START=0;graph.start(CLIENT,OWNER);graph.FLOW['next_poll']=0
        self.created[-1].username='wrong\r\nBcc:evil@example.com'
        with self.assertRaises(ValueError):graph.poll(CLIENT,OWNER)
        self.assertFalse(graph._cache_path().exists())

    def test_network_and_provider_errors_are_safe(self):
        with patch.object(FakeApplication,'initiate_device_flow',side_effect=RuntimeError('PRIVATE-SECRET')):
            with self.assertRaises(ValueError) as caught:graph.start(CLIENT,OWNER)
        self.assertNotIn('PRIVATE',str(caught.exception));self.assertIsNone(graph.FLOW)
        graph.LAST_START=0;graph.start(CLIENT,OWNER);graph.FLOW['next_poll']=0
        with patch.object(self.created[-1],'acquire_token_by_device_flow',side_effect=RuntimeError('PRIVATE-SECRET')):
            result=graph.poll(CLIENT,OWNER)
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertEqual(result['status'],'pending')
        self.assertGreaterEqual(result['retry_after'],15)

    def test_same_registration_separate_data_directories_are_independent(self):
        self.connected();first=graph._cache_path();first_content=first.read_bytes()
        with tempfile.TemporaryDirectory() as dad:
            os.environ['DATA_DIR']=dad;graph.LAST_START=0
            self.assertIsNone(graph.connection_info())
            self.connected('dad@example.com')
            self.assertEqual(graph.connection_info()['username'],'dad@example.com')
            graph.disconnect();self.assertIsNone(graph.connection_info())
        os.environ['DATA_DIR']=self.temp.name
        self.assertEqual(first.read_bytes(),first_content)
        self.assertEqual(graph.connection_info()['username'],'owner@example.com')

    def test_legacy_cache_selection_refresh_and_private_atomic_save(self):
        self.legacy();self.assertFalse((Path(self.temp.name)/'microsoft-account.json').exists())
        self.assertEqual(graph.connection_info()['username'],'owner@example.com')
        def refresh(scopes,account):
            application=self.created[-1];populate(application.cache)
            return {'access_token':'renewed'}
        with patch.object(FakeApplication,'acquire_token_silent',side_effect=refresh):
            self.assertEqual(graph.access_token(CLIENT),'renewed')
        self.assertEqual(stat.S_IMODE(graph._cache_path().stat().st_mode),0o600)
        self.assertFalse(list(Path(self.temp.name).glob('.microsoft-*')))
        graph._cache_path().write_text('{broken')
        with self.assertRaises(RuntimeError) as caught:graph.connection_info()
        self.assertNotIn('{broken',str(caught.exception))

    def test_status_does_not_refresh_or_disclose_tokens(self):
        self.legacy()
        with patch('microsoft_graph._app',side_effect=AssertionError('Status must not access Microsoft')):
            info=app.microsoft_status();status=bootstrap.configuration_status()
        self.assertTrue(info['connected']);self.assertTrue(status['configured'])
        self.assertNotIn('PRIVATE',json.dumps(info)+json.dumps(status))

    def test_graph_mime_submission_fixed_endpoint_no_redirects_or_error_body(self):
        response=MagicMock();response.__enter__.return_value.status=202
        opener=MagicMock();opener.open.return_value=response
        with patch('microsoft_graph.access_token',return_value='PRIVATE-TOKEN'),patch('microsoft_graph.urllib.request.build_opener',return_value=opener) as builder:
            self.assertEqual(graph.send_mime(CLIENT,b'Exact MIME'),202)
        self.assertIsInstance(builder.call_args.args[0],graph.NoRedirect)
        request=opener.open.call_args.args[0];self.assertEqual(request.full_url,graph.GRAPH_SEND)
        self.assertEqual(base64.b64decode(request.data),b'Exact MIME')
        self.assertEqual(opener.open.call_args.kwargs['timeout'],20)
        error=urllib.error.HTTPError(graph.GRAPH_SEND,403,'forbidden',{},io.BytesIO(b'PRIVATE-ERROR-BODY'))
        opener.open.side_effect=error
        with patch('microsoft_graph.access_token',return_value='PRIVATE-TOKEN'),patch('microsoft_graph.urllib.request.build_opener',return_value=opener):
            with self.assertRaises(graph.GraphRejected) as caught:graph.send_mime(CLIENT,b'MIME')
        self.assertIn('403',str(caught.exception));self.assertNotIn('PRIVATE',str(caught.exception))
        self.assertIsNone(graph.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example'))

    def test_delivery_uses_connected_sender_and_exact_attachment(self):
        self.connected('dad@example.com')
        job={'recipient':'customer@example.com','message_id':'<test@example.com>'}
        with patch('microsoft_graph.access_token',return_value='PRIVATE'),patch('microsoft_graph.send_mime',return_value=202) as send:
            bootstrap.deliver(job,b'%PDF saved','LEA0169',{'business':'Maintenance business'})
        message=message_from_bytes(send.call_args.args[1])
        self.assertEqual(message['From'],'dad@example.com');self.assertEqual(message['To'],'customer@example.com')
        attachment=message.get_payload()[-1];self.assertEqual(attachment.get_payload(decode=True),b'%PDF saved')
        self.assertEqual(attachment.get_filename(),'LEA0169 Invoice.pdf')

    def test_failed_refresh_is_definite_and_submission_timeout_uncertain(self):
        self.connected();job={'recipient':'customer@example.com','message_id':'<test@example.com>'}
        with patch('microsoft_graph.access_token',side_effect=RuntimeError('PRIVATE')):
            with self.assertRaises(invoice_mail.DeliveryError) as caught:bootstrap.deliver(job,b'%PDF saved','0001',{})
        self.assertFalse(caught.exception.uncertain);self.assertNotIn('PRIVATE',str(caught.exception))
        with patch('microsoft_graph.access_token',return_value='PRIVATE'),patch('microsoft_graph.send_mime',side_effect=TimeoutError('PRIVATE')):
            with self.assertRaises(invoice_mail.DeliveryError) as caught:bootstrap.deliver(job,b'%PDF saved','0001',{})
        self.assertTrue(caught.exception.uncertain);self.assertNotIn('PRIVATE',str(caught.exception))


class MicrosoftEndpointTests(ConnectionFixture):
    def setUp(self):
        super().setUp();importlib.reload(app)
        self.kick=patch('app.invoice_mail.kick');self.kick.start()
        class QuietHandler(app.Handler):
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.kick.stop();super().tearDown()
    def post(self,action,body=None,origin=None,content_type='application/json'):
        headers={'Content-Type':content_type}
        if origin:headers['Origin']=origin
        request=Request(self.url+'/api/microsoft/'+action,data=json.dumps(body or {'owner':OWNER}).encode(),headers=headers)
        try:
            with urlopen(request,timeout=5) as response:return response.status,json.loads(response.read())
        except urllib.error.HTTPError as response:return response.code,json.loads(response.read())
    def test_endpoint_confirmation_csrf_and_queued_mail_guards(self):
        self.assertEqual(self.post('start',origin='https://evil.example')[0],403)
        self.assertEqual(self.post('start',content_type='text/plain')[0],415)
        self.assertEqual(self.post('start',{'owner':'bad'})[0],400)
        self.assertEqual(self.post('start')[0],200);graph.FLOW['next_poll']=0
        self.assertEqual(self.post('status')[1]['status'],'ready')
        self.assertEqual(self.post('confirm',{'owner':OWNER,'username':'owner@example.com'})[0],400)
        with app.connection() as c:c.execute("INSERT INTO invoice_mail VALUES(1,'customer@example.com','pending',0,0,'','<id>')")
        self.assertEqual(self.post('confirm',{'owner':OWNER,'username':'owner@example.com','confirmed':True})[0],400)
        self.assertEqual(self.post('disconnect',{'confirmed':True})[0],400)
        with app.connection() as c:c.execute('DELETE FROM invoice_mail')
        self.assertEqual(self.post('confirm',{'owner':OWNER,'username':'owner@example.com','confirmed':True})[0],200)
        with urlopen(self.url+'/api/state') as response:state=json.loads(response.read())
        self.assertEqual(state['microsoft']['username'],'owner@example.com');self.assertNotIn('PRIVATE',json.dumps(state))
        self.assertEqual(self.post('disconnect',{'confirmed':True})[0],200)
        self.assertIsNone(graph.connection_info())
    def test_smtp_mode_does_not_start_microsoft_authentication(self):
        os.environ['EMAIL_PROVIDER']='smtp'
        self.assertEqual(self.post('start')[0],400)
        self.assertFalse(self.created)


class InterfaceVersionTests(unittest.TestCase):
    def test_displayed_version_matches_release(self):
        root=Path(__file__).resolve().parents[1]
        version=(root/'VERSION').read_text().strip()
        page=(root/'static/index.html').read_text()
        self.assertIn('INVOICE APP · v'+version,page)
        self.assertIn('current version v'+version,page)


if __name__=='__main__':unittest.main()
