from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from datetime import date
from decimal import Decimal, InvalidOperation
import json, sqlite3, os, logging, re
from documents import generate
BASE=Path(__file__).resolve().parent
DATA=Path(os.getenv('DATA_DIR','/data')); DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'invoices.sqlite3'
DEFAULTS=dict(name='',business='',address='',phone='',email='',website='',account_name='',account_number='',sort_code='',terms='Payment to be completed by bank transfer, within 7 days of the invoice date.')
def connection():
    c=sqlite3.connect(DB,timeout=120);c.row_factory=sqlite3.Row;return c
with connection() as c:
    c.executescript('''CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, next_number INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, address TEXT NOT NULL DEFAULT '', UNIQUE(kind,name));
CREATE TABLE IF NOT EXISTS invoices (number INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, body TEXT NOT NULL, settings TEXT NOT NULL, pdf BLOB NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);''')
    columns = {row['name'] for row in c.execute('PRAGMA table_info(contacts)')}
    for column in ('contact_name', 'email'):
        if column not in columns:
            c.execute(f"ALTER TABLE contacts ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    for column, declaration in [('separate_numbering','INTEGER NOT NULL DEFAULT 0'),('invoice_prefix',"TEXT NOT NULL DEFAULT ''"),('next_invoice_number','INTEGER NOT NULL DEFAULT 1'),('has_assigned_venues','INTEGER NOT NULL DEFAULT 0'),('assigned_contact_id','INTEGER')]:
        if column not in columns:
            c.execute(f'ALTER TABLE contacts ADD COLUMN {column} {declaration}')
    invoice_columns = {row['name'] for row in c.execute('PRAGMA table_info(invoices)')}
    for column, declaration in [('display_number','TEXT'),('sequence_number','INTEGER'),('contact_id','INTEGER'),('number_prefix',"TEXT NOT NULL DEFAULT ''")]:
        if column not in invoice_columns:
            c.execute(f'ALTER TABLE invoices ADD COLUMN {column} {declaration}')
    c.execute("UPDATE invoices SET display_number=printf('%04d',number),sequence_number=number WHERE display_number IS NULL")
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS invoice_display_number ON invoices(display_number)')
    c.execute('INSERT OR IGNORE INTO settings VALUES (1,?,1)',(json.dumps(DEFAULTS),))
def clean(value,limit=2000):
    if not isinstance(value,str) or len(value)>limit: raise ValueError('Invalid or overlong text field.')
    return value.strip()
def pence(v):
    try:
        x=Decimal(str(v))
        if not x.is_finite() or x<0 or x>1000000 or x.as_tuple().exponent < -2: raise ValueError('Amounts must be positive with at most two decimal places.')
        return int(x*100)
    except InvalidOperation: raise ValueError('Invalid amount.')
def valid_date(v):
    date.fromisoformat(v); return v

def invoice(raw):
    result={'customer':clean(raw.get('customer','')),'customer_address':clean(raw.get('customer_address',''),500),'customer_contact_name':clean(raw.get('customer_contact_name',''),200),'customer_email':clean(raw.get('customer_email',''),254),'date':valid_date(raw.get('date','')),'deposit':pence(raw.get('deposit',0)), 'lines':[]}
    if not result['customer']: raise ValueError('Choose or enter an invoice recipient.')
    lines=raw.get('lines',[])
    if not isinstance(lines,list) or not lines: raise ValueError('Add at least one service row.')
    for l in lines:
        row={'date':valid_date(l.get('date','')),'venue':clean(l.get('venue',''),500),'service':clean(l.get('service',''),500),'fee':pence(l.get('fee',''))}
        if not row['venue'] or not row['service']: raise ValueError('Every row needs a venue and service.')
        if l.get('venue_id') is not None:
            row['venue_id']=int(l['venue_id'])
        result['lines'].append(row)
    if result['deposit']>sum(l['fee'] for l in result['lines']):raise ValueError('Deposit cannot exceed the fees.')
    return result
def validate_venues(c,data):
    contact=c.execute("SELECT id FROM contacts WHERE kind='customer' AND name=?",(data['customer'],)).fetchone()
    contact_id=contact['id'] if contact else None
    for line in data['lines']:
        if 'venue_id' not in line:continue  # Preserve support for older API clients.
        venue=c.execute("SELECT * FROM contacts WHERE kind='venue' AND id=?",(line['venue_id'],)).fetchone()
        if not venue or venue['assigned_contact_id'] not in (None,contact_id):
            raise ValueError('A selected venue is not available for this contact. Refresh and choose another venue.')
        line['venue']=venue['name']+(', '+venue['address'] if venue['address'] else '')

class Handler(BaseHTTPRequestHandler):
    def reply(self,status,body,kind='application/json',name=None):
        if kind=='application/json':body=json.dumps(body).encode()
        self.send_response(status); self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        if name:self.send_header('Content-Disposition',f'attachment; filename="{name}"')
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if path in ('/','/app.js','/style.css'):
            file={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path]
            return self.reply(200,(BASE/'static'/file).read_bytes(),{'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path])
        if path=='/health':return self.reply(200,{'status':'ok'})
        with connection() as c:
            if path=='/api/state':
                s=c.execute('SELECT * FROM settings').fetchone()
                return self.reply(200,{'branding':{'business_name':os.getenv('BUSINESS_NAME','').strip()},'settings':json.loads(s['body']),'next':f"{s['next_number']:04d}",'contacts':[dict(r) for r in c.execute('SELECT * FROM contacts ORDER BY name')], 'invoices':[dict(**json.loads(r['body']),id=r['number'],number=r['display_number'],created=r['created']) for r in c.execute('SELECT number,display_number,body,created FROM invoices ORDER BY number DESC')]})
            m=re.fullmatch(r'/api/invoices/(\d+)/pdf',path)
            if m:
                r=c.execute('SELECT pdf,display_number FROM invoices WHERE number=?',(int(m[1]),)).fetchone()
                if r:return self.reply(200,r['pdf'],'application/pdf',f"Invoice-{r['display_number']}.pdf")
            if path=='/api/backup':
                import tempfile
                with tempfile.TemporaryDirectory() as t:
                    target=Path(t)/'backup.sqlite3'
                    with sqlite3.connect(target) as out:c.backup(out)
                    return self.reply(200,target.read_bytes(),'application/octet-stream','no-alias-backup.sqlite3')
        self.reply(404,{'error':'Not found'})
    def do_POST(self):
        # JSON + same-origin requests prevent cross-site form submissions.
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):return self.reply(403,{'error':'Invalid origin'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.reply(415,{'error':'JSON required'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=65536:raise ValueError('Invalid request size')
            raw=json.loads(self.rfile.read(size));path=urlparse(self.path).path
            with connection() as c:
                if path=='/api/invoices/remove-latest-test':
                    identifier=int(raw.get('id',raw.get('number',0)))
                    c.execute('BEGIN IMMEDIATE')
                    latest=c.execute('SELECT * FROM invoices ORDER BY number DESC LIMIT 1').fetchone()
                    if latest is None or identifier != latest['number']:
                        raise ValueError('Only the latest saved invoice can be removed. Refresh History.')
                    if raw.get('confirm') != latest['display_number']:
                        raise ValueError('Enter the invoice number to confirm removal.')
                    sequence=latest['sequence_number']
                    if latest['contact_id'] is None:
                        current=c.execute('SELECT next_number FROM settings WHERE id=1').fetchone()[0]
                        if current!=sequence+1:raise ValueError('The counter has changed since this invoice. It cannot be reset automatically.')
                        c.execute('UPDATE settings SET next_number=? WHERE id=1',(sequence,))
                    else:
                        contact=c.execute('SELECT * FROM contacts WHERE id=?',(latest['contact_id'],)).fetchone()
                        if not contact or contact['invoice_prefix']!=latest['number_prefix'] or contact['next_invoice_number']!=sequence+1:
                            raise ValueError('The contact counter has changed since this invoice. It cannot be reset automatically.')
                        c.execute('UPDATE contacts SET next_invoice_number=? WHERE id=?',(sequence,latest['contact_id']))
                    c.execute('DELETE FROM invoices WHERE number=?',(identifier,))
                    c.commit()
                    return self.reply(200,{'next':latest['display_number']})
                if path=='/api/contacts':
                    kind=raw.get('kind');name=clean(raw.get('name',''),200);address=clean(raw.get('address',''),500)
                    if kind not in ('customer','venue') or not name:raise ValueError('Enter a name.')
                    contact_name=clean(raw.get('contact_name',''),200) if kind=='customer' else ''
                    email=clean(raw.get('email',''),254) if kind=='customer' else ''
                    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Enter a valid email address.')
                    c.execute('BEGIN IMMEDIATE')
                    existing=c.execute('SELECT * FROM contacts WHERE kind=? AND name=?',(kind,name)).fetchone()
                    enabled=bool(raw.get('separate_numbering',False)) if kind=='customer' else False
                    prefix=clean(raw.get('invoice_prefix',existing['invoice_prefix'] if existing else ''),30) if kind=='customer' else ''
                    next_number=int(raw.get('next_invoice_number',existing['next_invoice_number'] if existing else 1))
                    if prefix and not re.fullmatch(r'[A-Za-z0-9_-]+',prefix):raise ValueError('Use only letters, numbers, hyphens or underscores in the prefix.')
                    if enabled and (not prefix or not re.search(r'[A-Za-z_-]',prefix)):raise ValueError('Enter a prefix containing a letter, hyphen or underscore.')
                    if next_number<1 or next_number>99999999:raise ValueError('Enter a next invoice number between 1 and 99999999.')
                    contact_id=existing['id'] if existing else -1
                    if enabled:
                        conflict=c.execute('SELECT id FROM contacts WHERE id!=? AND separate_numbering=1 AND invoice_prefix=?',(contact_id,prefix)).fetchone()
                        used=c.execute('SELECT number FROM invoices WHERE number_prefix=? AND (contact_id IS NULL OR contact_id!=?)',(prefix,contact_id)).fetchone()
                        if conflict or used:raise ValueError('This prefix is already used by another contact. Choose a different prefix.')
                        last=c.execute('SELECT COALESCE(MAX(sequence_number),0) FROM invoices WHERE contact_id=? AND number_prefix=?',(contact_id,prefix)).fetchone()[0]
                        if next_number<=last:raise ValueError('Next number must be higher than saved invoices for this contact and prefix.')
                    c.execute('INSERT INTO contacts(kind,name,address,contact_name,email,separate_numbering,invoice_prefix,next_invoice_number) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(kind,name) DO UPDATE SET address=excluded.address, contact_name=excluded.contact_name, email=excluded.email, separate_numbering=excluded.separate_numbering, invoice_prefix=excluded.invoice_prefix,next_invoice_number=excluded.next_invoice_number',(kind,name,address,contact_name,email,int(enabled),prefix,next_number))
                    if kind=='customer' and 'has_assigned_venues' in raw:
                        has_venues=bool(raw['has_assigned_venues'])
                        assigned=raw.get('assigned_venue_ids',[]) if has_venues else []
                        if not isinstance(assigned,list) or any(type(identifier) is not int for identifier in assigned):
                            raise ValueError('Choose valid saved venues.')
                        contact_id=c.execute("SELECT id FROM contacts WHERE kind='customer' AND name=?",(name,)).fetchone()[0]
                        for identifier in set(assigned):
                            venue=c.execute("SELECT * FROM contacts WHERE id=? AND kind='venue'",(identifier,)).fetchone()
                            if not venue:raise ValueError('A selected venue no longer exists. Refresh and try again.')
                            if venue['assigned_contact_id'] not in (None,contact_id):
                                raise ValueError('A selected venue is already assigned to another contact.')
                        c.execute('UPDATE contacts SET has_assigned_venues=? WHERE id=?',(int(has_venues),contact_id))
                        c.execute("UPDATE contacts SET assigned_contact_id=NULL WHERE kind='venue' AND assigned_contact_id=?",(contact_id,))
                        for identifier in set(assigned):
                            c.execute('UPDATE contacts SET assigned_contact_id=? WHERE id=?',(contact_id,identifier))
                    return self.reply(200,{'ok':True})
                if path=='/api/settings':
                    settings={k:clean(raw.get(k,'')) for k in DEFAULTS}
                    number=int(raw.get('next_number'))
                    c.execute('BEGIN IMMEDIATE')
                    last=c.execute('SELECT COALESCE(MAX(sequence_number),0) FROM invoices WHERE contact_id IS NULL').fetchone()[0]
                    if number<=last or number<1 or number>99999999:raise ValueError('Next number must be higher than all saved invoices.')
                    c.execute('UPDATE settings SET body=?,next_number=? WHERE id=1',(json.dumps(settings),number))
                    return self.reply(200,{'ok':True})
                if path in ('/api/preview','/api/invoices'):
                    data=invoice(raw)
                    if path=='/api/preview':
                        validate_venues(c,data)
                        settings=json.loads(c.execute('SELECT body FROM settings').fetchone()[0])
                        return self.reply(200,generate(data,settings,'DRAFT'),'application/pdf','Invoice-preview.pdf')
                    token=clean(raw.get('token',''),100)
                    if not token:raise ValueError('Missing save token')
                    c.execute('BEGIN IMMEDIATE')
                    old=c.execute('SELECT number,display_number FROM invoices WHERE token=?',(token,)).fetchone()
                    if old:return self.reply(200,{'id':old['number'],'number':old['display_number']})
                    validate_venues(c,data)
                    s=c.execute('SELECT * FROM settings').fetchone()
                    contact=c.execute("SELECT * FROM contacts WHERE kind='customer' AND name=?",(data['customer'],)).fetchone()
                    separate=contact is not None and bool(contact['separate_numbering'])
                    n=contact['next_invoice_number'] if separate else s['next_number']
                    prefix=contact['invoice_prefix'] if separate else ''
                    display=f'{prefix}{n:04d}'
                    if c.execute('SELECT 1 FROM invoices WHERE display_number=?',(display,)).fetchone():
                        raise ValueError('This invoice number already exists. Change the prefix or next number.')
                    identifier=c.execute('SELECT COALESCE(MAX(number),0)+1 FROM invoices').fetchone()[0]
                    pdf=generate(data,json.loads(s['body']),display)
                    c.execute('INSERT INTO invoices(number,token,body,settings,pdf,display_number,sequence_number,contact_id,number_prefix) VALUES (?,?,?,?,?,?,?,?,?)',(identifier,token,json.dumps(data),s['body'],pdf,display,n,contact['id'] if separate else None,prefix))
                    if separate:
                        c.execute('UPDATE contacts SET next_invoice_number=? WHERE id=?',(n+1,contact['id']))
                    else:
                        c.execute('UPDATE settings SET next_number=? WHERE id=1',(n+1,))
                    c.commit()
                    return self.reply(201,{'id':identifier,'number':display})
            self.reply(404,{'error':'Not found'})
        except (ValueError,TypeError,KeyError) as e:self.reply(400,{'error':str(e)})
        except Exception:
            logging.exception('Request failed');self.reply(500,{'error':'Unable to generate or save the invoice. Your number has not advanced. Check container logs.'})
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),Handler).serve_forever()
