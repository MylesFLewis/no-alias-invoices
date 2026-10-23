import copy,json,unittest
from unittest.mock import patch
import app
import test_invoice_email as fixtures

class VenueEditingTests(unittest.TestCase):
    setUp=fixtures.InvoiceEmailTests.setUp
    tearDown=fixtures.InvoiceEmailTests.tearDown
    request=fixtures.InvoiceEmailTests.request
    post=fixtures.InvoiceEmailTests.post
    state=fixtures.InvoiceEmailTests.state
    raw=fixtures.InvoiceEmailTests.raw
    def create(self,name='Original Hall'):
        return self.post('/api/contacts',{'kind':'venue','name':name,'address':'Original address','assigned_contact_id':self.contact['id']})
    def venue(self,identifier):return next(c for c in self.state()['contacts'] if c['id']==identifier)
    def edit(self,identifier,**changes):
        row=self.venue(identifier)
        return {'kind':'venue','id':identifier,'expected':{k:row[k] for k in ('name','address','assigned_contact_id')},'name':row['name'],'address':row['address'],**changes}
    def test_rename_keeps_id_assignment_and_invoice_snapshots(self):
        identifier=self.create()['id'];raw=self.raw(email=False);raw['lines'][0]['venue_id']=identifier
        saved=self.post('/api/invoices',raw);before=self.state()['invoices'][0];pdf=self.request('/api/invoices/'+str(saved['id'])+'/pdf')[1]
        result=self.post('/api/contacts',self.edit(identifier,name='Renamed Hall',address='Revised address'))
        self.assertEqual(result['id'],identifier);self.assertFalse(result['created'])
        venue=self.venue(identifier);self.assertEqual(venue['name'],'Renamed Hall');self.assertEqual(venue['assigned_contact_id'],self.contact['id'])
        self.assertEqual(sum(c['kind']=='venue' for c in self.state()['contacts']),1)
        self.assertEqual(self.state()['invoices'][0],before);self.assertEqual(self.request('/api/invoices/'+str(saved['id'])+'/pdf')[1],pdf)
        raw['token']='another-invoice';raw['lines'][0]['venue']='ignored';self.post('/api/invoices',raw)
        self.assertEqual(self.state()['invoices'][0]['lines'][0]['venue'],'Renamed Hall, Revised address')
    def test_create_never_upserts_and_rename_conflicts_do_not_overwrite(self):
        first=self.create()['id'];before=self.venue(first)
        for name in ('Original Hall','original hall',' ORIGINAL HALL '):
            code,error=self.request('/api/contacts',{'kind':'venue','name':name,'address':'Wrong address','assigned_contact_id':None})
            self.assertEqual(code,400);self.assertIn('already exists',error['error']);self.assertEqual(self.venue(first),before)
        second=self.create('Second Hall')['id']
        self.assertEqual(self.request('/api/contacts',self.edit(second,name='ORIGINAL HALL'))[0],400)
        self.assertEqual(self.venue(second)['name'],'Second Hall')
    def test_missing_wrong_kind_and_deleted_ids_cannot_create_venues(self):
        for identifier in (self.contact['id'],999,True,'1',0):
            self.assertEqual(self.request('/api/contacts',{'kind':'venue','id':identifier,'name':'New name','address':'Address'})[0],400)
        venue=self.create();edit=self.edit(venue['id'],name='Renamed')
        self.post('/api/contacts/delete',{'id':venue['id'],'confirm_name':'Original Hall','confirmed':True})
        self.assertEqual(self.request('/api/contacts',edit)[0],400)
        self.assertFalse(any(c['kind']=='venue' for c in self.state()['contacts']))
    def test_stale_edit_and_invalid_owner_are_atomic(self):
        identifier=self.create()['id'];stale=self.edit(identifier,name='Stale name')
        self.post('/api/contacts',self.edit(identifier,address='Fresh address'))
        code,error=self.request('/api/contacts',stale);self.assertEqual(code,400);self.assertIn('changed',error['error'])
        self.assertEqual(self.venue(identifier)['address'],'Fresh address')
        self.assertEqual(self.request('/api/contacts',self.edit(identifier,name='Bad owner',assigned_contact_id=999))[0],400)
        self.assertEqual(self.venue(identifier)['name'],'Original Hall')
    def test_case_variant_legacy_records_can_be_edited_by_id(self):
        first=self.create('LEA')['id']
        with app.connection() as c:
            second=app.next_contact_id(c);c.execute("INSERT INTO contacts(id,kind,name,address,assigned_contact_id) VALUES(?,'venue','Lea','Second address',?)",(second,self.contact['id']))
        self.post('/api/contacts',self.edit(first,name='Property One'));self.post('/api/contacts',self.edit(second,name='Property Two'))
        self.assertEqual(self.venue(first)['name'],'Property One');self.assertEqual(self.venue(second)['name'],'Property Two')
    def test_explicit_assignment_change_and_shared_venue(self):
        identifier=self.create()['id']
        self.post('/api/contacts',self.edit(identifier,assigned_contact_id=None));self.assertIsNone(self.venue(identifier)['assigned_contact_id'])
        self.post('/api/contacts',self.edit(identifier,assigned_contact_id=self.contact['id']))
        self.assertEqual(self.venue(identifier)['assigned_contact_id'],self.contact['id'])
        self.assertTrue(self.venue(self.contact['id'])['has_assigned_venues'])
