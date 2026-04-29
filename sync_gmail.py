import imaplib
import email
from email.header import decode_header
import csv
import os
import sys

# Fix Windows terminal encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

# --- CONFIGURATION ---
GMAIL_USER = os.getenv('GMAIL_USER', 'your-email@gmail.com')
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD', 'your-app-password')
CSV_PATH = 'Professor_Outreach_Tracker.csv'

# --- NON-PROFESSOR EMAIL FILTERS ---
EXCLUDE_SENDERS = [
    'no-reply', 'noreply', 'donotreply', 'do-not-reply',
    'mailer-daemon', 'postmaster', 'notifications',
    'admissions', 'recruiting', 'forms-receipts',
    'billing', 'support', 'help@', 'automated',
    'system@', 'alerts@', 'interntl@', 'computingphd',
    'international@',
    GMAIL_USER,  # exclude own sent emails
]

# --- SENTIMENT KEYWORDS (Thread-aware, Academic-grade) ---
POSITIVE_KEYWORDS = [
    'interview', 'zoom', 'google meet', 'teams meeting',
    'schedule a call', 'schedule a meeting', 'set up a meeting',
    'would like to meet', 'let us meet', 'like to discuss',
    'discuss your', 'discuss further', 'i am interested',
    'we are interested', 'please apply', 'encourage you to apply',
    'strong background', 'impressive', 'good fit', 'great fit', 'right fit',
    'we have funding', 'funded position', 'opening in my lab',
    'position available', 'vacancy', 'send your cv', 'share your cv',
    'send me your cv', 'tell me more', 'application portal',
    'skype', 'video call', 'welcome to apply',
    'look forward to speaking', 'reach out to discuss',
    'happy to chat', 'happy to talk', 'available to meet',
]

NEGATIVE_KEYWORDS = [
    'no opening', 'no openings', 'no position', 'no vacancy',
    'not accepting', 'not taking', 'not recruiting',
    'no funding', 'not funded', 'no fellowship',
    'fully funded already', 'already have students',
    'not a good match', 'not a fit', 'not aligned',
    'best of luck', 'best luck elsewhere', 'cannot support',
    'cannot accept', 'not in a position to',
    'regret to inform', 'regret that', 'unfortunately',
    'i am retiring', 'taking a sabbatical',
    'position has been filled', 'already hired',
    'canceled event', 'event canceled', 'meeting cancelled',
    'meeting canceled',
    # Negation patterns
    'skip an interview', 'skip interview', 'will skip',
    'will not interview', 'not interview', 'no interview',
    'gpa is too low', 'gpa too low', 'low gpa',
    'low-tier', 'low tier venue', 'good luck with your',
    'good luck elsewhere', 'will pass', 'pass on this',
    'not moving forward', 'not proceed', 'cannot proceed',
    # Polite academic rejections (very common)
    'not currently looking for new students',
    'not looking for new students',
    'not looking for students',
    'not taking new students',
    'not accepting new students',
    'do not have any openings',
    'don\'t have any openings',
    'at full capacity',
    'lab is full',
    'group is full',
    'wish you the best',
    'wish you all the best',
    'best wishes with your',
    'good luck in your search',
    'i will skip',
    'i am going to pass',
]

# Keywords that indicate an actual interview was scheduled
INTERVIEW_SCHEDULED_KEYWORDS = [
    'zoom link', 'meeting link', 'google meet',
    'schedule a zoom', 'scheduled a meeting', 'schedule a call',
    'set up a meeting', 'set up a call', 'book a time',
    'calendly', 'when2meet', 'doodle',
    'please find the meeting', 'meeting invitation',
    'i\'d like to invite you', 'let us schedule',
    'let\'s schedule', "let's meet", 'let us meet',
]

# Negated positive patterns — "zoom" in "won't zoom", "interview" in "skip interview"
NEGATED_POSITIVE_PATTERNS = [
    'skip an interview', 'skip interview',
    'will not zoom', 'cannot meet', 'unable to meet',
    'not interested in meeting', 'will not be able to discuss',
]


def decode_str(s):
    if s is None:
        return ""
    result = ""
    for part, charset in decode_header(s):
        if isinstance(part, bytes):
            result += part.decode(charset or 'utf-8', errors='replace')
        else:
            result += str(part)
    return result


