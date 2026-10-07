import smtplib
from email.message import EmailMessage
import mimetypes
import os

from Utils.credentials import get_credential


def send_training_email(to_address, subject, body, attachments=None):
    smtp_server = get_credential("SMTP_SERVER", "mail.smtp2go.com")
    smtp_port = int(get_credential("SMTP_PORT", "587"))
    smtp_user = get_credential("SMTP_USER")
    smtp_pass = get_credential("SMTP_PASS")
    smtp_from = get_credential("SMTP_FROM", "x-ski@parmeltec.org")

    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP_USER / SMTP_PASS fehlen (Umgebungsvariable oder .env im Projektverzeichnis).")

    attachments = attachments or []

    msg = EmailMessage()
    msg['From'] = smtp_from
    msg['To'] = to_address
    msg['Subject'] = subject
    msg.set_content(body)

    for filepath in attachments:
        filetype, _ = mimetypes.guess_type(str(filepath))
        if filetype is None:
            filetype = 'application/octet-stream'  # Standard-Binärformat

        maintype, subtype = filetype.split('/')

        with open(filepath, 'rb') as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(filepath))

    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        print(f"📧 E-Mail mit {len(attachments)} Anhang/Anhängen an {to_address} gesendet.")
