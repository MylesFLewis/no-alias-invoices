import importlib
import json
import os
import tempfile
import threading
import unittest
from email import message_from_bytes
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
import bootstrap
import email_templates as templates
import invoice_mail


class TemplateUnitTests(unittest.TestCase):
    def test_sanitizer_removes_active_content_and_unsafe_urls(self):
        source='''<script>BAD_SCRIPT</script><style>BAD_STYLE</style><iframe src="https://evil.example">BAD_FRAME</iframe>
        <svg><a href="javascript:bad">BAD_SVG</a></svg><form action="https://evil.example"><input></form>
        <p id="save" onclick="bad()" style="color:#123456;position:fixed;background-image:url(https://evil.example)">Safe <b>bold</b></p>
        <a href="jav&#x61;script:bad()">bad link</a><a href="//evil.example">relative</a>
        <img src="data:image/svg+xml,bad" onerror="bad()"><a href="https://example.com">Good</a>'''
        result=templates.clean_html(source)
        for value in ['<script','<style','<iframe','<svg','<form','<input','onclick','onerror','position:','background-image:','javascript:','data:image','BAD_SCRIPT','BAD_STYLE','BAD_FRAME','BAD_SVG']:
            self.assertNotIn(value,result)
        self.assertIn('color:#123456',result);self.assertIn('<b>bold</b>',result)
        self.assertIn('href="https://example.com"',result)

    def test_images_links_and_basic_formatting_survive(self):
        source='<h2>Invoice</h2><p style="text-align:center"><strong>Bold</strong><em>Italic</em><u>Underlined</u></p><ul><li>One</li></ul><img src="https://example.com/logo.png" alt="Logo" width="200"><a href="mailto:hello@example.com">Email</a>'
        result=templates.clean_html(source)
        for value in ['<h2>','<strong>','<em>','<u>','<ul>','<li>','text-align:center','width="200"','https://example.com/logo.png','mailto:hello@example.com']:
            self.assertIn(value,result)
        self.assertIn('[Logo]',templates.plain_text(result));self.assertIn('• One',templates.plain_text(result))

    def test_field_validation_limits_and_no_template_execution(self):
        for subject,body in [('', '<p>Body</p>'),('a\r\nBcc:evil@example.com','<p>Body</p>'),
                             ('Subject','<script>only script</script>'),('Subject','<p>{{unknown}}</p>'),
                             ('Subject','<p>{{business_name.__class__}}</p>'),('Subject','x'*30001)]:
            with self.assertRaises(ValueError):templates.validate(subject,body)
        with self.assertRaises(ValueError):templates.validate('{{invoice_number}}'*101,'Body')

    def test_values_are_escaped_and_subject_fields_cannot_inject_headers(self):
        result=templates.render('Invoice {{business_name}}','<p>{{client_name}}</p><p>{{business_name}}</p>',
            {'client_name':'<img src=x onerror=bad()>','business_name':'Name\r\nBcc:attacker@example.com\x00'})
        self.assertNotIn('\r',result['subject']);self.assertNotIn('\n',result['subject']);self.assertNotIn('\x00',result['subject'])
        self.assertNotIn('<img src=x',result['html']);self.assertIn('&lt;img',result['html'])
        self.assertIn('<img src=x',result['plain'])
        self.assertIn('Content-Security-Policy',result['html']);self.assertIn("default-src 'none'",result['html'])

    def test_sample_context_dates_and_money(self):
        sample=templates.preview('Invoice {{invoice_number}} to {{client_name}}','<p>{{invoice_date}} / {{due_date}} / {{amount_due}}</p>')
        self.assertEqual(sample['subject'],'Invoice DEMO0169 to Alex Example')
        self.assertIn('16/10/2026',sample['plain']);self.assertIn('30/10/2026',sample['plain']);self.assertIn('£200.00',sample['plain'])


