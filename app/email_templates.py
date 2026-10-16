"""Fixed-field invoice templates with sanitised HTML and a plain-text alternative."""
import html
import json
import os
import re
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit

import nh3

DEFAULT_SUBJECT='Invoice {{invoice_number}}'
DEFAULT_HTML='''<p>Hello {{client_name}},</p>
<p>Please find invoice <strong>{{invoice_number}}</strong> attached as a PDF.</p>
<p>Amount due: <strong>{{amount_due}}</strong></p>
<p>The invoice contains the payment details and terms.</p>
<p>Kind regards,<br>{{business_name}}</p>'''
FIELDS={
    'invoice_number':'Invoice number','client_name':'Client name','company_name':'Client company',
    'client_email':'Client email','invoice_date':'Invoice date','due_date':'Due date',
    'amount_due':'Amount due','business_name':'Business name','business_email':'Business email',
    'business_phone':'Business phone','business_address':'Business address','payment_terms':'Payment terms'}
TOKEN=re.compile(r'{{\s*([a-z_]+)\s*}}')
TAGS={'p','div','span','br','strong','b','em','i','u','s','strike','h1','h2','h3','ul','ol','li','blockquote','hr','a','img'}


def safe_url(value,image=False):
    if not isinstance(value,str) or len(value)>2048 or any(ord(c)<33 or ord(c)==127 for c in value):return None
    try:
        parsed=urlsplit(value)
        if parsed.scheme in (('https',) if image else ('https','http')) and parsed.hostname and not parsed.username and not parsed.password:
            return value
        if not image and parsed.scheme=='mailto' and not parsed.query and not parsed.fragment and re.fullmatch(r'[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+',parsed.path):
            return value
    except ValueError:pass
    return None


def safe_style(value):
    result=[]
    for item in value.split(';'):
        if ':' not in item:continue
        key,val=(part.strip().lower() for part in item.split(':',1))
        valid=False
        if key in ('color','background-color'):
            valid=bool(re.fullmatch(r'#[0-9a-f]{3}(?:[0-9a-f]{3})?|rgba?\([0-9.,% ]+\)',val)) or val in {'black','white','red','blue','green','gray','grey','orange','purple','transparent'}
        elif key=='text-align':valid=val in ('left','center','right','justify')
        elif key=='font-weight':valid=val in ('normal','bold','400','600','700')
        elif key=='font-style':valid=val in ('normal','italic')
        elif key=='text-decoration':valid=val in ('none','underline','line-through')
        elif key=='font-size':valid=bool(re.fullmatch(r'(?:[1-3][0-9]|4[0-8])px|(?:small|medium|large|x-large|xx-large)',val))
        elif key=='font-family':valid=val in ('arial','arial, sans-serif','georgia','verdana','tahoma','times new roman','sans-serif','serif')
        elif key=='line-height':valid=val in ('1','1.2','1.4','1.5','1.6','2')
        elif key in ('margin','margin-top','margin-bottom'):valid=bool(re.fullmatch(r'0|(?:[0-3]?[0-9]|4[0-8])px',val))
        if valid:result.append(key+':'+val)
    return ';'.join(result) or None


def attribute(tag,name,value):
    if name=='style':return safe_style(value)
    if name=='href':return safe_url(value)
    if name=='src':return safe_url(value,image=True)
    if name in ('width','height'):
        return value if re.fullmatch(r'[1-9][0-9]{0,2}',value) and int(value)<=600 else None
    if name in ('alt','title'):return value[:300]
    return None


CLEANER=nh3.Cleaner(tags=TAGS,attributes={'*':{'style'},'a':{'href','title'},'img':{'src','alt','width','height'}},
    clean_content_tags={'script','style','iframe','object','embed','svg','math','template','form'},
    attribute_filter=attribute,strip_comments=True,url_schemes={'http','https','mailto'},url_relative='deny')


class PlainText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_starttag(self,tag,attrs):
        attributes=dict(attrs)
        if tag in ('p','div','h1','h2','h3','blockquote','ul','ol','hr'):self.parts.append('\n')
        if tag=='li':self.parts.append('\n• ')
        if tag=='br':self.parts.append('\n')
        if tag=='img' and attributes.get('alt'):self.parts.append('['+attributes['alt']+']')
        if tag=='a' and attributes.get('href'):self.parts.append('['+attributes['href']+'] ')
    def handle_endtag(self,tag):
        if tag in ('p','div','h1','h2','h3','blockquote','li'):self.parts.append('\n')
    def handle_data(self,value):self.parts.append(value)


def plain_text(body):
    parser=PlainText();parser.feed(body)
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',''.join(parser.parts)).strip()


def clean_html(body):
    if not isinstance(body,str) or len(body.encode('utf-8'))>30000:
        raise ValueError('Use an email body up to 30 KB.')
    return CLEANER.clean(body)


