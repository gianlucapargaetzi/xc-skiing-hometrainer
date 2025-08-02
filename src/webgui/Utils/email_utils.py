import smtplib
from email.message import EmailMessage
import mimetypes
import os

SMTP_SERVER = "mail.smtp2go.com"
SMTP_PORT = 587
SMTP_USER = "parmeltec"
SMTP_PASS = "f4cHOmBVVG92cuxD"
SMTP_FROM = "x-ski@parmeltec.org"


def send_training_email(to_address, subject, body, attachments=[]):
    msg = EmailMessage()
    msg['From'] = SMTP_FROM
    msg['To'] = to_address
    msg['Subject'] = subject
    msg.set_content(body)

    for filepath in attachments:
        filetype, _ = mimetypes.guess_type(filepath)
        if filetype is None:
            filetype = 'application/octet-stream'  # Standard-Binärformat

        maintype, subtype = filetype.split('/')

        with open(filepath, 'rb') as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(filepath))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        print(f"📧 E-Mail mit {len(attachments)} Anhang/Anhängen an {to_address} gesendet.")