class TemplateEndpointTests(unittest.TestCase):
    def setUp(self):
        self.environment=dict(os.environ);self.temp=tempfile.TemporaryDirectory()
        os.environ.update(DATA_DIR=self.temp.name,EMAIL_PROVIDER='smtp',SMTP_HOST='smtp.example.com',SMTP_PORT='587',
            SMTP_SECURITY='starttls',SMTP_FROM='sender@example.com',SMTP_USERNAME='user',SMTP_PASSWORD='fake-password')
        os.environ.pop('BUSINESS_NAME',None)
        importlib.reload(app)
        self.kick=patch('app.invoice_mail.kick');self.kick.start()
        self.generate=patch('app.generate',return_value=b'%PDF exact saved invoice');self.generate.start()
        class QuietHandler(app.Handler):
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.post('/api/contacts',{'kind':'customer','name':'Client Ltd','contact_name':'Sam Client','email':'client@example.com'})
        self.contact=self.state()['contacts'][0]
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.kick.stop();self.generate.stop()
        os.environ.clear();os.environ.update(self.environment);self.temp.cleanup()
    def request(self,path,body=None,origin=None):
        headers={'Content-Type':'application/json'} if body is not None else {}
        if origin:headers['Origin']=origin
        request=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urlopen(request,timeout=5) as response:
                content=response.read();return response.status,json.loads(content) if response.headers['Content-Type']=='application/json' else content
        except HTTPError as response:return response.code,json.loads(response.read())
    def post(self,path,body):
        code,result=self.request(path,body);self.assertLess(code,300,result);return result
    def state(self):return self.request('/api/state')[1]
    def template(self,subject='Invoice {{invoice_number}}',body='<p>Hello {{client_name}}</p>'):
        return self.post('/api/email-template',{'subject':subject,'html':body,'version':self.state()['email_template']['version']})
    def invoice(self,token='save-one'):
        return self.post('/api/invoices',{'customer':'Client Ltd','date':'2026-10-16','deposit':'25',
            'token':token,'email_invoice':True,'email_contact_id':self.contact['id'],'email_recipient':'client@example.com',
            'lines':[{'date':'2026-10-18','venue':'Venue','service':'Maintenance','fee':'125'}]})

    def test_default_save_sanitization_cas_and_preserved_settings(self):
        before=self.state();self.assertEqual(before['email_template']['version'],1)
        saved=self.template('Your invoice {{invoice_number}}','<h2 onclick="bad()">Hello {{client_name}}</h2><script>bad()</script>')
        self.assertEqual(saved['version'],2);self.assertNotIn('onclick',saved['html']);self.assertNotIn('<script',saved['html'])
        code,_=self.request('/api/email-template',{'subject':'Stale','html':'<p>Stale</p>','version':1});self.assertEqual(code,400)
        after=self.state();self.assertEqual(after['email_template'],saved)
        self.assertEqual(after['settings'],before['settings']);self.assertEqual(after['next'],before['next'])
        importlib.reload(app);self.assertEqual(self.state()['email_template'],saved)

    def test_preview_and_paste_clean_have_no_side_effects_and_require_same_origin(self):
        before=self.state();result=self.post('/api/email-template/preview',{'subject':'Draft {{invoice_number}}','html':'<p>{{client_name}} / {{amount_due}}</p>'})
        self.assertEqual(result['subject'],'Draft DEMO0169');self.assertIn('Alex Example',result['plain'])
        self.assertEqual(self.state()['next'],before['next']);self.assertEqual(self.state()['email_template'],before['email_template'])
        cleaned=self.post('/api/email-template/clean',{'html':'<p onclick="x()">Pasted</p><script>x()</script>'})
        self.assertEqual(cleaned['html'],'<p>Pasted</p>')
        self.assertEqual(self.request('/api/email-template',{'subject':'Attack','html':'<p>Attack</p>','version':1},origin='https://evil.example')[0],403)
        with app.connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_mail').fetchone()[0],0)

    def test_template_snapshot_is_atomic_and_retry_keeps_original(self):
        self.template('First {{invoice_number}}','<p>Original {{client_name}}: {{amount_due}}</p>')
        saved=self.invoice();self.template('Changed {{invoice_number}}','<p>Changed</p>')
        job=invoice_mail.claim(app.connection,__import__('time').time())
        self.assertEqual(job['email_subject'],'First 0001');self.assertIn('Original Sam Client: £100.00',job['email_plain'])
        self.assertNotIn('Changed',job['email_html'])
        invoice_mail.finish(app.connection,job,invoice_mail.DeliveryError('SMTP unavailable'))
        self.post('/api/invoices/email-retry',{'id':saved['id'],'recipient':'client@example.com','confirmed':True})
        retried=invoice_mail.claim(app.connection,__import__('time').time())
        self.assertEqual(retried['email_html'],job['email_html']);self.assertEqual(retried['pdf'],job['pdf'])
        self.assertEqual(self.state()['next'],'0002')

    def test_smtp_and_graph_use_same_multipart_content_and_attachment(self):
        self.template('Please pay {{invoice_number}}','<h2>For {{company_name}}</h2><p><strong>{{amount_due}}</strong></p>')
        saved=self.invoice();job=invoice_mail.claim(app.connection,__import__('time').time())
        message=invoice_mail.message_for(job,job['pdf'],job['display_number'],{},'sender@example.com')
        self.assertEqual(message['Subject'],'Please pay 0001');self.assertIn('£100.00',message.get_body(preferencelist=('plain',)).get_content())
        self.assertIn('<strong>£100.00</strong>',message.get_body(preferencelist=('html',)).get_content())
        self.assertEqual(list(message.iter_attachments())[0].get_payload(decode=True),b'%PDF exact saved invoice')
        smtp=MagicMock();smtp.send_message.return_value={}
        with patch('invoice_mail.smtplib.SMTP',return_value=smtp):invoice_mail.deliver(job,job['pdf'],job['display_number'],{})
        smtp_message=smtp.send_message.call_args.args[0]
        os.environ.update(EMAIL_PROVIDER='microsoft_graph',MICROSOFT_CLIENT_ID='11111111-2222-3333-4444-555555555555',MICROSOFT_SENDER='sender@example.com')
        with patch('microsoft_graph.connection_info',return_value={'username':'sender@example.com'}),patch('microsoft_graph.access_token',return_value='FAKE'),patch('microsoft_graph.send_mime',return_value=202) as send:
            bootstrap.deliver(job,job['pdf'],job['display_number'],{})
        graph_message=message_from_bytes(send.call_args.args[1])
        self.assertEqual(graph_message['Subject'],smtp_message['Subject'])
        self.assertEqual(graph_message.get_payload()[0].get_payload()[1].get_payload(decode=True),smtp_message.get_body(preferencelist=('html',)).get_payload(decode=True))

    def test_deletion_cleans_snapshot_and_failed_queue_rolls_back(self):
        saved=self.invoice();self.post('/api/invoices/remove-latest-test',{'id':saved['id'],'confirm':saved['number']})
        with app.connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_email_content').fetchone()[0],0)
        with patch('email_templates.snapshot',side_effect=ValueError('Bad template')):
            raw={'customer':'Client Ltd','date':'2026-10-16','deposit':'0','token':'two','email_invoice':True,
                'email_contact_id':self.contact['id'],'email_recipient':'client@example.com',
                'lines':[{'date':'2026-10-18','venue':'Venue','service':'Work','fee':'100'}]}
            self.assertEqual(self.request('/api/invoices',raw)[0],400)
        self.assertEqual(self.state()['next'],'0001');self.assertFalse(self.state()['invoices'])

    def test_legacy_jobs_fall_back_and_existing_records_survive_migration(self):
        saved=self.invoice()
        with app.connection() as c:
            c.execute('DELETE FROM invoice_email_content')
            c.execute('DROP TABLE invoice_email_template')
        importlib.reload(app)
        self.assertEqual(self.state()['invoices'][0]['number'],'0001');self.assertEqual(self.state()['next'],'0002')
        job=invoice_mail.claim(app.connection,__import__('time').time())
        message=invoice_mail.message_for(job,job['pdf'],'0001',{},'sender@example.com')
        self.assertEqual(message['Subject'],'Invoice 0001');self.assertIsNotNone(message.get_body(preferencelist=('html',)))

    def test_editor_assets_and_sandbox_preview(self):
        code,page=self.request('/');self.assertEqual(code,200)
        self.assertIn(b'contenteditable="true"',page);self.assertIn(b'sandbox=""',page)
        self.assertIn(b'/email_editor.js',page);self.assertNotIn(b'cdn.',page)
        code,script=self.request('/email_editor.js');self.assertEqual(code,200)
        self.assertIn(b"event.preventDefault()",script)
        self.assertIn(b"'/api/email-template/clean'",script)


if __name__=='__main__':unittest.main()