def validate(subject,body):
    if not isinstance(subject,str) or not 1<=len(subject.strip())<=200 or any(ord(c)<32 or ord(c)==127 for c in subject):
        raise ValueError('Use a subject from 1 to 200 characters without line breaks.')
    body=clean_html(body)
    if not plain_text(body):raise ValueError('Enter some text for the email body.')
    for source in (subject,body):
        for token in TOKEN.findall(source):
            if token not in FIELDS:raise ValueError('Unknown email field: '+token)
        remaining=TOKEN.sub('',source)
        if '{{' in remaining or '}}' in remaining:raise ValueError('Use the Insert field menu for valid email fields.')
        if len(TOKEN.findall(source))>100:raise ValueError('Use no more than 100 field references in each template part.')
    return subject.strip(),body


def migrate(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS invoice_email_template (
        id INTEGER PRIMARY KEY CHECK(id=1),subject TEXT NOT NULL,html TEXT NOT NULL,version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS invoice_email_content (
        invoice_id INTEGER PRIMARY KEY,subject TEXT NOT NULL,html TEXT NOT NULL,plain TEXT NOT NULL);''')
    c.execute('INSERT OR IGNORE INTO invoice_email_template VALUES(1,?,?,1)',(DEFAULT_SUBJECT,DEFAULT_HTML))


def get(c):
    row=c.execute('SELECT subject,html,version FROM invoice_email_template WHERE id=1').fetchone()
    return dict(row)


def save(c,raw):
    version=raw.get('version')
    if type(version) is not int or version<1:raise ValueError('Reload the email template before saving.')
    subject,body=validate(raw.get('subject'),raw.get('html'))
    changed=c.execute('UPDATE invoice_email_template SET subject=?,html=?,version=version+1 WHERE id=1 AND version=?',(subject,body,version))
    if changed.rowcount!=1:raise ValueError('The email template changed in another window. Reload it before saving.')
    return get(c)


def uk(value):
    try:return date.fromisoformat(value).strftime('%d/%m/%Y')
    except (ValueError,TypeError):return ''


def context(body,settings,number):
    amount=sum(row.get('fee',0) for row in body.get('lines',[]))-body.get('deposit',0)
    terms=settings.get('terms','')
    if body.get('payment_term_days') is not None:
        terms='Payment is due on '+(uk(body.get('due_date')) or 'the date stated on the attached invoice')+'.'
    return {'invoice_number':str(number),'client_name':body.get('customer_contact_name') or body.get('customer') or 'Customer',
        'company_name':body.get('customer',''),'client_email':body.get('customer_email',''),
        'invoice_date':uk(body.get('date')),'due_date':uk(body.get('due_date')) or 'As stated on the attached invoice',
        'amount_due':'£{:,.2f}'.format(amount/100),'business_name':settings.get('business') or 'No Alias Entertainment',
        'business_email':settings.get('email',''),'business_phone':settings.get('phone',''),
        'business_address':settings.get('address',''),'payment_terms':terms}


def render(subject,body,values):
    subject,body=validate(subject,body)
    rendered_subject=TOKEN.sub(lambda match:str(values.get(match[1],'')),subject)
    rendered_subject=re.sub(r'[\x00-\x1f\x7f]+',' ',rendered_subject)
    rendered_subject=re.sub(r'\s+',' ',rendered_subject).strip()
    if not rendered_subject or len(rendered_subject)>400:raise ValueError('The rendered email subject is empty or too long.')
    rendered=TOKEN.sub(lambda match:html.escape(str(values.get(match[1],'')),quote=True).replace('\n','<br>'),body)
    if len(rendered.encode('utf-8'))>120000:raise ValueError('The rendered email is too large. Use fewer repeated fields.')
    rendered=CLEANER.clean(rendered)
    document='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https:; base-uri 'none'; form-action 'none'"></head><body style="margin:0;padding:24px;background-color:#f4f5f7;font-family:Arial,sans-serif;color:#19212b"><div style="max-width:600px;margin:auto;padding:24px;background-color:#ffffff">'''+rendered+'</div></body></html>'
    return {'subject':rendered_subject,'html':document,'plain':plain_text(rendered)}


def snapshot(c,identifier):
    row=c.execute('SELECT body,settings,display_number FROM invoices WHERE number=?',(identifier,)).fetchone()
    if row is None:raise ValueError('Save the invoice before queueing email.')
    template=get(c);settings=json.loads(row['settings']);settings['business']=os.getenv('BUSINESS_NAME','').strip() or settings.get('business','')
    values=context(json.loads(row['body']),settings,row['display_number'])
    result=render(template['subject'],template['html'],values)
    c.execute('INSERT INTO invoice_email_content VALUES(?,?,?,?)',(identifier,result['subject'],result['html'],result['plain']))


def preview(subject,body):
    values=context({'customer':'Example Client Ltd','customer_contact_name':'Alex Example','customer_email':'alex@example.com',
        'date':'2026-10-16','due_date':'2026-10-30','lines':[{'fee':25000}],'deposit':5000},
        {'business':'Your business','email':'hello@example.com','phone':'01234 567890','address':'Example business address','terms':'Please pay within 14 days.'},'DEMO0169')
    return render(subject,body,values)
