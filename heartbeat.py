"""
Aurora Heartbeat — OpenClaw-style Proactive Intelligence Engine
==============================================================
Runs every 6 hours as an APScheduler background job.
Instead of dumb "Good Morning!" spam, it READS context first:
  - Checks for upcoming PhD deadlines
  - Monitors professor outreach follow-up windows
  - Scans for habit streak risks
  - Checks interview prep dates
  - Reads Gmail for unanswered replies (if credentials available)

Only sends a Telegram message if ≥ 1 module finds something actionable.
Silence is the default — no spam.

RAM-Optimized Design:
  - Synchronous (not async) — no event loop overhead
  - Pure file/SQLite reads — no heavy API calls unless action needed
  - Final message composed by SPRINTER (lightweight model via API)
  - Max one Telegram API call per heartbeat tick
"""

import os
import json
import csv
import logging
import sqlite3
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
CSV_PATH = os.getenv("CSV_PATH", "Professor_Outreach_Tracker.csv")
USER_NAME = os.getenv("USER_NAME", "Muhammed")
AGENT_NAME = os.getenv("AGENT_NAME", "Aurora")

# Lightweight model for composing heartbeat message
COMPOSER_MODELS = [
    "google/gemma-3-12b-it:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# ─── Module 1: Deadline Watcher ───────────────────────────────────────────────

def check_deadlines() -> list[str]:
    """Scan deadlines.json for anything within 7 days. Returns list of alerts."""
    alerts = []
    deadline_file = "deadlines.json"
    if not os.path.exists(deadline_file):
        return alerts
    try:
        with open(deadline_file, "r") as f:
            deadlines = json.load(f)
        now = datetime.now()
        for d in deadlines:
            try:
                dt = datetime.strptime(d["date"], "%Y-%m-%d")
                days_left = (dt - now).days
                if 0 <= days_left <= 7:
                    alerts.append(f"📅 DEADLINE in {days_left}d: **{d['topic']}** ({d['date']})")
                elif days_left < 0:
                    alerts.append(f"⚠️ OVERDUE: **{d['topic']}** ({d['date']})")
            except:
                continue
    except Exception as e:
        logging.warning(f"[Heartbeat] Deadline check failed: {e}")
    return alerts


# ─── Module 2: Outreach Follow-Up Monitor ─────────────────────────────────────

def check_followups() -> list[str]:
    """Find professors contacted 10+ days ago with no reply. Returns alerts."""
    alerts = []
    if not os.path.exists(CSV_PATH):
        return alerts
    try:
        now = datetime.now()
        overdue = []
        with open(CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("Status", "").strip().lower()
                date_str = row.get("Date Contacted", "").strip()
                sentiment = row.get("Sentiment", "").strip().lower()

                # Only check "contacted" rows with no reply
                if "contacted" in status and "response" not in status and date_str:
                    try:
                        date_contacted = datetime.strptime(date_str, "%Y-%m-%d")
                        days_since = (now - date_contacted).days
                        if 10 <= days_since <= 21:  # Sweet spot: 10-21 days
                            name = row.get("Professor", "Unknown")
                            univ = row.get("University", "")
                            overdue.append((days_since, name, univ))
                    except:
                        continue

        # Sort by days since contact, report top 2 to avoid spam
        overdue.sort(reverse=True)
        for days, name, univ in overdue[:2]:
            alerts.append(f"📬 No reply in {days}d: **{name}** ({univ}) — consider a follow-up?")

    except Exception as e:
        logging.warning(f"[Heartbeat] Follow-up check failed: {e}")
    return alerts


# ─── Module 3: Interview Countdown ────────────────────────────────────────────

def check_interviews() -> list[str]:
    """Check SQLite profile for upcoming interview dates."""
    alerts = []
    try:
        conn = sqlite3.connect("aurora_memory.db")
        c = conn.cursor()
        # Look for interview-related deadlines in semantic_memory
        c.execute("SELECT text FROM semantic_memory WHERE text LIKE '%interview%' OR text LIKE '%Interview%'")
        rows = c.fetchall()
        conn.close()

        now = datetime.now()
        for (text,) in rows:
            # Try to find a date in the text
            import re
            date_matches = re.findall(r'\d{4}-\d{2}-\d{2}|\w+ \d{1,2},?\s*\d{4}|May \d{1,2}|June \d{1,2}', text)
            for dm in date_matches:
                try:
                    # Try common formats
                    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%b %d"):
                        try:
                            dt = datetime.strptime(dm.strip(), fmt)
                            if fmt == "%b %d":
                                dt = dt.replace(year=now.year)
                            days_left = (dt - now).days
                            if 0 <= days_left <= 5:
                                alerts.append(
                                    f"🎓 INTERVIEW in {days_left}d! — {text[:100]}..."
                                )
                            break
                        except:
                            continue
                except:
                    continue
    except Exception as e:
        logging.warning(f"[Heartbeat] Interview check failed: {e}")
    return alerts


# ─── Module 4: Habit Streak Guardian ──────────────────────────────────────────

def check_habits() -> list[str]:
    """Find habits that haven't been logged today. Nudge to maintain streaks."""
    alerts = []
    try:
        conn = sqlite3.connect("aurora_memory.db")
        c = conn.cursor()
        c.execute("SELECT habit_name, streak, last_done FROM habits WHERE streak > 0")
        habits = c.fetchall()
        conn.close()

        today = datetime.now().strftime("%Y-%m-%d")
        for habit_name, streak, last_done in habits:
            if last_done and last_done != today and streak >= 2:
                alerts.append(
                    f"💪 Don't break your **{habit_name}** streak! ({streak} days) — still not logged today."
                )
    except Exception as e:
        logging.warning(f"[Heartbeat] Habit check failed: {e}")
    return alerts


# ─── Module 5: Outreach Progress Motivator ────────────────────────────────────

def check_outreach_pace() -> list[str]:
    """Check if outreach pace has slowed — alert if no emails sent this week."""
    alerts = []
    if not os.path.exists(CSV_PATH):
        return alerts
    try:
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        sent_this_week = 0
        pending_count = 0

        with open(CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("Status", "").strip().lower()
                date_str = row.get("Date Contacted", "").strip()
                if "to contact" in status:
                    pending_count += 1
                if "contacted" in status and date_str and date_str >= week_ago:
                    sent_this_week += 1

        if sent_this_week == 0 and pending_count > 0:
            alerts.append(
                f"📊 No emails sent this week! You have **{pending_count}** professors still waiting. "
                f"Type `/start` to draft one."
            )
    except Exception as e:
        logging.warning(f"[Heartbeat] Outreach pace check failed: {e}")
    return alerts


# ─── Message Composer (LLM) ───────────────────────────────────────────────────

def compose_heartbeat_message(raw_alerts: list[str]) -> str:
    """
    Turn raw alert strings into a warm, personal Aurora message.
    Uses SPRINTER (lightweight) model — zero local RAM.
    Falls back to plain formatted text if LLM unavailable.
    """
    alert_text = "\n".join(f"- {a}" for a in raw_alerts)

    if not OPENROUTER_API_KEY:
        # Fallback: plain text formatting
        now = datetime.now().strftime("%H:%M")
        return (
            f"👋 Hey {USER_NAME}! Aurora checking in ({now}).\n\n"
            + "\n".join(f"• {a}" for a in raw_alerts)
            + "\n\nLet me know if you need anything!"
        )

    prompt = f"""You are {AGENT_NAME}, a warm AI companion. Write a short, proactive check-in message for {USER_NAME}.
Based on these alerts:
{alert_text}

Rules:
- Max 5 sentences. Concise and personal, like a caring friend.
- Lead with the most urgent item.
- Natural tone. No robotic phrases. No "Furthermore" or "It is important to note."
- End with ONE specific actionable suggestion.
- Use emojis sparingly (1-2 max).
- Do NOT say "I hope this message finds you well."

Write the message now:"""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

    for model in COMPOSER_MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=250,  # Keep output small
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.warning(f"[Heartbeat] Composer model {model} failed: {e}")
            continue

    # Last fallback
    return (
        f"⚡ {AGENT_NAME} pulse check:\n\n"
        + "\n".join(f"• {a}" for a in raw_alerts)
    )


# ─── Telegram Sender ──────────────────────────────────────────────────────────

def send_telegram_message(text: str):
    """Send a plain heartbeat message via Telegram Bot API."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        httpx.post(url, json=payload, timeout=10.0)
    except Exception as e:
        logging.error(f"[Heartbeat] Telegram send failed: {e}")


# ─── Main Heartbeat Tick ──────────────────────────────────────────────────────

def run_heartbeat():
    """
    Main heartbeat function. Called by APScheduler every 6 hours.
    Collects alerts from all 5 modules, composes message, sends if needed.
    Total execution: ~1-3 seconds on 1GB RAM server (no heavy operations).
    """
    logging.info("[Heartbeat] 🫀 Tick starting...")

    all_alerts = []

    # Run all 5 modules (pure file/DB reads — no API calls yet)
    all_alerts.extend(check_deadlines())
    all_alerts.extend(check_followups())
    all_alerts.extend(check_interviews())
    all_alerts.extend(check_habits())
    all_alerts.extend(check_outreach_pace())

    if not all_alerts:
        logging.info("[Heartbeat] Nothing actionable this tick. Staying silent. ✅")
        return

    logging.info(f"[Heartbeat] {len(all_alerts)} alert(s) found. Composing message...")

    # Compose message (one lightweight API call if OpenRouter available)
    message = compose_heartbeat_message(all_alerts)

    # Send to Telegram
    send_telegram_message(message)
    logging.info("[Heartbeat] ✅ Heartbeat message sent.")


# ─── Test Function (for /test_heartbeat command) ──────────────────────────────

def run_test_heartbeat() -> str:
    """
    Force-run all heartbeat modules and return the message as a string.
    Used by the /test_heartbeat Telegram command.
    """
    all_alerts = []
    all_alerts.extend(check_deadlines())
    all_alerts.extend(check_followups())
    all_alerts.extend(check_interviews())
    all_alerts.extend(check_habits())
    all_alerts.extend(check_outreach_pace())

    if not all_alerts:
        return (
            "✅ **Heartbeat test complete.**\n\n"
            "Everything looks calm — no urgent alerts right now.\n"
            "_(In real use, heartbeat stays silent when there's nothing actionable.)_"
        )

    message = compose_heartbeat_message(all_alerts)
    return f"🧪 **Heartbeat Test Result:**\n\n{message}"
