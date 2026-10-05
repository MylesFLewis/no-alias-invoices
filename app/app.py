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
        result['lines'].append(row)
    if result['deposit']>sum(l['fee'] for l in result['lines']):raise ValueError('Deposit cannot exceed the fees.')
    return result
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
                return self.reply(200,{'branding':{'business_name':os.getenv('BUSINESS_NAME','').strip()},'settings':json.loads(s['body']),'next':f"{s['next_number']:04d}",'contacts':[dict(r) for r in c.execute('SELECT * FROM contacts ORDER BY name')], 'invoices':[dict(number=f"{r['number']:04d}", **json.loads(r['body']),created=r['created']) for r in c.execute('SELECT number,body,created FROM invoices ORDER BY number DESC')]})
            m=re.fullmatch(r'/api/invoices/(\d+)/pdf',path)
            if m:
                r=c.execute('SELECT pdf FROM invoices WHERE number=?',(int(m[1]),)).fetchone()
                if r:return self.reply(200,r['pdf'],'application/pdf',f'No-Alias-Invoice-{int(m[1]):04d}.pdf')
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
                    number=int(raw.get('number',0))
                    if raw.get('confirm') != f'{number:04d}':
                        raise ValueError('Enter the invoice number to confirm removal.')
                    c.execute('BEGIN IMMEDIATE')
                    latest=c.execute('SELECT MAX(number) FROM invoices').fetchone()[0]
                    if latest is None or number != latest:
                        raise ValueError('Only the latest saved invoice can be removed. Refresh History.')
                    c.execute('DELETE FROM invoices WHERE number=?',(number,))
                    c.execute('UPDATE settings SET next_number=? WHERE id=1',(number,))
                    c.commit()
                    return self.reply(200,{'next':f'{number:04d}'})
                if path=='/api/contacts':
                    kind=raw.get('kind');name=clean(raw.get('name',''),200);address=clean(raw.get('address',''),500)
                    if kind not in ('customer','venue') or not name:raise ValueError('Enter a name.')
                    contact_name=clean(raw.get('contact_name',''),200) if kind=='customer' else ''
                    email=clean(raw.get('email',''),254) if kind=='customer' else ''
                    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Enter a valid email address.')
                    c.execute('INSERT INTO contacts(kind,name,address,contact_name,email) VALUES (?,?,?,?,?) ON CONFLICT(kind,name) DO UPDATE SET address=excluded.address, contact_name=excluded.contact_name, email=excluded.email',(kind,name,address,contact_name,email))
                    return self.reply(200,{'ok':True})
                if path=='/api/settings':
                    settings={k:clean(raw.get(k,'')) for k in DEFAULTS}
                    number=int(raw.get('next_number'))
                    c.execute('BEGIN IMMEDIATE')
                    last=c.execute('SELECT COALESCE(MAX(number),0) FROM invoices').fetchone()[0]
                    if number<=last or number<1 or number>99999999:raise ValueError('Next number must be higher than all saved invoices.')
                    c.execute('UPDATE settings SET body=?,next_number=? WHERE id=1',(json.dumps(settings),number))
                    return self.reply(200,{'ok':True})
                if path in ('/api/preview','/api/invoices'):
                    data=invoice(raw)
                    if path=='/api/preview':
                        settings=json.loads(c.execute('SELECT body FROM settings').fetchone()[0])
                        return self.reply(200,generate(data,settings,'DRAFT'),'application/pdf','Invoice-preview.pdf')
                    token=clean(raw.get('token',''),100)
                    if not token:raise ValueError('Missing save token')
                    c.execute('BEGIN IMMEDIATE')
                    old=c.execute('SELECT number FROM invoices WHERE token=?',(token,)).fetchone()
                    if old:return self.reply(200,{'number':f"{old[0]:04d}"})
                    s=c.execute('SELECT * FROM settings').fetchone();n=s['next_number']
                    pdf=generate(data,json.loads(s['body']),f'{n:04d}')
                    c.execute('INSERT INTO invoices(number,token,body,settings,pdf) VALUES (?,?,?,?,?)',(n,token,json.dumps(data),s['body'],pdf))
                    c.execute('UPDATE settings SET next_number=? WHERE id=1',(n+1,))
                    c.commit()
                    return self.reply(201,{'number':f'{n:04d}'})
            self.reply(404,{'error':'Not found'})
        except (ValueError,TypeError,KeyError) as e:self.reply(400,{'error':str(e)})
        except Exception:
            logging.exception('Request failed');self.reply(500,{'error':'Unable to generate or save the invoice. Your number has not advanced. Check container logs.'})
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    ThreadingHTTPServer(('0.0.0.0',int(os.getenv('PORT','8080'))),Handler).serve_forever()
