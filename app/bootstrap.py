"""Start the invoice app with SMTP or Microsoft Graph invoice delivery."""
import logging
import os
import re
import runpy
from email.message import EmailMessage
from email.utils import formatdate

import invoice_mail
import microsoft_graph

_original_config = invoice_mail.config
_original_status = invoice_mail.configuration_status
_original_deliver = invoice_mail.deliver


def _provider():
    return os.getenv("EMAIL_PROVIDER", "smtp").strip().lower()


def config():
    provider = _provider()
    if provider == "smtp":
        return _original_config()
    if provider != "microsoft_graph":
        raise ValueError("EMAIL_PROVIDER must be smtp or microsoft_graph.")

    client_id = os.getenv("MICROSOFT_CLIENT_ID", "").strip()
    sender = os.getenv("MICROSOFT_SENDER", "").strip()
    if not re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        client_id,
    ):
        raise ValueError("Set a valid MICROSOFT_CLIENT_ID in the container.")
    try:
        sender = invoice_mail.address(sender)
    except ValueError:
        raise ValueError(
            "Set MICROSOFT_SENDER to the Microsoft email address used for invoice mail."
        ) from None
    return {
        "provider": "microsoft_graph",
        "client_id": client_id,
        "sender": sender,
    }


def configuration_status():
    if _provider() == "smtp":
        return _original_status()
    try:
        options = config()
        connected = microsoft_graph.access_token(options["client_id"]) is not None
        return {
            "configured": connected,
            "message": (
                "Microsoft Graph connected. Invoice email is ready."
                if connected
                else "Microsoft Graph configured but not connected. "
                     "Open the container console and run: python /app/connect_microsoft.py"
            ),
        }
    except (ValueError, RuntimeError) as error:
        return {"configured": False, "message": str(error)}


def deliver(job, pdf, number, settings):
    if _provider() == "smtp":
        return _original_deliver(job, pdf, number, settings)

    try:
        options = config()
    except ValueError as error:
        raise invoice_mail.DeliveryError(str(error)) from None

    if (
        not isinstance(pdf, bytes)
        or not pdf.startswith(b"%PDF")
        or len(pdf) > invoice_mail.MAX_PDF
    ):
        raise invoice_mail.DeliveryError(
            "Saved invoice PDF is unavailable or too large to email."
        )

    recipient = invoice_mail.address(job["recipient"])
    message = EmailMessage()
    message["From"] = options["sender"]
    message["To"] = recipient
    message["Subject"] = "Invoice " + number
    message["Message-ID"] = job["message_id"]
    message["Date"] = formatdate(usegmt=True)

    business = (
        os.getenv("BUSINESS_NAME", "").strip()
        or settings.get("business", "")
        or "No Alias Entertainment"
    )
    message.set_content(
        "Hello,\n\n"
        "Please find invoice " + number + " attached as a PDF.\n"
        "The invoice contains the payment details and terms.\n\n"
        "Kind regards,\n" + business + "\n"
    )
    message.add_attachment(
        pdf,
        maintype="application",
        subtype="pdf",
        filename=number + " Invoice.pdf",
    )

    if microsoft_graph.access_token(options["client_id"]) is None:
        raise invoice_mail.DeliveryError(
            "Microsoft account is not connected. Open the container console and run: "
            "python /app/connect_microsoft.py"
        )

    logging.info(
        "Invoice Microsoft Graph: submitting invoice %s to %s",
        number,
        recipient,
    )
    try:
        status = microsoft_graph.send_mime(
            options["client_id"],
            message.as_bytes(),
        )
    except microsoft_graph.GraphRejected as error:
        logging.error(
            "Invoice Microsoft Graph rejected invoice %s: %s",
            number,
            str(error)[:1200],
        )
        raise invoice_mail.DeliveryError(
            "Microsoft rejected the email request. Check the Microsoft connection "
            "and retry from History."
        ) from None
    except Exception as error:
        logging.error(
            "Invoice Microsoft Graph submission became uncertain for invoice %s: %s",
            number,
            str(error)[:1200],
        )
        raise invoice_mail.DeliveryError(
            "Delivery is uncertain. Check Sent Items or the recipient inbox before retrying.",
            True,
        ) from None

    if status != 202:
        raise invoice_mail.DeliveryError(
            "Microsoft Graph did not accept the message (HTTP %s)." % status
        )

    logging.info(
        "Invoice Microsoft Graph: accepted invoice %s for delivery",
        number,
    )


invoice_mail.config = config
invoice_mail.configuration_status = configuration_status
invoice_mail.deliver = deliver

runpy.run_module("app", run_name="__main__")
