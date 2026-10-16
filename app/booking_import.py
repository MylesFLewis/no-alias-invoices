"""Narrow, server-to-server booking import; no credentials reach the browser."""
import hashlib
import hmac
import json
import os
import re
import time


def key():
    value=os.getenv('BOOKINGS_API_KEY','').strip()
    return value if re.fullmatch(r'[A-Za-z0-9_-]{32,128}',value) else None


def authorized(header):
    secret=key()
    return bool(secret and isinstance(header,str) and header.isascii() and hmac.compare_digest(header,'Bearer '+secret))


def migrate(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS booking_invoices (
        source TEXT NOT NULL, booking TEXT NOT NULL, reference TEXT NOT NULL,
        invoice_id INTEGER NOT NULL, display_number TEXT NOT NULL, PRIMARY KEY(source,booking));
        CREATE TABLE IF NOT EXISTS booking_api_requests(requested REAL NOT NULL);''')


def identity(raw):
    if not isinstance(raw,dict):raise ValueError('Submit a booking object.')
    values=tuple(raw.get(k) for k in ('source','booking'))
    if any(not isinstance(v,str) or not re.fullmatch(r'[0-9a-f]{32}',v) for v in values):
        raise ValueError('Invalid booking identity.')
    return values


def status(c,raw,mail_status):
    row=c.execute('SELECT * FROM booking_invoices WHERE source=? AND booking=?',identity(raw)).fetchone()
    if not row:return {'created':False}
    exists=c.execute('SELECT 1 FROM invoices WHERE number=?',(row['invoice_id'],)).fetchone()
    # Keep the tombstone if a test invoice is removed: its number may be reused.
    return {'created':True,'removed':not bool(exists),'id':row['invoice_id'],'number':row['display_number'],
            'email':mail_status(c,row['invoice_id']) if exists else None}


def contacts(c):
    return [dict(r) for r in c.execute("SELECT id,name,contact_name,email,address,payment_term_days,separate_numbering,invoice_prefix,next_invoice_number FROM contacts WHERE kind='customer' ORDER BY name")]


def prepare(c,raw,normalise,address):
    identity(raw)
    reference=raw.get('reference','')
    if not isinstance(reference,str) or len(reference)>160:raise ValueError('Invalid booking reference.')
    choice=raw.get('contact')
    if not isinstance(choice,dict):raise ValueError('Choose an existing contact or create a new contact.')
    if choice.get('mode')=='existing':
        if type(choice.get('id')) is not int:raise ValueError('Choose a saved contact.')
        contact=c.execute("SELECT * FROM contacts WHERE kind='customer' AND id=?",(choice['id'],)).fetchone()
        if contact is None:raise ValueError('Contact no longer exists. Review again.')
        selected=dict(contact)
    elif choice.get('mode')=='new':
        selected={}
        for field,limit in [('name',200),('contact_name',200),('email',254),('address',500)]:
            value=choice.get(field,'')
            if not isinstance(value,str) or len(value)>limit:raise ValueError('Invalid new contact '+field+'.')
            selected[field]=value.strip()
        if not selected['name']:raise ValueError('Enter the company or individual name.')
        if selected['email']:selected['email']=address(selected['email'])
        if any(r['name'].casefold()==selected['name'].casefold() for r in c.execute("SELECT name FROM contacts WHERE kind='customer'")):
            raise ValueError('A contact with this name already exists. Select it rather than creating a duplicate.')
    else:raise ValueError('Choose an existing contact or create a new contact.')
    draft=raw.get('draft')
    if not isinstance(draft,dict) or len(draft.get('lines',[]))!=1:raise ValueError('Review one booking service.')
    draft=dict(draft)
    draft.update(customer=selected['name'],customer_contact_name=selected['contact_name'],customer_email=selected['email'],customer_address=selected['address'])
    data=normalise(draft)
    if 'venue_id' in data['lines'][0]:raise ValueError('Use the reviewed event venue text for booking imports.')
    email=raw.get('email_invoice',False)
    if type(email) is not bool:raise ValueError('Choose whether to email the invoice.')
    if email and not selected['email']:raise ValueError('The invoice contact needs an email address.')
    # Sign both the reviewed proposal and live dependencies; stale reviews fail.
    dependencies={'proposal':{'source':raw['source'],'booking':raw['booking'],'reference':reference,'contact':selected,'data':data,'email':email},
        'settings':dict(c.execute('SELECT * FROM settings WHERE id=1').fetchone()),
        'template':dict(c.execute('SELECT * FROM invoice_email_template WHERE id=1').fetchone())}
    signature=hmac.new(key().encode(),json.dumps(dependencies,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    draft.update(email_invoice=email,email_recipient=selected['email'],email_contact_id=selected.get('id'),token='booking:'+raw['source']+':'+raw['booking'])
    return draft,selected,signature
