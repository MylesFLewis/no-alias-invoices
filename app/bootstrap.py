"""Start the invoice app with optional Microsoft Graph mail delivery."""
import logging
import os
import runpy
from email.message import EmailMessage
from email.utils import formatdate

import invoice_mail
import microsoft_graph

_original_config = invoice_mail.config
_original_status = invoice_mail.configuration_status
_original_deliver = invoice_mail.deliver


def _provider():
    return os.getenv('EMAIL_PROVIDER', 'smtp').strip().lower()


def config():
    provider = _provider()
    if provider == 'smtp':
        return _original_config()
    if provider != 'microsoft_graph':
        raise ValueError('EMAIL_PROVIDER must be smtp or microsoft_graph.')
    client_id = os.getenv('MICROSOFT_CLIENT_ID', '').strip()
    if not client_id:
        raise ValueError('Set MICROSOFT_CLIENT_ID in the container to enable Microsoft invoice email.')
    if len(client_id) != 36:
        raise ValueError('Check MICROSOFT_CLIENT_ID in the container configuration.')
    return {'provider': 'microsoft_graph', 'client_id': client_id}


def configuration_status():
    if _provider() == 'smtp':
        return _original_status()
    try:
        options = config()
        connected = microsoft_graph.access_token(options['client_id']) is not None
        return {
            'configured': connected,
            'message': ('Microsoft Graph connected. Invoice email is ready.' if connected else
                        'Microsoft Graph configured but not connected. Run python /app/connect_microsoft.py in the container console once.'),
        }
    except (ValueError, RuntimeError) as error:
        return {'configured': False, 'message': str(error)}


def deliver(job, pdf, number, settings):
    if _provider() == 'smtp':
        return _original_deliver(job, pdf, number, settings)
    try:
        options = config()
    except ValueError as error:
        raise invoice_mail.DeliveryError(str(error)) from None
    if not isinstance(pdf, bytes) or not pdf.startswith(b'%PDF') or len(pdf) > invoice_mail.MAX_PDF:
        raise invoice_mail.DeliveryError('Saved invoice PDF is unavailable or too large to email.')
    recipient = invoice_mail.address(job['recipient'])
    message = EmailMessage()
    message['To'] = recipient
    message['Subject'] = 'Invoice ' + number
    message['Message-ID'] = job['message_id']
    message['Date'] = formatdate(usegmt=True)
    business = os.getenv('BUSINESS_NAME', '').strip() or settings.get('business', '') or 'No Alias Entertainment'
    message.set_content('Hello,\n\nPlease find invoice ' + number + ' attached as a PDF.\n'
                        'The invoice contains the payment details and terms.\n\nKind regards,\n' + business + '\n')
    message.add_attachment(pdf, maintype='application', subtype='pdf', filename=number + ' Invoice.pdf')
    transmitting = False
    try:
        if microsoft_graph.access_token(options['client_id']) is None:
            raise invoice_mail.DeliveryError('Microsoft account is not connected. Open the container console and run: python /app/connect_microsoft.py')
        logging.info('Invoice Microsoft Graph: submitting invoice %s to %s', number, recipient)
        transmitting = True
        status = microsoft_graph.send_mime(options['client_id'], message.as_bytes())
        if status != 202:
            raise invoice_mail.DeliveryError('Microsoft Graph did not accept the message (HTTP %s).' % status)
        logging.info('Invoice Microsoft Graph: accepted invoice %s for delivery', number)
    except invoice_mail.DeliveryError:
        raise
    except RuntimeError as error:
        logging.error('Invoice Microsoft Graph rejected invoice %s: %s', number, str(error)[:1200])
        raise invoice_mail.DeliveryError('Microsoft rejected the email request. Check the Microsoft connection and retry from History.') from None
    except Exception as error:
        logging.error('Invoice Microsoft Graph failure for invoice %s after_submission_started=%s: %s', number, transmitting, str(error)[:1200])
        if transmitting:
            raise invoice_mail.DeliveryError('Delivery is uncertain. Check Sent Items or the recipient inbox before retrying.', True) from None
        raise invoice_mail.DeliveryError('Email could not be sent. Check Microsoft connectivity and retry from History.') from None


invoice_mail.config = config
invoice_mail.configuration_status = configuration_status
invoice_mail.deliver = deliver

runpy.run_module('app', run_name='__main__')
