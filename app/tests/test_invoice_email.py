import importlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import MagicMock, patch

import app
import invoice_mail as mail


class InvoiceEmailTests(unittest.TestCase):
    def setUp(self):
        self.environment=dict(os.environ)
        self.temp=tempfile.TemporaryDirectory()
        os.environ.update(DATA_DIR=self.temp.name,SMTP_HOST='smtp.example.com',SMTP_PORT='587',
            SMTP_SECURITY='starttls',SMTP_USERNAME='test-user',SMTP_PASSWORD='test-secret',SMTP_FROM='sender@example.com')
        importlib.reload(app)
        self.kick=patch('app.invoice_mail.kick');self.kick.start()
        self.pdf=patch('app.generate',return_value=b'%PDF saved invoice');self.generate=self.pdf.start()
        class QuietHandler(app.Handler):
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),QuietHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.post('/api/contacts',{'kind':'customer','name':'Client','email':'client@example.com','address':'Saved address','contact_name':'Saved person'})
        self.contact=self.state()['contacts'][0]
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.kick.stop();self.pdf.stop();os.environ.clear();os.environ.update(self.environment)
        self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        request=Request(self.url+path,data=None if body is None else json.dumps(body).encode(),
                        headers=headers or ({'Content-Type':'application/json'} if body is not None else {}))
        try:
            with urlopen(request,timeout=5) as response:
                raw=response.read();return response.status,json.loads(raw) if response.headers['Content-Type']=='application/json' else raw
        except HTTPError as response:return response.code,json.loads(response.read())
    def post(self,path,body):
        code,result=self.request(path,body);self.assertLess(code,300,result);return result
    def state(self):return self.request('/api/state')[1]
    def raw(self,token='save-one',email=True,**extra):
        return dict(customer='Client',customer_email='spoof@example.com',customer_contact_name='Spoof',customer_address='Spoof address',
                    date='2026-10-14',deposit='0',token=token,email_invoice=email,email_contact_id=self.contact['id'],
                    email_recipient='client@example.com',lines=[dict(date='2026-10-15',venue='Venue',service='DJ',fee='100')],**extra)
    def job(self,identifier):
        with app.connection() as c:return dict(c.execute('SELECT * FROM invoice_mail WHERE invoice_id=?',(identifier,)).fetchone())
    def finish_send(self,identifier,error=None):
        job=mail.claim(app.connection,time.time());self.assertEqual(job['invoice_id'],identifier)
        mail.finish(app.connection,job,error);return job

    def test_unticked_preview_and_disabled_configuration(self):
        os.environ['SMTP_HOST']=''
        raw=self.raw(email=False)
        saved=self.post('/api/invoices',raw)
        self.assertNotIn('email',saved)
        self.assertFalse(self.state()['smtp']['configured'])
        self.assertEqual(self.request('/api/preview',self.raw())[0],200)
        with app.connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_mail').fetchone()[0],0)
        code,result=self.request('/api/invoices',self.raw('new'))
        self.assertEqual(code,400);self.assertIn('SMTP_HOST',result['error'])
        self.assertEqual(self.state()['next'],'0002')

    def test_saved_contact_snapshot_and_duplicate_save_never_requeues(self):
        saved=self.post('/api/invoices',self.raw())
        self.assertEqual(saved['email']['recipient'],'client@example.com')
        invoice=self.state()['invoices'][0]
        self.assertEqual(invoice['customer_email'],'client@example.com')
        self.assertEqual(invoice['customer_address'],'Saved address')
        self.assertEqual(invoice['customer_contact_name'],'Saved person')
        self.assertEqual(self.request('/api/invoices/'+str(saved['id'])+'/pdf')[1],b'%PDF saved invoice')
        self.post('/api/contacts',{'kind':'customer','name':'Client','email':'changed@example.com'})
        repeated=self.post('/api/invoices',self.raw())
        self.assertEqual(saved,repeated)
        self.assertEqual(self.state()['next'],'0002')
        self.assertEqual(self.generate.call_count,1)
        with app.connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_mail').fetchone()[0],1)
        self.finish_send(saved['id'])
        repeated=self.post('/api/invoices',self.raw())
        self.assertEqual(repeated['email']['status'],'sent')
        self.assertIsNone(mail.claim(app.connection,time.time()))

    def test_false_then_true_retry_does_not_send_old_invoice(self):
        saved=self.post('/api/invoices',self.raw(email=False))
        repeat=self.post('/api/invoices',self.raw())
        self.assertEqual(saved,repeat);self.assertNotIn('email',repeat)
        self.assertIsNone(mail.claim(app.connection,time.time()))

    def test_invalid_stale_missing_or_injected_recipient_rolls_back(self):
        for changes in [dict(email_invoice='true'),dict(email_contact_id=True),dict(email_contact_id=999),
                        dict(email_recipient='other@example.com'),dict(email_recipient='client@example.com\r\nBcc: attacker@example.com')]:
            raw=self.raw();raw.update(changes)
            self.assertEqual(self.request('/api/invoices',raw)[0],400)
        self.post('/api/contacts',{'kind':'customer','name':'Client','email':''})
        self.assertEqual(self.request('/api/invoices',self.raw())[0],400)
        self.assertEqual(self.state()['next'],'0001');self.assertFalse(self.state()['invoices'])
        self.assertEqual(self.generate.call_count,0)
        self.assertEqual(self.request('/api/contacts',{'kind':'customer','name':'Bad','email':'a@example.com,b@example.com'})[0],400)

    def test_atomic_queue_limits_pdf_and_numbering(self):
        with app.connection() as c:
            c.executemany('INSERT INTO invoice_mail_requests VALUES(?)',[(time.time(),)]*20)
        self.assertEqual(self.request('/api/invoices',self.raw())[0],400)
        self.assertEqual(self.state()['next'],'0001');self.assertFalse(self.state()['invoices'])
        with app.connection() as c:c.execute('DELETE FROM invoice_mail_requests')
        self.generate.return_value=b'%PDF'+b'x'*mail.MAX_PDF
        self.assertEqual(self.request('/api/invoices',self.raw())[0],400)
        self.assertEqual(self.state()['next'],'0001');self.assertFalse(self.state()['invoices'])
        self.generate.return_value=b'%PDF saved invoice'
        self.post('/api/contacts',{'kind':'customer','name':'Client','email':'client@example.com','separate_numbering':True,'invoice_prefix':'LEA','next_invoice_number':169})
        saved=self.post('/api/invoices',self.raw());self.assertEqual(saved['number'],'LEA0169')
        self.assertEqual(self.state()['next'],'0001');self.assertEqual(self.state()['contacts'][0]['next_invoice_number'],170)

    def test_tls_attachment_exact_pdf_envelope_and_no_quit_retry(self):
        saved=self.post('/api/invoices',self.raw());job=self.job(saved['id'])
        smtp=MagicMock();smtp.send_message.return_value={};smtp.quit.side_effect=OSError('quit-secret')
        with patch('invoice_mail.smtplib.SMTP',return_value=smtp) as constructor:
            mail.deliver(job,b'%PDF exact saved',saved['number'],{'business':'Test business'})
        constructor.assert_called_once_with('smtp.example.com',587,timeout=10)
        smtp.starttls.assert_called_once();smtp.login.assert_called_once_with('test-user','test-secret')
        context=smtp.starttls.call_args.kwargs['context'];self.assertTrue(context.check_hostname)
        args=smtp.send_message.call_args
        message=args.args[0];self.assertEqual(args.kwargs['to_addrs'],['client@example.com'])
        self.assertEqual(args.kwargs['from_addr'],'sender@example.com')
        self.assertEqual(message['To'],'client@example.com');self.assertIsNone(message['Bcc'])
        attachment=list(message.iter_attachments())[0]
        self.assertEqual(attachment.get_payload(decode=True),b'%PDF exact saved')
        self.assertEqual(attachment.get_filename(),'0001 Invoice.pdf')
        self.assertEqual(message['Subject'],'Invoice 0001')
        os.environ.update(SMTP_SECURITY='ssl',SMTP_PORT='465')
        with patch('invoice_mail.smtplib.SMTP_SSL',return_value=smtp) as constructor:
            mail.deliver(job,b'%PDF exact saved',saved['number'],{})
        self.assertEqual(constructor.call_args.kwargs['timeout'],10)

    def test_failures_are_safe_and_uncertain_does_not_auto_retry(self):
        saved=self.post('/api/invoices',self.raw());job=self.job(saved['id']);smtp=MagicMock()
        smtp.login.side_effect=RuntimeError('test-secret')
        with patch('invoice_mail.smtplib.SMTP',return_value=smtp):
            with self.assertRaises(mail.DeliveryError) as caught:mail.deliver(job,b'%PDF saved',saved['number'],{})
        self.assertFalse(caught.exception.uncertain);self.assertNotIn('test-secret',str(caught.exception))
        smtp.login.side_effect=None;smtp.send_message.side_effect=TimeoutError('test-secret')
        with patch('invoice_mail.smtplib.SMTP',return_value=smtp):
            with self.assertRaises(mail.DeliveryError) as caught:mail.deliver(job,b'%PDF saved',saved['number'],{})
        self.assertTrue(caught.exception.uncertain);self.assertNotIn('test-secret',str(caught.exception))
        self.finish_send(saved['id'],caught.exception)
        self.assertIsNone(mail.claim(app.connection,time.time()))
        self.assertEqual(self.state()['invoices'][0]['email']['status'],'uncertain')
        self.assertEqual(self.state()['next'],'0002')

    def test_retry_confirmation_original_recipient_same_pdf_and_sent_block(self):
        saved=self.post('/api/invoices',self.raw());self.finish_send(saved['id'],mail.DeliveryError('Check SMTP'))
        for raw in [dict(id=saved['id'],recipient='client@example.com',confirmed=False),dict(id=saved['id'],recipient='wrong@example.com',confirmed=True)]:
            self.assertEqual(self.request('/api/invoices/email-retry',raw)[0],400)
        self.post('/api/contacts',{'kind':'customer','name':'Client','email':'changed@example.com'})
        self.post('/api/invoices/email-retry',dict(id=saved['id'],recipient='client@example.com',confirmed=True))
        job=self.finish_send(saved['id']);self.assertEqual(job['recipient'],'client@example.com');self.assertEqual(job['pdf'],b'%PDF saved invoice')
        self.assertEqual(self.state()['next'],'0002');self.assertEqual(self.generate.call_count,1)
        self.assertEqual(self.request('/api/invoices/email-retry',dict(id=saved['id'],recipient='client@example.com',confirmed=True))[0],400)

    def test_concurrent_saves_and_claims_are_single_use(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.post('/api/invoices',self.raw()),range(4)))
        self.assertEqual(len({r['id'] for r in results}),1);self.assertEqual(self.generate.call_count,1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            claims=list(pool.map(lambda _:mail.claim(app.connection,time.time()),range(4)))
        self.assertEqual(sum(j is not None for j in claims),1)
        job=next(j for j in claims if j);mail.finish(app.connection,job)

    def test_restart_marks_inflight_uncertain_and_preserves_owner_guard(self):
        first=self.post('/api/invoices',self.raw());second=self.post('/api/invoices',self.raw('two'))
        clock=time.time();old=mail.claim(app.connection,clock)
        self.assertIsNone(mail.claim(app.connection,clock+119))
        new=mail.claim(app.connection,clock+121);self.assertEqual(new['invoice_id'],second['id'])
        self.assertEqual(self.job(first['id'])['status'],'uncertain')
        mail.finish(app.connection,old);self.assertEqual(self.job(first['id'])['status'],'uncertain')
        mail.finish(app.connection,new);self.assertEqual(self.job(second['id'])['status'],'sent')

    def test_worker_uses_saved_pdf_and_records_outcome(self):
        saved=self.post('/api/invoices',self.raw())
        self.assertTrue(mail.LOCK.acquire(blocking=False))
        with patch('invoice_mail.deliver') as deliver:mail.run(app.connection)
        self.assertEqual(deliver.call_count,1);self.assertEqual(deliver.call_args.args[1],b'%PDF saved invoice')
        self.assertEqual(self.job(saved['id'])['status'],'sent');self.assertFalse(mail.LOCK.locked())
        self.request('/health');self.kick.return_value=None

    def test_delete_pending_and_sent_reclaims_number_but_sending_is_blocked(self):
        saved=self.post('/api/invoices',self.raw())
        self.post('/api/invoices/remove-latest-test',dict(id=saved['id'],confirm=saved['number']))
        self.assertIsNone(mail.claim(app.connection,time.time()));self.assertEqual(self.state()['next'],'0001')
        saved=self.post('/api/invoices',self.raw('two'))
        job=mail.claim(app.connection,time.time())
        self.assertEqual(self.request('/api/invoices/remove-latest-test',dict(id=saved['id'],confirm=saved['number']))[0],400)
        mail.finish(app.connection,job)
        removed=self.post('/api/invoices/remove-latest-test',dict(id=saved['id'],confirm=saved['number']))
        self.assertEqual(removed['next'],'0001');self.assertEqual(self.state()['next'],'0001');self.assertFalse(self.state()['invoices'])
        with app.connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_mail').fetchone()[0],0)

    def test_migration_preserves_old_records_settings_and_pdf(self):
        saved=self.post('/api/invoices',self.raw(email=False))
        before=self.state()
        with app.connection() as c:
            c.executescript('DROP TABLE invoice_mail;DROP TABLE invoice_mail_guard;DROP TABLE invoice_mail_requests;')
        importlib.reload(app)
        after=self.state();self.assertEqual(before['contacts'],after['contacts']);self.assertEqual(before['invoices'],after['invoices'])
        self.assertEqual(before['next'],after['next']);self.assertEqual(before['settings'],after['settings'])
        self.assertEqual(self.request('/api/invoices/'+str(saved['id'])+'/pdf')[1],b'%PDF saved invoice')

    def test_smtp_configuration_and_api_do_not_expose_credentials(self):
        body=json.dumps(self.state());self.assertNotIn('test-secret',body);self.assertNotIn('test-user',body)
        for field,value in [('SMTP_SECURITY','none'),('SMTP_PORT','0'),('SMTP_HOST','smtp.example.com\r\nBAD'),('SMTP_FROM','a@example.com,b@example.com'),('SMTP_PASSWORD','')]:
            original=os.environ[field];os.environ[field]=value
            self.assertFalse(mail.configuration_status()['configured']);os.environ[field]=original
        self.assertEqual(self.request('/api/invoices',self.raw(),{'Content-Type':'application/json','Origin':'http://evil.example'})[0],403)

    def test_confirmed_smtp_rejections_are_failed_not_uncertain(self):
        import smtplib
        saved=self.post('/api/invoices',self.raw());job=self.job(saved['id']);smtp=MagicMock()
        for error in [smtplib.SMTPRecipientsRefused({'client@example.com':(550,b'rejected')}),
                      smtplib.SMTPDataError(554,b'rejected'),smtplib.SMTPSenderRefused(550,b'rejected','sender@example.com')]:
            smtp.send_message.side_effect=error
            with patch('invoice_mail.smtplib.SMTP',return_value=smtp):
                with self.assertRaises(mail.DeliveryError) as caught:mail.deliver(job,b'%PDF saved',saved['number'],{})
            self.assertFalse(caught.exception.uncertain)


class InterfaceTests(unittest.TestCase):
    def test_required_controls_and_unticked_default(self):
        import re
        from html.parser import HTMLParser
        from pathlib import Path
        class Page(HTMLParser):
            def __init__(self):super().__init__();self.ids={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if 'id' in attrs:self.ids[attrs['id']]=attrs
        root=Path(__file__).resolve().parents[1];page=Page()
        page.feed((root/'static/index.html').read_text())
        for identifier in re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)",(root/'static/app.js').read_text()):
            self.assertIn(identifier,page.ids)
        self.assertIn('smtp-status',page.ids)
        checkbox=page.ids['email-invoice'];self.assertEqual(checkbox['type'],'checkbox')
        self.assertNotIn('checked',checkbox);self.assertIn('disabled',checkbox)


if __name__=='__main__':unittest.main()
