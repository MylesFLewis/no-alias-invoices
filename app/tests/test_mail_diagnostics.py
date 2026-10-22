import logging,smtplib,ssl,time,unittest
from io import StringIO
from unittest.mock import MagicMock,patch
from urllib.error import HTTPError
import app,bootstrap,invoice_mail as mail,mail_diagnostics as diag,microsoft_graph as graph
import test_invoice_email as fixtures
GUID='11111111-2222-3333-4444-555555555555'
CLIENT='22222222-2222-3333-4444-555555555555'
class DiagnosticHistoryTests(unittest.TestCase):
    setUp=fixtures.InvoiceEmailTests.setUp
    tearDown=fixtures.InvoiceEmailTests.tearDown
    request=fixtures.InvoiceEmailTests.request
    post=fixtures.InvoiceEmailTests.post
    state=fixtures.InvoiceEmailTests.state
    raw=fixtures.InvoiceEmailTests.raw
    def test_timeline_retry_and_snapshot(self):
        saved=self.post('/api/invoices',self.raw());identifier=saved['id']
        with app.connection() as c:self.assertIsNone(mail.status(c,identifier)['attempts'][0]['started_at'])
        job=mail.claim(app.connection,time.time());ref=job['attempt_ref']
        mail.finish(app.connection,job,mail.DeliveryError('Login failed',category='authentication'))
        with app.connection() as c:
            self.assertEqual(mail.status(c,identifier)['attempts'][0]['category'],'authentication')
            mail.retry(c,identifier,'client@example.com',True,time.time())
        job=mail.claim(app.connection,time.time());self.assertNotEqual(job['attempt_ref'],ref);mail.finish(app.connection,job)
        with app.connection() as c:
            result=mail.status(c,identifier);self.assertEqual(len(result['attempts']),2)
            self.assertIn('SMTP server',result['label']);self.assertIn('delivery not confirmed',result['label']);self.assertIn('phishing',result['guidance'])
            self.assertIsNotNone(result['attempts'][0]['finished_at']);self.assertEqual(c.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_email_content').fetchone()[0],1)
        with patch.dict('os.environ',{'EMAIL_PROVIDER':'microsoft_graph'}):
            with app.connection() as c:self.assertEqual(mail.status(c,identifier)['provider'],'smtp')
    def test_interrupted_claim_and_late_finish(self):
        saved=self.post('/api/invoices',self.raw());job=mail.claim(app.connection,time.time())
        with app.connection() as c:c.execute('UPDATE invoice_mail_guard SET expires_at=0')
        self.assertIsNone(mail.claim(app.connection,time.time()));mail.finish(app.connection,job)
        with app.connection() as c:
            result=mail.status(c,saved['id']);self.assertEqual(result['status'],'uncertain');self.assertEqual(result['attempts'][0]['category'],'interrupted')
    def test_legacy_and_deletion_cleanup(self):
        saved=self.post('/api/invoices',self.raw())
        with app.connection() as c:
            c.execute('DELETE FROM invoice_mail_attempts');c.execute("UPDATE invoice_mail SET status='sent'")
        with app.connection() as c:
            result=mail.status(c,saved['id']);self.assertEqual(result['provider'],'unknown');self.assertFalse(result['history_available'])
        self.post('/api/invoices/remove-latest-test',{'id':saved['id'],'confirm':saved['number']})
        with app.connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_mail_attempts').fetchone()[0],0)
    def test_allowlist_history_bound_and_smtp_log_privacy(self):
        saved=self.post('/api/invoices',self.raw());job=mail.claim(app.connection,time.time());server=MagicMock()
        server.login.side_effect=smtplib.SMTPAuthenticationError(535,b'test-secret PRIVATE-BODY test-user')
        with self.assertLogs(level=logging.INFO) as captured,patch('invoice_mail.smtplib.SMTP',return_value=server):
            with self.assertRaises(mail.DeliveryError) as failed:mail.deliver(job,b'%PDF private',saved['number'],{})
        for secret in ('test-secret','PRIVATE-BODY','test-user'):self.assertNotIn(secret,' '.join(captured.output))
        self.assertEqual(failed.exception.category,'authentication');self.assertFalse(failed.exception.uncertain);self.assertEqual(job['diagnostics']['protocol_code'],535)
        with app.connection() as c:
            for n in range(55):diag.queued(c,saved['id'],time.time()+n)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM invoice_mail_attempts').fetchone()[0],50)
        self.assertEqual(diag.safe_metadata({'request_id':'secret\nTOKEN','client_request_id':GUID,'protocol_code':202,'retry_after':-1,'body':'PRIVATE'}),{'client_request_id':GUID,'protocol_code':202})
class ProviderMetadataTests(unittest.TestCase):
    def test_graph_capture_success_and_safe_rejection(self):
        response=MagicMock();response.__enter__.return_value.status=202;response.__enter__.return_value.headers={'request-id':GUID,'client-request-id':CLIENT}
        opener=MagicMock();opener.open.return_value=response;metadata={'client_request_id':CLIENT}
        with patch('microsoft_graph.access_token',return_value='SECRET-TOKEN'),patch('microsoft_graph.urllib.request.build_opener',return_value=opener):
            self.assertEqual(graph.send_mime(CLIENT,b'PRIVATE-BODY',diagnostics=metadata),202)
            self.assertEqual(opener.open.call_args.args[0].get_header('Client-request-id'),CLIENT);self.assertEqual(metadata['request_id'],GUID)
            opener.open.side_effect=HTTPError('https://graph.microsoft.com',429,'SECRET-TOKEN',{'request-id':GUID,'Retry-After':'60'},StringIO('PRIVATE-BODY'))
            with self.assertRaises(graph.GraphRejected) as failed:graph.send_mime(CLIENT,b'PRIVATE-BODY',diagnostics=metadata)
            self.assertEqual(failed.exception.status,429);self.assertNotIn('SECRET',str(failed.exception));self.assertEqual(metadata['retry_after'],60)
    def test_failure_categories_and_no_automatic_graph_retry(self):
        for code,category in [(401,'authentication'),(403,'permission'),(429,'throttled'),(503,'provider_unavailable'),(400,'rejected')]:
            self.assertEqual(diag.http_category(code),category)
            with patch.dict('os.environ',{'EMAIL_PROVIDER':'microsoft_graph'}),patch('bootstrap.config',return_value={'client_id':CLIENT,'sender':'sender@example.com'}),patch('microsoft_graph.access_token',return_value='token'),patch('invoice_mail.message_for',return_value=MagicMock()),patch('microsoft_graph.send_mime',side_effect=graph.GraphRejected('safe',code)) as send:
                with self.assertRaises(mail.DeliveryError) as failed:bootstrap.deliver({'recipient':'client@example.com'},b'%PDF','0001',{})
                self.assertEqual(failed.exception.category,category);self.assertEqual(send.call_count,1)
        self.assertEqual(mail.smtp_category(ssl.SSLError('PRIVATE'),False),'tls')
        self.assertEqual(mail.smtp_category(smtplib.SMTPRecipientsRefused({}),True),'recipient')
        self.assertEqual(mail.smtp_category(TimeoutError('PRIVATE'),True),'interrupted')
        self.assertEqual(mail.smtp_category(TimeoutError('PRIVATE'),False),'connection')
