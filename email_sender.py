import smtplib
from email.message import EmailMessage
import os
from dotenv import load_dotenv

load_dotenv()

GMAIL_USER        = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
CV_PATH           = os.getenv("CV_PATH")
TRANSCRIPT_PATH   = os.getenv("TRANSCRIPT_PATH")

# Attachment filenames are derived from the file paths so no personal name
# is hardcoded here. Update CV_PATH and TRANSCRIPT_PATH in your .env file.
CV_FILENAME         = os.path.basename(CV_PATH) if CV_PATH else "CV.pdf"
TRANSCRIPT_FILENAME = os.path.basename(TRANSCRIPT_PATH) if TRANSCRIPT_PATH else "Transcript.pdf"


def send_email_with_attachments(to_email: str, subject: str, body: str) -> bool:
    """
    Sends an email with CV and Transcript attached via Gmail SMTP.

    Configure GMAIL_USER, GMAIL_APP_PASSWORD, CV_PATH, and TRANSCRIPT_PATH
    in your .env file before calling this function.
    """
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From']    = GMAIL_USER
    msg['To']      = to_email
    msg.set_content(body)

    # Attach CV
    if CV_PATH and os.path.exists(CV_PATH):
        with open(CV_PATH, 'rb') as f:
            pdf_data = f.read()
        msg.add_attachment(pdf_data, maintype='application', subtype='pdf',
                           filename=CV_FILENAME)
    else:
        print(f"Warning: CV not found at {CV_PATH}")

    # Attach Transcript
    if TRANSCRIPT_PATH and os.path.exists(TRANSCRIPT_PATH):
        with open(TRANSCRIPT_PATH, 'rb') as f:
            pdf_data = f.read()
        msg.add_attachment(pdf_data, maintype='application', subtype='pdf',
                           filename=TRANSCRIPT_FILENAME)
    else:
        print(f"Warning: Transcript not found at {TRANSCRIPT_PATH}")

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False
