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

    identifier = microsoft_graph.client_id()
    identity = microsoft_graph.connection_info(identifier)
    sender = os.getenv("MICROSOFT_SENDER", "").strip() or (identity["username"] if identity else "")
    try:
        sender = invoice_mail.address(sender)
    except ValueError:
        raise ValueError("Connect a Microsoft account in Settings to enable invoice email.") from None
    if identity and sender.casefold()!=identity["username"].casefold():
        raise ValueError("The connected mailbox differs from MICROSOFT_SENDER. Reconnect the intended mailbox in Settings.")
    return {"provider":"microsoft_graph","client_id":identifier,"sender":sender}


def configuration_status():
    if _provider() == "smtp":
        return _original_status()
    try:
        options = config()
        identity = microsoft_graph.connection_info(options["client_id"])
        connected = identity is not None
        return {
            "configured": connected,
            "message": (
                "Microsoft Graph connected as " + identity["username"] + ". Invoice email is ready."
                if connected
                else "Microsoft Graph configured but not connected. "
                     "Connect Microsoft account in Settings."
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

    recipient = invoice_mail.address(job["recipient"])
    message = invoice_mail.message_for(job,pdf,number,settings,options["sender"])

    try:
        connected = microsoft_graph.access_token(options["client_id"]) is not None
    except Exception:
        raise invoice_mail.DeliveryError("Microsoft authorisation could not be refreshed. Reconnect in Settings; no email was submitted.") from None
    if not connected:
        raise invoice_mail.DeliveryError("Microsoft account needs reconnecting in Settings; no email was submitted.")

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
    except microsoft_graph.GraphNotConnected:
        raise invoice_mail.DeliveryError("Microsoft account needs reconnecting in Settings; no email was submitted.") from None
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
    except Exception:
        logging.error("Invoice Microsoft Graph submission became uncertain for invoice %s", number)
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


def install():
    invoice_mail.config = config
    invoice_mail.configuration_status = configuration_status
    invoice_mail.deliver = deliver


if __name__ == "__main__":
    install()
    runpy.run_module("app", run_name="__main__")
