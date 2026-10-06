from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json, sqlite3, os, logging, re, tempfile, csv, io, hashlib
from documents import generate
BASE=Path(__file__).resolve().parent
DATA=Path(os.getenv('DATA_DIR','/data')); DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'invoices.sqlite3'
DEFAULTS=dict(name='',business='',address='',phone='',email='',website='',account_name='',account_number='',sort_code='',terms='Payment to be completed by bank transfer, within 7 days of the invoice date.')
def connection():
    c=sqlite3.connect(DB,timeout=120);c.row_factory=sqlite3.Row;return c
with connection() as c:
    c.executescript('''CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, next_number INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS retired_contact_ids (id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, address TEXT NOT NULL DEFAULT '', UNIQUE(kind,name));
CREATE TABLE IF NOT EXISTS invoices (number INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, body TEXT NOT NULL, settings TEXT NOT NULL, pdf BLOB NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);''')
    columns = {row['name'] for row in c.execute('PRAGMA table_info(contacts)')}
    for column in ('contact_name', 'email'):
        if column not in columns:
            c.execute(f"ALTER TABLE contacts ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    for column, declaration in [('separate_numbering','INTEGER NOT NULL DEFAULT 0'),('invoice_prefix',"TEXT NOT NULL DEFAULT ''"),('next_invoice_number','INTEGER NOT NULL DEFAULT 1'),('has_assigned_venues','INTEGER NOT NULL DEFAULT 0'),('assigned_contact_id','INTEGER'),('payment_term_days','INTEGER')]:
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

def next_contact_id(c):
    return c.execute('SELECT COALESCE(MAX(id),0)+1 FROM (SELECT id FROM contacts UNION ALL SELECT id FROM retired_contact_ids)').fetchone()[0]

def invoice(raw):
    result={'customer':clean(raw.get('customer','')),'customer_address':clean(raw.get('customer_address',''),500),'customer_contact_name':clean(raw.get('customer_contact_name',''),200),'customer_email':clean(raw.get('customer_email',''),254),'date':valid_date(raw.get('date','')),'deposit':pence(raw.get('deposit',0)), 'lines':[]}
    if not result['customer']: raise ValueError('Choose or enter an invoice recipient.')
    lines=raw.get('lines',[])
    if not isinstance(lines,list) or not lines: raise ValueError('Add at least one service row.')
    for l in lines:
        row={'date':valid_date(l.get('date','')),'other_details':clean(l.get('other_details',''),1000),'work_order_number':clean(l.get('work_order_number',''),200),'venue':clean(l.get('venue',''),500),'service':clean(l.get('service',''),500),'fee':pence(l.get('fee',''))}
        if not row['venue'] or not row['service']: raise ValueError('Every row needs a venue and service.')
        if l.get('venue_id') is not None:
            row['venue_id']=int(l['venue_id'])
        result['lines'].append(row)
    if result['deposit']>sum(l['fee'] for l in result['lines']):raise ValueError('Deposit cannot exceed the fees.')
    return result
def contact_payment_terms(c,data):
    row=c.execute("SELECT payment_term_days FROM contacts WHERE kind='customer' AND name=?",(data['customer'],)).fetchone()
    days=row['payment_term_days'] if row else None
    data['payment_term_days']=days
    try:
        data['due_date']=(date.fromisoformat(data['date'])+timedelta(days=days)).isoformat() if days is not None else None
    except OverflowError:
        raise ValueError('The calculated due date falls outside the supported date range.')

def validate_venues(c,data):
    contact=c.execute("SELECT id FROM contacts WHERE kind='customer' AND name=?",(data['customer'],)).fetchone()
    contact_id=contact['id'] if contact else None
    for line in data['lines']:
        if 'venue_id' not in line:continue  # Preserve support for older API clients.
        venue=c.execute("SELECT * FROM contacts WHERE kind='venue' AND id=?",(line['venue_id'],)).fetchone()
        if not venue or venue['assigned_contact_id'] not in (None,contact_id):
            raise ValueError('A selected venue is not available for this contact. Refresh and choose another venue.')
        line['venue']=venue['name']+(', '+venue['address'] if venue['address'] else '')

def invoice_file(number):
    if not re.fullmatch(r'[A-Za-z0-9_-]+',number):raise ValueError('Invalid invoice filename.')
    return DATA / 'invoices' / f'{number} Invoice.pdf'

def export_invoice(number,pdf):
    temporary=None
    try:
        target=invoice_file(number)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if target.read_bytes()==pdf:return None
            raise OSError('A different file already exists with this invoice filename.')
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.invoice-',suffix='.tmp',delete=False) as output:
            temporary=Path(output.name);os.fchmod(output.fileno(),0o644);output.write(pdf);output.flush();os.fsync(output.fileno())
        os.replace(temporary,target)
        return None
    except (OSError,ValueError):
        logging.exception('Invoice folder copy failed for %s',number)
        return 'Invoice saved in History, but the folder copy failed. Check the Invoice PDF folder mapping, permissions and existing files. Download it from History if needed.'
    finally:
        if temporary is not None:
            try:temporary.unlink(missing_ok=True)
            except OSError:logging.exception('Temporary invoice copy cleanup failed')

def remove_export(number,pdf):
    try:
        target=invoice_file(number)
        if target.exists() and target.read_bytes()==pdf:target.unlink()
        elif target.exists():return 'Test invoice removed from History, but its folder copy was kept because the file had changed.'
    except (OSError,ValueError):
        logging.exception('Test invoice folder cleanup failed')
        return 'Test invoice removed from History, but its folder copy could not be removed. Delete that test PDF from the invoice folder before reusing its number.'
    return None

def saved_result(identifier,number,pdf):
    result={'id':identifier,'number':number}
    warning=export_invoice(number,pdf)
    if warning:result['warning']=warning
    return result

def venue_csv_plan(c,content):
    if not isinstance(content,str) or len(content.encode('utf-8'))>1024*1024:
        raise ValueError('Choose a CSV file up to 1 MB.')
    reader=csv.DictReader(io.StringIO(content.lstrip('\ufeff'),newline=''),strict=True)
    try:headings=reader.fieldnames or []
    except csv.Error as error:raise ValueError('Invalid CSV: '+str(error))
    normalized=[heading.strip().casefold() for heading in headings]
    expected=['venue name','address','company name']
    if len(normalized)!=3 or set(normalized)!=set(expected):
        raise ValueError('CSV headings must be Venue name, Address, Company name.')
    contacts={};venues={}
    for entry in c.execute('SELECT * FROM contacts'):
        target=contacts if entry['kind']=='customer' else venues
        target.setdefault(entry['name'].strip().casefold(),[]).append(dict(entry))
    rows=[];seen=set()
    try:
        for raw in reader:
            if len(rows)>=1000:raise ValueError('Import at most 1000 venues at a time.')
            values={heading.strip().casefold():raw.get(heading) for heading in headings}
            if all(value is not None and not value.strip() for value in values.values()) and None not in raw:continue
            row={'row':reader.line_num,'name':values['venue name'] or '', 'address':values['address'] or '', 'company':values['company name'] or '', 'action':'Create','error':''}
            rows.append(row)
            try:
                if None in raw or any(value is None for value in values.values()):raise ValueError('Row must contain exactly three columns.')
                row['name']=clean(row['name'],200);row['address']=clean(row['address'],500);row['company']=clean(row['company'],200)
                if not row['name']:raise ValueError('Venue name is required.')
                key=row['name'].casefold()
                if key in seen:raise ValueError('This venue is listed more than once in the CSV.')
                seen.add(key)
                matches=venues.get(key,[])
                if len(matches)>1:raise ValueError('Multiple saved venues match this name; resolve the duplicates first.')
                existing=matches[0] if matches else None
                owner=None
                if row['company']:
                    matches=contacts.get(row['company'].casefold(),[])
                    if not matches:raise ValueError('Company name does not match a saved contact.')
                    if len(matches)>1:raise ValueError('Multiple contacts match this company name.')
                    owner=matches[0];row['company']=owner['name']
                owner_id=owner['id'] if owner else None
                if existing and existing['assigned_contact_id'] not in (None,owner_id):
                    raise ValueError('Venue is assigned to another contact. Release it from that contact before importing.')
                row['venue_id']=existing['id'] if existing else None
                row['contact_id']=owner_id
                row['before']={'address':existing['address'],'owner':existing['assigned_contact_id']} if existing else None
                if existing:
                    row['name']=existing['name']
                    row['action']='Unchanged' if existing['address']==row['address'] and existing['assigned_contact_id']==owner_id else 'Update'
            except (ValueError,TypeError) as error:row['error']=str(error)
    except csv.Error as error:raise ValueError('Invalid CSV: '+str(error))
    if not rows:raise ValueError('The CSV contains no venue rows.')
    fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return dict(rows=rows,preview_hash=fingerprint,can_import=not any(row['error'] for row in rows),counts={label:sum(row['action']==label and not row['error'] for row in rows) for label in ['Create','Update','Unchanged']},errors=sum(bool(row['error']) for row in rows))

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
        if path=='/api/venues/csv-template':return self.reply(200,b'Venue name,Address,Company name\r\n','text/csv; charset=utf-8','venue-import-template.csv')
        if path=='/health':return self.reply(200,{'status':'ok'})
        with connection() as c:
            if path=='/api/state':
                s=c.execute('SELECT * FROM settings').fetchone()
                return self.reply(200,{'branding':{'business_name':os.getenv('BUSINESS_NAME','').strip()},'settings':json.loads(s['body']),'next':f"{s['next_number']:04d}",'contacts':[dict(r) for r in c.execute('SELECT * FROM contacts ORDER BY name')], 'invoices':[dict(**json.loads(r['body']),id=r['number'],number=r['display_number'],created=r['created']) for r in c.execute('SELECT number,display_number,body,created FROM invoices ORDER BY number DESC')]})
            m=re.fullmatch(r'/api/invoices/(\d+)/pdf',path)
            if m:
                r=c.execute('SELECT pdf,display_number FROM invoices WHERE number=?',(int(m[1]),)).fetchone()
                if r:return self.reply(200,r['pdf'],'application/pdf',f"{r['display_number']} Invoice.pdf")
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
            path=urlparse(self.path).path
            size=int(self.headers.get('Content-Length','0'))
            limit=2*1024*1024 if path in ('/api/venues/csv-preview','/api/venues/csv-import') else 65536
            if not 0<size<=limit:raise ValueError('Invalid request size')
            raw=json.loads(self.rfile.read(size))
            with connection() as c:
                if path in ('/api/venues/csv-preview','/api/venues/csv-import'):
                    if path.endswith('csv-import'):c.execute('BEGIN IMMEDIATE')
                    plan=venue_csv_plan(c,raw.get('csv',''))
                    if path.endswith('csv-preview'):return self.reply(200,plan)
                    if not plan['can_import']:raise ValueError('Fix all CSV errors before importing. No venues were changed.')
                    if raw.get('preview_hash')!=plan['preview_hash']:
                        raise ValueError('The CSV or saved details changed after the preview. Preview again before importing.')
                    for row in plan['rows']:
                        if row['venue_id'] is None:
                            c.execute("INSERT INTO contacts(id,kind,name,address,assigned_contact_id) VALUES(?,'venue',?,?,?)",(next_contact_id(c),row['name'],row['address'],row['contact_id']))
                        else:
                            c.execute('UPDATE contacts SET address=?,assigned_contact_id=? WHERE id=?',(row['address'],row['contact_id'],row['venue_id']))
                        if row['contact_id'] is not None:
                            c.execute('UPDATE contacts SET has_assigned_venues=1 WHERE id=?',(row['contact_id'],))
                    c.commit()
                    return self.reply(200,{'counts':plan['counts']})
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
                    result={'next':latest['display_number']}
                    warning=remove_export(latest['display_number'],latest['pdf'])
                    if warning:result['warning']=warning
                    return self.reply(200,result)
                if path=='/api/contacts/delete':
                    c.execute('BEGIN IMMEDIATE')
                    entry=c.execute('SELECT * FROM contacts WHERE id=?',(int(raw.get('id',0)),)).fetchone()
                    if not entry:raise ValueError('This contact or venue no longer exists.')
                    if raw.get('confirm_name')!=entry['name'] or raw.get('confirmed') is not True:
                        raise ValueError('Both deletion confirmations are required.')
                    if entry['kind']=='customer':
                        c.execute("UPDATE contacts SET assigned_contact_id=NULL WHERE kind='venue' AND assigned_contact_id=?",(entry['id'],))
                    c.execute('INSERT OR IGNORE INTO retired_contact_ids(id) VALUES(?)',(entry['id'],))
                    c.execute('DELETE FROM contacts WHERE id=?',(entry['id'],))
                    c.commit()
                    return self.reply(200,{'deleted':entry['id']})
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
                    c.execute('INSERT INTO contacts(id,kind,name,address,contact_name,email,separate_numbering,invoice_prefix,next_invoice_number) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(kind,name) DO UPDATE SET address=excluded.address, contact_name=excluded.contact_name, email=excluded.email, separate_numbering=excluded.separate_numbering, invoice_prefix=excluded.invoice_prefix,next_invoice_number=excluded.next_invoice_number',(existing['id'] if existing else next_contact_id(c),kind,name,address,contact_name,email,int(enabled),prefix,next_number))
                    if kind=='venue' and 'assigned_contact_id' in raw:
                        owner=raw['assigned_contact_id']
                        if owner is not None:
                            if type(owner) is not int or not c.execute("SELECT id FROM contacts WHERE kind='customer' AND id=?",(owner,)).fetchone():
                                raise ValueError('Choose a valid saved contact, or Available to all contacts.')
                            c.execute('UPDATE contacts SET has_assigned_venues=1 WHERE id=?',(owner,))
                        c.execute("UPDATE contacts SET assigned_contact_id=? WHERE kind='venue' AND name=?",(owner,name))
                    if kind=='customer' and 'payment_term_days' in raw:
                        days=raw['payment_term_days']
                        if days in (None,''):days=None
                        elif type(days) is not int or not 0<=days<=3650:
                            raise ValueError('Payment term days must be a whole number between 0 and 3650, or blank.')
                        c.execute("UPDATE contacts SET payment_term_days=? WHERE kind='customer' AND name=?",(days,name))
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
                        contact_payment_terms(c,data)
                        validate_venues(c,data)
                        settings=json.loads(c.execute('SELECT body FROM settings').fetchone()[0])
                        return self.reply(200,generate(data,settings,'DRAFT'),'application/pdf','Invoice-preview.pdf')
                    token=clean(raw.get('token',''),100)
                    if not token:raise ValueError('Missing save token')
                    c.execute('BEGIN IMMEDIATE')
                    old=c.execute('SELECT number,display_number,pdf FROM invoices WHERE token=?',(token,)).fetchone()
                    if old:return self.reply(200,saved_result(old['number'],old['display_number'],old['pdf']))
                    contact_payment_terms(c,data)
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
                    return self.reply(201,saved_result(identifier,display,pdf))
            self.reply(404,{'error':'Not found'})
        except (ValueError,TypeError,KeyError) as e:self.reply(400,{'error':str(e)})
        except Exception:
            logging.exception('Request failed');self.reply(500,{'error':'Unable to generate or save the invoice. Your number has not advanced. Check container logs.'})
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),Handler).serve_forever()
