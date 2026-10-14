"""Durable, single-recipient invoice delivery. No automatic uncertain retries."""
import os
import logging
import re
import secrets
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate

LEASE = 120
MAX_PDF = 20 * 1024 * 1024
LOCK = threading.Lock()
LABELS = {'pending':'Email queued', 'sending':'Sending email', 'sent':'Accepted by mail server',
          'failed':'Email failed', 'uncertain':'Delivery uncertain'}


def address(value):
    if not isinstance(value,str):
        raise ValueError('Save a valid single email address in the contact information.')
    value=value.strip()
    if len(value)>254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}",value):
        raise ValueError('Save a valid single email address in the contact information.')
    return value


def config():
    host=os.getenv('SMTP_HOST','').strip()
    sender=os.getenv('SMTP_FROM','').strip()
    if not host or not sender:
        raise ValueError('Configure SMTP_HOST and SMTP_FROM in the container to enable invoice email.')
    if len(host)>253 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*',host):
        raise ValueError('Check SMTP_HOST in the container configuration.')
    security=os.getenv('SMTP_SECURITY','starttls').strip().lower()
    if security not in ('starttls','ssl'):
        raise ValueError('SMTP_SECURITY must be starttls or ssl. Unencrypted email is disabled.')
    try:
        port=int(os.getenv('SMTP_PORT','465' if security=='ssl' else '587'))
        if not 1<=port<=65535:raise ValueError()
    except ValueError:
        raise ValueError('Check SMTP_PORT in the container configuration.') from None
    username=os.getenv('SMTP_USERNAME','')
    password=os.getenv('SMTP_PASSWORD','')
    if bool(username)!=bool(password) or len(username)>512 or len(password)>1024 or any(ord(c)<32 or ord(c)==127 for c in username+password):
        raise ValueError('Set both SMTP_USERNAME and SMTP_PASSWORD, or leave both blank.')
    try:sender=address(sender)
    except ValueError:raise ValueError('SMTP_FROM must be one valid sender email address.') from None
    return dict(host=host,port=port,security=security,username=username,password=password,sender=sender)


def configuration_status():
    try:
        config()
        return {'configured':True,'message':'SMTP configured. Delivery is checked when sending an invoice.'}
    except ValueError as error:
        return {'configured':False,'message':str(error)}


