import copy, importlib, json, os, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import app
import booking_import

class BookingImportTests(unittest.TestCase):
    def setUp(self):
        self.env=dict(os.environ);self.temp=tempfile.TemporaryDirectory()
        os.environ.update(DATA_DIR=self.temp.name,BOOKINGS_API_KEY='a'*64,EMAIL_PROVIDER='smtp',SMTP_HOST='smtp.example.com',SMTP_PORT='587',SMTP_SECURITY='starttls',SMTP_FROM='sender@example.com')
        importlib.reload(app)
        self.gen=patch('app.generate',return_value=b'%PDF saved booking');self.gen.start()
        self.kick=patch('app.invoice_mail.kick');self.kick.start()
        class Quiet(app.Handler):
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Quiet);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.proposal={'source':'1'*32,'booking':'2'*32,'reference':'Birthday booking',
            'contact':{'mode':'new','name':'Alex Example','contact_name':'Alex','email':'alex@example.com','address':'Billing address'},
            'email_invoice':True,'draft':{'date':'2026-10-16','deposit':'50.00',
                'lines':[{'date':'2026-12-12','venue':'Town Hall, AB1 2CD','service':'DJ entertainment','other_details':'19:00 → 23:00 UK','fee':'300.00'}]}}
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.gen.stop();self.kick.stop()
        os.environ.clear();os.environ.update(self.env);self.temp.cleanup()
    def post(self,action,raw=None,headers=None):
        req=Request(self.base+'/api/bookings/'+action,data=json.dumps(raw or self.proposal).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['BOOKINGS_API_KEY'],**(headers or {})})
        try:
            with urlopen(req,timeout=5) as r:return r.status,json.load(r)
        except HTTPError as e:return e.code,json.load(e)
    def counts(self):
        with app.connection() as c:return tuple(c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('contacts','invoices','invoice_mail'))
    def reviewed(self,p=None):
        p=copy.deepcopy(p or self.proposal);code,result=self.post('review',p);self.assertEqual(code,200,result)
        p['review_token']=result['review_token'];return p,result
    def test_authorization_origin_and_disabled_default(self):
        for h in ({'Authorization':''},{'Authorization':'Bearer wrong'},{'Origin':'http://evil.example'}):self.assertEqual(self.post('contacts',headers=h)[0],403)
        self.assertFalse(booking_import.authorized('Bearer é'));os.environ.pop('BOOKINGS_API_KEY');self.assertFalse(booking_import.authorized('Bearer '+'a'*64))
        self.assertEqual(self.counts(),(0,0,0))
    def test_review_then_atomic_contact_invoice_email(self):
        p,r=self.reviewed();self.assertEqual(self.counts(),(0,0,0));self.assertEqual(r['summary']['deposit'],5000)
        code,result=self.post('create',p);self.assertEqual(code,201,result);self.assertEqual(result['number'],'0001');self.assertEqual(self.counts(),(1,1,1))
        self.assertEqual(result['email']['recipient'],'alex@example.com')
        with app.connection() as c:
            body=json.loads(c.execute('SELECT body FROM invoices').fetchone()[0]);self.assertEqual(body['customer_address'],'Billing address')
            self.assertEqual(body['lines'][0]['venue'],'Town Hall, AB1 2CD');self.assertEqual(c.execute('SELECT next_number FROM settings').fetchone()[0],2)
            self.assertIn('Alex',c.execute('SELECT plain FROM invoice_email_content').fetchone()[0]);self.assertEqual(c.execute('SELECT reference FROM booking_invoices').fetchone()[0],'Birthday booking')
    def test_concurrent_retries_and_changed_payload_do_not_duplicate(self):
        p,_=self.reviewed();results=[]
        threads=[threading.Thread(target=lambda:results.append(self.post('create',p))) for _ in range(3)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sorted(r[0] for r in results),[200,200,201]);self.assertEqual(self.counts(),(1,1,1))
        p['draft']['lines'][0]['fee']='999';self.assertEqual(self.post('create',p)[1]['number'],'0001');self.assertTrue(self.post('status')[1]['created'])
    def test_existing_contact_terms_numbering_and_details_preserved(self):
        with app.connection() as c:c.execute("INSERT INTO contacts(id,kind,name,address,contact_name,email,payment_term_days,separate_numbering,invoice_prefix,next_invoice_number) VALUES(5,'customer','Saved Ltd','Saved billing','Saved Name','saved@example.com',30,1,'S-',169)")
        p=copy.deepcopy(self.proposal);p['contact']={'mode':'existing','id':5};p,r=self.reviewed(p)
        self.assertEqual(r['summary']['due_date'],'2026-11-15');result=self.post('create',p)[1]
        self.assertEqual(result['number'],'S-0169');self.assertEqual(result['email']['recipient'],'saved@example.com')
        with app.connection() as c:
            self.assertEqual(c.execute('SELECT next_number FROM settings').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT address,next_invoice_number FROM contacts').fetchone()[:],('Saved billing',170))
    def test_stale_review_invalid_values_and_rollback(self):
        self.assertEqual(self.post('create')[0],400);p,_=self.reviewed();p['draft']['deposit']='75';self.assertEqual(self.post('create',p)[0],400)
        p,_=self.reviewed()
        with app.connection() as c:c.execute('UPDATE settings SET next_number=2')
        self.assertEqual(self.post('create',p)[0],400);p,_=self.reviewed()
        with patch('app.invoice_mail.queue',side_effect=ValueError('Queue unavailable')):self.assertEqual(self.post('create',p)[0],400)
        self.assertEqual(self.counts(),(0,0,0))
        for value in ('301','NaN'):
            p=copy.deepcopy(self.proposal);p['draft']['deposit']=value;self.assertEqual(self.post('review',p)[0],400)
    def test_name_conflict_and_ambiguous_emails(self):
        with app.connection() as c:
            for n in (1,2):c.execute("INSERT INTO contacts(id,kind,name,email) VALUES(?,'customer',?,'alex@example.com')",(n,'Existing '+str(n)))
        self.assertEqual(len(self.post('contacts')[1]['contacts']),2)
        p=copy.deepcopy(self.proposal);p['contact']['name']='existing 1';self.assertEqual(self.post('review',p)[0],400)
        p['contact']={'mode':'existing','id':1};p,_=self.reviewed(p);self.assertEqual(self.post('create',p)[0],201);self.assertEqual(self.counts(),(2,1,1))
    def test_removal_tombstone_survives_key_rotation(self):
        p,_=self.reviewed();result=self.post('create',p)[1]
        req=Request(self.base+'/api/invoices/remove-latest-test',data=json.dumps({'id':result['id'],'confirm':result['number']}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req) as r:self.assertEqual(r.status,200)
        self.assertTrue(self.post('status')[1]['removed']);os.environ['BOOKINGS_API_KEY']='b'*64
        self.assertTrue(self.post('create',p)[1]['removed']);self.assertEqual(self.counts(),(1,0,0))
    def test_no_email_and_request_limit(self):
        p=copy.deepcopy(self.proposal);p['email_invoice']=False;p['contact']['email']='';p,_=self.reviewed(p)
        self.assertEqual(self.post('create',p)[0],201);self.assertEqual(self.counts(),(1,1,0))
        with app.connection() as c:
            import time
            c.executemany('INSERT INTO booking_api_requests VALUES(?)',[(time.time(),)]*60)
        self.assertEqual(self.post('contacts')[0],429)