def get_email_body(msg):
    """Extract full plain text body from a single email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disposition:
                charset = part.get_content_charset() or 'utf-8'
                try:
                    body += part.get_payload(decode=True).decode(charset, errors='replace')
                except Exception:
                    body += part.get_payload(decode=True).decode('latin-1', errors='replace')
    else:
        charset = msg.get_content_charset() or 'utf-8'
        try:
            body = msg.get_payload(decode=True).decode(charset, errors='replace')
        except Exception:
            body = msg.get_payload(decode=True).decode('latin-1', errors='replace')
    return body.strip()


def is_excluded_sender(email_addr):
    """Returns True if this is a system/non-professor email."""
    addr = email_addr.lower()
    return any(excl in addr for excl in EXCLUDE_SENDERS)


def analyze_sentiment_from_thread(full_thread_text):
    """Analyze sentiment from the FULL combined thread text with negation awareness."""
    text = full_thread_text.lower()

    # Step 1: Check for negated positive patterns FIRST
    # e.g. "skip an interview" should NOT count as positive even though "interview" is there
    has_negated_positive = any(pat in text for pat in NEGATED_POSITIVE_PATTERNS)

    pos_hits = [kw for kw in POSITIVE_KEYWORDS if kw in text]
    neg_hits = [kw for kw in NEGATIVE_KEYWORDS if kw in text]

    # Step 2: Remove false positive hits caused by negation
    if has_negated_positive:
        # Remove keywords that appear in negating context
        pos_hits = [kw for kw in pos_hits if kw not in ['interview', 'zoom', 'meet', 'discuss']]

    if pos_hits and not neg_hits:
        return 'Positive', pos_hits[:3]
    elif neg_hits and not pos_hits:
        return 'Negative', neg_hits[:3]
    elif neg_hits and pos_hits:
        first_pos = min(text.find(kw) for kw in pos_hits)
        first_neg = min(text.find(kw) for kw in neg_hits)
        if first_pos < first_neg:
            return 'Positive', pos_hits[:3]
        else:
            return 'Negative', neg_hits[:3]
    elif has_negated_positive:
        # Negated patterns found but no other negative keyword — still Negative
        return 'Negative', ['negated positive pattern']
    else:
        return 'Neutral', []


def sync_gmail():
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found.")
        return

    headers = []
    professors = []
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames)
        professors = list(reader)

    if 'Sentiment' not in headers:
        headers.append('Sentiment')

    # Build professor email -> row index map (excluding system emails)
    prof_email_map = {}
    for i, p in enumerate(professors):
        e = p.get('Email', '').strip().lower()
        if e and not is_excluded_sender(e):
            prof_email_map[e] = i

    print(f"Loaded {len(professors)} professors, {len(prof_email_map)} valid professor emails.")

    try:
        print(f"\nConnecting to Gmail ({GMAIL_USER})...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)

        # Scan these folders in order
        target_folders = [
            '"[Gmail]/All Mail"',
            '"[Gmail]/Important"',
            '"[Gmail]/Starred"',
            'INBOX',
        ]

        # thread_data accumulates ALL messages per professor across all folders
        thread_data = {}

        for folder in target_folders:
            print(f"\n--- Scanning: {folder} ---")
            try:
                rv, _ = mail.select(folder, readonly=True)
                if rv != 'OK':
                    print(f"    Skipping (could not open).")
                    continue
            except Exception as ex:
                print(f"    Error: {ex}")
                continue

            for prof_email, idx in prof_email_map.items():
                status, messages = mail.search(None, f'FROM "{prof_email}"')
                if status != "OK" or not messages[0]:
                    continue

                msg_ids = messages[0].split()

                if prof_email not in thread_data:
                    thread_data[prof_email] = {
                        'idx': idx,
                        'bodies': [],
                        'subjects': [],
                    }

                print(f"    {prof_email}: {len(msg_ids)} msg(s)")

                # Fetch ALL messages in the thread
                for msg_id in msg_ids:
                    res, msg_data = mail.fetch(msg_id, "(RFC822)")
                    for part in msg_data:
                        if isinstance(part, tuple):
                            msg = email.message_from_bytes(part[1])
                            subject = decode_str(msg.get("Subject", ""))
                            body = get_email_body(msg)
                            if body:
                                thread_data[prof_email]['bodies'].append(body)
                                if subject not in thread_data[prof_email]['subjects']:
                                    thread_data[prof_email]['subjects'].append(subject)

        # Analyze full threads and update CSV
        print("\n=== FULL THREAD SENTIMENT RESULTS ===")
        updated_count = 0

        for prof_email, data in thread_data.items():
            if not data['bodies']:
                continue

            # Combine ALL message bodies as the full thread
            full_thread = "\n\n--- NEXT MESSAGE ---\n\n".join(data['bodies'])
            sentiment, keywords = analyze_sentiment_from_thread(full_thread)

            latest_subject = data['subjects'][-1] if data['subjects'] else "(No Subject)"
            snippet = data['bodies'][-1][:300].replace('\n', ' ').replace('\r', '').strip()

            safe_subj = latest_subject[:60].encode('ascii', errors='replace').decode('ascii')
            kw_str = str(keywords) if keywords else "no strong keywords"
            print(f"  [{sentiment:8}] {prof_email}")
            print(f"             {len(data['bodies'])} msgs in thread")
            print(f"             Keywords matched: {kw_str}")

            idx = data['idx']
            professors[idx]['Response'] = f"[{latest_subject}] {snippet}..."
            professors[idx]['Sentiment'] = sentiment

            # Determine Status based on full thread content
            thread_lower = full_thread.lower()
            if sentiment == 'Positive' and any(kw in thread_lower for kw in INTERVIEW_SCHEDULED_KEYWORDS):
                professors[idx]['Status'] = 'Interview Scheduled'
            elif sentiment == 'Positive':
                professors[idx]['Status'] = 'Response Received'
            elif sentiment == 'Negative':
                professors[idx]['Status'] = 'Rejected'
            else:
                professors[idx]['Status'] = 'Response Received'

            updated_count += 1

        mail.logout()

        if updated_count > 0:
            with open(CSV_PATH, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(professors)
            print(f"\nUpdated {updated_count} professor records with full-thread sentiment.")

            import subprocess
            subprocess.run(["python", "sync_dashboard.py"])
        else:
            print("\nNo professor replies found.")

    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    sync_gmail()