def migrate(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS invoice_mail (
        invoice_id INTEGER PRIMARY KEY, recipient TEXT NOT NULL, status TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '',
        message_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS invoice_mail_guard (
        slot INTEGER PRIMARY KEY CHECK(slot=1), owner TEXT NOT NULL, expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS invoice_mail_requests (recorded_at REAL NOT NULL);''')


def request_limit(c,clock):
    c.execute('DELETE FROM invoice_mail_requests WHERE recorded_at<=?',(clock-3600,))
    if c.execute('SELECT COUNT(*) FROM invoice_mail_requests').fetchone()[0]>=20:
        raise ValueError('Invoice email limit reached. Wait before sending more invoices (20 per hour).')
    c.execute('INSERT INTO invoice_mail_requests VALUES(?)',(clock,))


def requested_contact(c,raw,data):
    enabled=raw.get('email_invoice',False)
    if type(enabled) is not bool:raise ValueError('Email invoice must be true or false.')
    if not enabled:return None
    config()
    identifier=raw.get('email_contact_id')
    if type(identifier) is not int:raise ValueError('Choose a saved contact to email this invoice.')
    contact=c.execute("SELECT * FROM contacts WHERE kind='customer' AND id=? AND name=?",(identifier,data['customer'])).fetchone()
    if not contact:raise ValueError('The selected contact changed. Refresh and select the recipient again.')
    recipient=address(contact['email'])
    if raw.get('email_recipient')!=recipient:
        raise ValueError('The contact email changed. Refresh and review the recipient before saving.')
    # Keep the PDF recipient aligned with the saved contact used for delivery.
    data['customer_email']=recipient
    data['customer_contact_name']=contact['contact_name']
    data['customer_address']=contact['address']
    return recipient


def queue(c,identifier,recipient,pdf,clock):
    if len(pdf)>MAX_PDF:raise ValueError('This PDF exceeds the 20 MB invoice email limit. Save without emailing.')
    request_limit(c,clock)
    c.execute("INSERT INTO invoice_mail VALUES(?,?,'pending',?,?,'',?)",
              (identifier,recipient,clock,clock,'<'+secrets.token_hex(24)+'@no-alias-invoices.local>'))


def status(c,identifier):
    row=c.execute('SELECT recipient,status,last_error FROM invoice_mail WHERE invoice_id=?',(identifier,)).fetchone()
    return dict(row) if row else None


def retry(c,identifier,recipient,confirmed,clock):
    config()
    row=c.execute('SELECT * FROM invoice_mail WHERE invoice_id=?',(identifier,)).fetchone()
    if not row or row['status'] not in ('failed','uncertain'):
        raise ValueError('Only failed or uncertain invoice emails can be retried.')
    if confirmed is not True or recipient!=row['recipient']:
        raise ValueError('Confirm the saved recipient and check for an earlier delivery before retrying.')
    request_limit(c,clock)
    c.execute("UPDATE invoice_mail SET status='pending',updated_at=?,last_error='' WHERE invoice_id=?",(clock,identifier))


class DeliveryError(Exception):
    def __init__(self,message,uncertain=False):
        super().__init__(message)
        self.uncertain=uncertain


def deliver(job,pdf,number,settings):
    try:options=config()
    except ValueError as error:raise DeliveryError(str(error)) from None
    if not isinstance(pdf,bytes) or not pdf.startswith(b'%PDF') or len(pdf)>MAX_PDF:
        raise DeliveryError('Saved invoice PDF is unavailable or too large to email.')
    message=EmailMessage()
    message['From']=options['sender'];message['To']=address(job['recipient'])
    message['Subject']='Invoice '+number
    message['Message-ID']=job['message_id']
    message['Date']=formatdate(usegmt=True)
    business=os.getenv('BUSINESS_NAME','').strip() or settings.get('business','') or 'No Alias Entertainment'
    message.set_content('Hello,\n\nPlease find invoice '+number+' attached as a PDF.\n'
                        'The invoice contains the payment details and terms.\n\nKind regards,\n'+business+'\n')
    message.add_attachment(pdf,maintype='application',subtype='pdf',filename=number+' Invoice.pdf')
    context=ssl.create_default_context();transmitting=False;server=None
    try:
        if options['security']=='ssl':
            server=smtplib.SMTP_SSL(options['host'],options['port'],timeout=10,context=context)
        else:
            server=smtplib.SMTP(options['host'],options['port'],timeout=10)
            server.ehlo();server.starttls(context=context);server.ehlo()
        if options['username']:server.login(options['username'],options['password'])
        transmitting=True
        refused=server.send_message(message,from_addr=options['sender'],to_addrs=[job['recipient']])
        if refused:raise DeliveryError('The mail server rejected the recipient. Check the saved address.')
    except DeliveryError:raise
    except (smtplib.SMTPRecipientsRefused,smtplib.SMTPDataError,smtplib.SMTPSenderRefused):
        raise DeliveryError('The mail server rejected the message. Check the recipient and SMTP configuration.') from None
    except Exception:
        if transmitting:
            raise DeliveryError('Delivery is uncertain. Check the recipient inbox or provider logs before retrying.',True) from None
        raise DeliveryError('Email could not be sent. Check SMTP configuration and connectivity, then retry from History.') from None
    finally:
        if server is not None:
            # QUIT failure after acceptance must not turn a successful send into a retry.
            try:server.quit()
            except Exception:
                try:server.close()
                except Exception:pass


def claim(connection,clock):
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        guard=c.execute('SELECT * FROM invoice_mail_guard WHERE slot=1').fetchone()
        if guard and guard['expires_at']>clock:return None
        c.execute("UPDATE invoice_mail SET status='uncertain',updated_at=?,last_error=? WHERE status='sending'",
                  (clock,'Delivery was interrupted. Check for an earlier delivery before retrying.'))
        row=c.execute("SELECT m.*,i.pdf,i.display_number,i.settings FROM invoice_mail m JOIN invoices i ON i.number=m.invoice_id WHERE m.status='pending' ORDER BY m.created_at,m.invoice_id LIMIT 1").fetchone()
        if not row:
            c.execute('DELETE FROM invoice_mail_guard');return None
        owner=secrets.token_hex(24)
        c.execute('INSERT OR REPLACE INTO invoice_mail_guard VALUES(1,?,?)',(owner,clock+LEASE))
        c.execute("UPDATE invoice_mail SET status='sending',updated_at=? WHERE invoice_id=?",(clock,row['invoice_id']))
        return dict(row,owner=owner)


def finish(connection,job,error=None):
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        guard=c.execute('SELECT owner FROM invoice_mail_guard WHERE slot=1').fetchone()
        if not guard or guard['owner']!=job['owner']:return
        outcome='sent' if error is None else ('uncertain' if error.uncertain else 'failed')
        c.execute("UPDATE invoice_mail SET status=?,last_error=?,updated_at=? WHERE invoice_id=? AND status='sending'",
                  (outcome,str(error) if error else '',time.time(),job['invoice_id']))
        c.execute('DELETE FROM invoice_mail_guard WHERE owner=?',(job['owner'],))


def run(connection):
    import json
    try:
        for _ in range(20):
            job=claim(connection,time.time())
            if job is None:break
            error=None
            try:deliver(job,job['pdf'],job['display_number'],json.loads(job['settings']))
            except DeliveryError as issue:error=issue
            except Exception:error=DeliveryError('Delivery is uncertain. Check provider logs before retrying.',True)
            finish(connection,job,error)
    except Exception:
        logging.error('Invoice email worker interrupted; review History for delivery status.')
    finally:LOCK.release()


def kick(connection):
    if not LOCK.acquire(blocking=False):return
    try:threading.Thread(target=run,args=(connection,),daemon=True).start()
    except Exception:
        LOCK.release()
        logging.error('Invoice email worker could not start; queued mail will resume on the next health check.')
