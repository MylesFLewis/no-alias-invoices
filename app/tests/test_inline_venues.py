import copy,json,time,unittest
from unittest.mock import patch
import app
import test_invoice_email as fixtures

class InlineVenueTests(unittest.TestCase):
    setUp=fixtures.InvoiceEmailTests.setUp
    tearDown=fixtures.InvoiceEmailTests.tearDown
    request=fixtures.InvoiceEmailTests.request
    post=fixtures.InvoiceEmailTests.post
    state=fixtures.InvoiceEmailTests.state
    raw=fixtures.InvoiceEmailTests.raw
    def draft(self,token='inline-one',name='New Hall',address='1 New Street, IP1 2AB'):
        raw=self.raw(token=token,email=False)
        raw['lines'][0].pop('venue')
        raw['lines'][0]['new_venue']={'name':name,'address':address,'contact_id':self.contact['id']}
        return raw
    def venues(self):return [r for r in self.state()['contacts'] if r['kind']=='venue']
    def test_preview_readonly_then_atomic_save_assignment_and_duplicate_request(self):
        raw=self.draft();self.assertEqual(self.request('/api/preview',raw)[0],200)
        self.assertEqual(self.venues(),[]);self.assertFalse(self.state()['contacts'][0]['has_assigned_venues'])
        saved=self.post('/api/invoices',raw);venue=self.venues()[0]
        self.assertEqual(venue['name'],'New Hall');self.assertEqual(venue['address'],'1 New Street, IP1 2AB');self.assertEqual(venue['assigned_contact_id'],self.contact['id'])
        self.assertEqual(self.post('/api/invoices',raw)['id'],saved['id']);self.assertEqual(len(self.venues()),1)
        invoice=self.state()['invoices'][0];self.assertEqual(invoice['lines'][0]['venue_id'],venue['id']);self.assertEqual(invoice['lines'][0]['venue'],'New Hall, 1 New Street, IP1 2AB')
        self.assertNotIn('new_venue',invoice['lines'][0]);self.assertTrue(self.state()['contacts'][0]['has_assigned_venues'])
    def test_duplicate_rows_reuse_venue_and_existing_selection_remains_available(self):
        raw=self.draft();raw['lines'].append(copy.deepcopy(raw['lines'][0]));self.post('/api/invoices',raw)
        self.assertEqual(len(self.venues()),1);invoice=self.state()['invoices'][0]
        self.assertEqual(invoice['lines'][0]['venue_id'],invoice['lines'][1]['venue_id'])
        selected=self.raw(token='saved-venue',email=False);selected['lines'][0]['venue_id']=self.venues()[0]['id'];self.post('/api/invoices',selected)
        self.assertEqual(len(self.venues()),1)
    def test_bad_fields_wrong_contact_deleted_contact_and_conflicts(self):
        for changes in ({'name':''},{'address':''},{'name':'x'*201},{'address':'x'*501},{'contact_id':999}):
            raw=self.draft();raw['lines'][0]['new_venue'].update(changes);self.assertEqual(self.request('/api/invoices',raw)[0],400)
        raw=self.draft();raw['lines'][0]['venue_id']=1;self.assertEqual(self.request('/api/invoices',raw)[0],400)
        self.assertEqual(self.venues(),[])
        self.post('/api/contacts',{'kind':'venue','name':'new hall','address':'Shared existing address','assigned_contact_id':None})
        self.assertEqual(self.request('/api/invoices',self.draft())[0],400);self.assertEqual(self.venues()[0]['assigned_contact_id'],None)
        raw=self.draft(name='Other Hall');raw['customer']='Missing contact';self.assertEqual(self.request('/api/invoices',raw)[0],400)
        self.assertEqual(self.state()['invoices'],[])
    def test_generation_and_email_failure_roll_back_venue_and_assignment(self):
        with patch('app.generate',side_effect=ValueError('Synthetic PDF error')):self.assertEqual(self.request('/api/invoices',self.draft())[0],400)
        raw=self.draft();raw['email_invoice']=True
        with patch('app.invoice_mail.queue',side_effect=ValueError('Synthetic queue error')):self.assertEqual(self.request('/api/invoices',raw)[0],400)
        self.assertEqual(self.venues(),[]);self.assertEqual(self.state()['invoices'],[]);self.assertEqual(self.state()['next'],'0001');self.assertFalse(self.state()['contacts'][0]['has_assigned_venues'])
    def test_same_contact_exact_match_reused_but_address_or_owner_conflict_rejected(self):
        self.post('/api/invoices',self.draft());self.post('/api/invoices',self.draft(token='second',name='NEW HALL'))
        self.assertEqual(len(self.venues()),1)
        self.assertEqual(self.request('/api/invoices',self.draft(token='bad-address',address='Different address'))[0],400)
        with app.connection() as c:c.execute('UPDATE contacts SET assigned_contact_id=999 WHERE kind=\'venue\'')
        self.assertEqual(self.request('/api/invoices',self.draft(token='bad-owner'))[0],400)
    def test_multiple_new_venues_and_conflicting_draft_addresses(self):
        raw=self.draft();other=copy.deepcopy(raw['lines'][0]);other['new_venue']['address']='Different address';raw['lines'].append(other)
        self.assertEqual(self.request('/api/preview',raw)[0],400);self.assertEqual(self.request('/api/invoices',raw)[0],400);self.assertEqual(self.venues(),[])
        raw['lines'][1]['new_venue']['name']='Second Hall';self.post('/api/invoices',raw);self.assertEqual(len(self.venues()),2)
