"""Bounded delivery metadata only: never retain provider bodies or credentials."""
import os
import re
import secrets
import uuid

CATEGORIES={'configuration','authentication','permission','recipient','sender','rejected','throttled','provider_unavailable','connection','tls','interrupted','unknown','pdf'}
GUID=re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')


def provider():
    value=os.getenv('EMAIL_PROVIDER','smtp').strip().lower()
    return value if value in ('smtp','microsoft_graph') else 'unknown'


def migrate(c):
    c.execute('''CREATE TABLE IF NOT EXISTS invoice_mail_attempts (
        ref TEXT PRIMARY KEY, invoice_id INTEGER NOT NULL, provider TEXT NOT NULL,
        state TEXT NOT NULL, category TEXT NOT NULL DEFAULT '', queued_at REAL NOT NULL,
        started_at REAL, finished_at REAL, protocol_code INTEGER, request_id TEXT NOT NULL DEFAULT '',
        client_request_id TEXT NOT NULL DEFAULT '', retry_after INTEGER)''')
    c.execute('CREATE INDEX IF NOT EXISTS mail_attempt_invoice ON invoice_mail_attempts(invoice_id,queued_at)')


def queued(c,identifier,clock):
    ref=secrets.token_hex(12)
    c.execute("INSERT INTO invoice_mail_attempts(ref,invoice_id,provider,state,queued_at) VALUES(?,?,?,'pending',?)",(ref,identifier,provider(),clock))
    c.execute('DELETE FROM invoice_mail_attempts WHERE invoice_id=? AND ref NOT IN (SELECT ref FROM invoice_mail_attempts WHERE invoice_id=? ORDER BY queued_at DESC,rowid DESC LIMIT 50)',(identifier,identifier))
    return ref


def start(c,identifier,clock,queued_at):
    row=c.execute("SELECT ref FROM invoice_mail_attempts WHERE invoice_id=? AND state='pending' ORDER BY queued_at DESC,rowid DESC LIMIT 1",(identifier,)).fetchone()
    ref=row['ref'] if row else queued(c,identifier,queued_at)
    c.execute("UPDATE invoice_mail_attempts SET state='sending',provider=?,started_at=?,client_request_id=? WHERE ref=?",(provider(),clock,str(uuid.uuid4()) if provider()=='microsoft_graph' else '',ref))
    return dict(c.execute('SELECT * FROM invoice_mail_attempts WHERE ref=?',(ref,)).fetchone())


def safe_metadata(data):
    result={}
    if not isinstance(data,dict):return result
    for key in ('request_id','client_request_id'):
        value=data.get(key)
        if isinstance(value,str) and GUID.fullmatch(value):result[key]=value.lower()
    for key in ('protocol_code','retry_after'):
        value=data.get(key)
        if type(value) is int and 0<=value<=(86400 if key=='retry_after' else 999):result[key]=value
    return result


def finish(c,ref,state,category,clock,data):
    values=safe_metadata(data)
    c.execute("UPDATE invoice_mail_attempts SET state=?,category=?,finished_at=? WHERE ref=? AND state='sending'",(state,category if category in CATEGORIES else '',clock,ref))
    for key,value in values.items():c.execute('UPDATE invoice_mail_attempts SET '+key+'=? WHERE ref=?',(value,ref))


def http_category(code):
    if code==401:return 'authentication'
    if code==403:return 'permission'
    if code==429:return 'throttled'
    if 500<=code<=599:return 'provider_unavailable'
    return 'rejected'


def guidance(category):
    return {
        'configuration':'Check the email provider settings in the container.',
        'authentication':'Reconnect Microsoft in Settings, or check SMTP login details.',
        'permission':'Check that the connected Microsoft mailbox is authorised to send.',
        'recipient':'Check the saved recipient address and any delivery failure notice.',
        'sender':'Check the configured sender is authorised by the provider.',
        'rejected':'The provider rejected this request. Check the recipient and provider settings.',
        'throttled':'The provider limited requests. Wait before manually retrying.',
        'provider_unavailable':'The provider is temporarily unavailable. Wait before manually retrying.',
        'connection':'Check the server network, DNS and email provider connection.',
        'tls':'Check TLS settings, server time and certificate trust. Do not disable certificate checks.',
        'interrupted':'Check Sent Items, delivery failure notices and the recipient before retrying; it may already have sent.',
        'unknown':'Check the attempt reference in container logs and Sent Items before retrying.',
        'pdf':'Check the saved PDF is available and within the email size limit.',
    }.get(category,'')


def details(c,identifier,state):
    rows=[dict(r) for r in c.execute('SELECT * FROM invoice_mail_attempts WHERE invoice_id=? ORDER BY queued_at DESC,rowid DESC LIMIT 50',(identifier,))]
    for row in rows:row.pop('invoice_id',None)
    latest=rows[0] if rows else None
    sending_provider=latest['provider'] if latest else 'unknown'
    name={'smtp':'SMTP server','microsoft_graph':'Microsoft'}.get(sending_provider,'sending provider')
    label=('Accepted by '+name+' — delivery not confirmed') if state=='sent' else {'pending':'Queued for sending','sending':'Submitting to '+name,'failed':'Submission failed','uncertain':'Submission outcome uncertain'}.get(state,state)
    help_text=('Check Sent Items and delivery failure notices. If the recipient has not received it, ask their IT team to check junk, quarantine and phishing filters. The app cannot see recipient delivery or filtering decisions.') if state=='sent' else guidance(latest['category']) if latest else 'Detailed attempt history is unavailable for emails sent before this update.'
    return {'label':label,'provider':sending_provider,'guidance':help_text,'attempts':rows,'history_available':bool(rows)}
