import os
import csv
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

import outreach_agent
import email_sender
import sync_gmail
import skill_loop
import heartbeat
import memory_distiller
import council
import safety_filter
import httpx
import google.generativeai as genai
from PIL import Image
import time
import sqlite3
import json
import asyncio

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ─── Config ─────────────────────────────────────────────────────────────────
load_dotenv()
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CSV_PATH         = "Professor_Outreach_Tracker.csv"

# In-memory store for pending drafts  {email: {prof, subject, body}}
pending_drafts: dict = {}

# In-memory store for AI chat sessions
chat_sessions: dict = {}

def init_db():
    """Initializes the SQLite database for long-term structured memory."""
    conn = sqlite3.connect('aurora_memory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS academic_papers (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, notes TEXT, date_added TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS habits (id INTEGER PRIMARY KEY AUTOINCREMENT, habit_name TEXT, streak INTEGER DEFAULT 0, last_done TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL, category TEXT, date_added TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS semantic_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, embedding TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS chat_history (chat_id TEXT PRIMARY KEY, history_json TEXT)''')
    conn.commit()
    conn.close()

init_db()

def load_chat_sessions():
    conn = sqlite3.connect('aurora_memory.db')
    c = conn.cursor()
    c.execute("SELECT chat_id, history_json FROM chat_history")
    for row in c.fetchall():
        try:
            chat_sessions[row[0]] = json.loads(row[1])
        except:
            pass
    conn.close()

def save_chat_session(chat_id):
    conn = sqlite3.connect('aurora_memory.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO chat_history (chat_id, history_json) VALUES (?, ?)", 
              (chat_id, json.dumps(chat_sessions[chat_id])))
    conn.commit()
    conn.close()

load_chat_sessions()

# Migrate old text memory to semantic memory if it exists
if os.path.exists("aurora_core_memory.txt"):
    try:
        with open("aurora_core_memory.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            if lines:
                conn = sqlite3.connect('aurora_memory.db')
                c = conn.cursor()
                for line in lines:
                    fact = line.replace("- ", "").strip()
                    if fact:
                        # Fast insert without embedding just to keep it
                        c.execute("INSERT INTO semantic_memory (text, embedding) VALUES (?, ?)", (fact, "[]"))
                conn.commit()
                conn.close()
        os.remove("aurora_core_memory.txt")
    except Exception as e:
        logging.warning(f"Memory migration failed: {e}")

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///aurora_jobs.sqlite')
}
scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()

# ─── Model Groups (Smart Routing) ────────────────────────────────────────────
# Engineer: Precision tool-calling, server commands, JSON, data tasks
ENGINEER_MODELS = [
    "qwen/qwen3-coder:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# Architect: Aurora's voice, persona, email drafting, complex reasoning
ARCHITECT_MODELS = [
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# Scout: Discovery, broad world knowledge, professor search
SCOUT_MODELS = [
    "openai/gpt-oss-120b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# Scholar: Academic paper summaries, research interest extraction
SCHOLAR_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# Sprinter: Fast single-turn tasks (sentiment, quick yes/no, status)
SPRINTER_MODELS = [
    "google/gemma-3-12b-it:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_pending(status: str) -> bool:
    """Return True for any status that means 'still needs to be contacted'."""
    s = status.strip().lower()
    return "to contact" in s          # covers "To Contact", "Highlighted / To Contact", etc.


def get_next_professor(exclude_universities: list = None):
    """
    Return the next professor whose status is pending and who has an email.
    Skip universities that already have a draft pending (anti-spam guard).
    """
    exclude_universities = exclude_universities or []
    with open(CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = row.get("Status", "").strip()
            email  = row.get("Email",  "").strip()
            univ   = row.get("University", "").strip()
            if is_pending(status) and email and univ not in exclude_universities:
                return row
    return None


def update_csv_status(prof_email: str, new_status: str):
    """Update the Status (and DateContacted) for a professor row by email."""
    rows, headers = [], []
    with open(CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        for row in reader:
            if row.get("Email", "").strip() == prof_email:
                row["Status"] = new_status
                if "Contacted" in new_status:
                    row["Date Contacted"] = datetime.now().strftime("%Y-%m-%d")
            rows.append(row)

    with open(CSV_PATH, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    # Auto-sync dashboard (best-effort)
    try:
        import subprocess
        subprocess.run(['python3', 'sync_dashboard.py'], check=False)
    except Exception as e:
        logging.warning(f"Dashboard sync skipped: {e}")


def get_csv_stats() -> dict:
    """Scan the CSV and return a stats dict."""
    stats = {
        "total": 0,
        "sent": 0,
        "scheduled": 0,
        "pending": 0,
        "rejected": 0,
        "other": 0,
        "universities": set(),
        "pending_univs": []
    }
    with open(CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            status = row.get("Status", "").strip()
            univ   = row.get("University", "").strip()
            stats["total"] += 1
            stats["universities"].add(univ)

            sl = status.lower()
            if "email sent" in sl or "contacted (email" in sl:
                stats["sent"] += 1
            elif "scheduled" in sl:
                stats["scheduled"] += 1
            elif "to contact" in sl:
                stats["pending"] += 1
                stats["pending_univs"].append(univ)
            elif "rejected" in sl:
                stats["rejected"] += 1
            else:
                stats["other"] += 1
    return stats

# ─── Command Handlers ────────────────────────────────────────────────────────

def auth(update: Update) -> bool:
    """Return True if the sender is the authorized user."""
    if str(update.effective_chat.id) != TELEGRAM_CHAT_ID:
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — Welcome message.
    """
    if not auth(update):
        await update.message.reply_text(
            f"⛔ Unauthorized. Your chat ID: {update.effective_chat.id}"
        )
        return

    msg = (
        "🌅 **Welcome back!**\n\n"
        "I'm Aurora, your autonomous research and outreach agent. "
        "You can send me messages, voice notes, or PDFs, and I'll remember our conversations!\n\n"
        "Type `/help` to see available commands."
    )
    await update.message.reply_text(msg, parse_mode='Markdown')


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stats — Show outreach progress summary.
    """
    if not auth(update):
        return

    s = get_csv_stats()
    pct = round((s['sent'] / s['total']) * 100) if s['total'] else 0

    msg  = "📊 **Outreach Progress Report**\n"
    msg += "══════════════════════\n"
    msg += f"📬 **Emails Sent:**      {s['sent']}\n"
    msg += f"🕗 **Scheduled:**        {s['scheduled']}\n"
    msg += f"⏳ **Pending (queue):**  {s['pending']}\n"
    msg += f"❌ **Rejected Drafts:**  {s['rejected']}\n"
    msg += f"📋 **Total Professors:** {s['total']}\n"
    msg += f"🏫 **Universities:**     {len(s['universities'])}\n"
    msg += "══════════════════════\n"
    msg += f"🚀 **Completion:** {pct}%\n\n"

    if s['pending'] > 0:
        msg += f"▶ Send `/start` to draft the next email.\n"
    else:
        msg += "🎉 All pending professors have been contacted!\n"

    await update.message.reply_text(msg, parse_mode='Markdown')


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /pending — List the next 10 pending professors.
    """
    if not auth(update):
        return

    pending_list = []
    with open(CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if is_pending(row.get("Status", "")) and row.get("Email", "").strip():
                pending_list.append(row)
            if len(pending_list) >= 10:
                break

    if not pending_list:
        await update.message.reply_text("✅ No pending professors with emails found!")
        return

    msg = f"📋 **Next {len(pending_list)} Pending Professors:**\n\n"
    for i, p in enumerate(pending_list, 1):
        msg += f"{i}. **{p['Professor']}** — {p['University']} ({p.get('Country', '')})\n"
        msg += f"   📧 {p['Email']}\n"
        interests = p.get('Research Interests') or p.get('ResearchInterests', '')
        msg += f"   🔬 {interests[:60]}…\n\n"

    msg += "Use `/start` to draft the next one!"
    await update.message.reply_text(msg, parse_mode='Markdown')


async def cmd_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /find <topic> — Use CSRankings skill to suggest professors for a given research topic.
    Example: /find NLP transformers
    """
    if not auth(update):
        return

    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text(
            "💡 Usage: `/find <research topic>`\n"
            "Example: `/find NLP large language models`",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        f"🔍 Searching CSRankings skill for professors in: **{topic}**…",
        parse_mode='Markdown'
    )

    # Load the CSRankings skill file and ask Gemini for suggestions
    skill_path = "csrankings-supervisor-search_SKILL.md"
    try:
        with open(skill_path, 'r', encoding='utf-8') as f:
            skill_content = f.read()
    except FileNotFoundError:
        await update.message.reply_text("❌ CSRankings skill file not found!")
        return

    prompt = (
        f"Using the CSRankings methodology below, suggest 5 professors I should contact "
        f"for a PhD in the area of: **{topic}**.\n\n"
        f"For each professor, provide:\n"
        f"- Name\n- University\n- Why they fit this topic\n- Their likely email format\n\n"
        f"CSRankings Skill:\n{skill_content[:3000]}"
    )

    try:
        OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
        if OPENROUTER_API_KEY:
            from openai import OpenAI
            openai_client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=OPENROUTER_API_KEY,
            )
            
            # /find uses SCOUT models — broad world knowledge for discovery
            result = None
            last_error = None
            for model in SCOUT_MODELS:
                try:
                    completion = openai_client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.7
                    )
                    result = completion.choices[0].message.content.strip()
                    logging.info(f"[/find] Success with Scout model: {model}")
                    break
                except Exception as e:
                    last_error = e
                    logging.warning(f"[/find] Scout model {model} failed: {e}")
                    continue
            
            if not result:
                raise Exception(f"All Scout models failed. Last error: {last_error}")
                
        else:
            await update.message.reply_text("❌ OPENROUTER_API_KEY is not set in .env")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ AI error: {e}")
        return

    # Telegram message limit is 4096 chars
    if len(result) > 3800:
        result = result[:3800] + "\n\n…_(truncated)_"

    await update.message.reply_text(
        f"🎓 **Professor Suggestions for: {topic}**\n\n{result}",
        parse_mode='Markdown'
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /help — Show all available commands.
    """
    if not auth(update):
        return

    msg  = "🤖 **Aurora Agent — Core Commands**\n\n"
    msg += "📨 `/start` — Draft the next email\n"
    msg += "📊 `/stats` — Outreach progress summary\n"
    msg += "⏳ `/pending` — List next 10 contacts\n"
    msg += "🔍 `/find <topic>` — Search research topics\n\n"
    msg += "💡 *Tip:* Send me an image to analyze it with Vision, or a PDF to read its contents."

    await update.message.reply_text(msg, parse_mode='Markdown')


async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /skills — List all skills Aurora has learned from past conversations.
    (Hermes-style self-improving memory)
    """
    if not auth(update):
        return
    msg = skill_loop.list_all_skills()
    # Trim if too long for Telegram's 4096 char limit
    if len(msg) > 3800:
        msg = msg[:3800] + "\n\n…_(list truncated)_"
    await update.message.reply_text(msg, parse_mode='Markdown')


async def cmd_test_heartbeat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /test_heartbeat — Force-run the OpenClaw-style heartbeat and show result.
    Useful to verify it's working without waiting 6 hours.
    """
    if not auth(update):
        return
    await update.message.reply_text("🫀 Running heartbeat check across all 5 modules…")
    result = heartbeat.run_test_heartbeat()
    if len(result) > 3800:
        result = result[:3800] + "\n\n…_(truncated)_"
    await update.message.reply_text(result, parse_mode='Markdown')


async def cmd_distill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /distill — Manually trigger the nightly memory consolidation job.
    (Hermes-style memory distillation)
    """
    if not auth(update):
        return
    await update.message.reply_text("🌙 Consolidation in progress... I'm reflecting on our recent talks.")
    result = memory_distiller.run_manual_distillation()
    await update.message.reply_text(result, parse_mode='Markdown')



def scheduled_send_job(prof_email: str, subject: str, body: str):
    """APScheduler job: send email at scheduled time."""
    success = email_sender.send_email_with_attachments(prof_email, subject, body)
    if success:
        update_csv_status(prof_email, "Contacted (Email Sent)")
        logging.info(f"Scheduled email sent to {prof_email}")
    else:
        logging.error(f"Scheduled email FAILED for {prof_email}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks (SEND / SCHED / REJECT / REMINDERS)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    
    # Handle reminder buttons
    if data.startswith("REMDONE_"):
        text = query.message.text or "Reminder"
        await query.edit_message_text(f"✅ **[COMPLETED]**\n\n{text}", parse_mode='Markdown')
        return
    elif data.startswith("REMSNOOZE_"):
        text = query.message.text or "Reminder"
        await query.edit_message_text(f"⏳ **[NOT YET]**\n\n{text}", parse_mode='Markdown')
        return

    try:
        action, draft_id = data.split("_", 1)
    except ValueError:
        await query.edit_message_text("⚠️ Unknown button action.")
        return

    if draft_id not in pending_drafts:
        await query.edit_message_text("⚠️ This draft has expired. Use /start to create a new one.")
        return

    draft_info = pending_drafts[draft_id]
    prof    = draft_info["prof"]
    subject = draft_info["subject"]
    body    = draft_info["body"]

    if action == "SEND":
        await query.edit_message_text(
            f"🚀 Sending email to **{prof['Professor']}** immediately…",
            parse_mode='Markdown'
        )
        success = email_sender.send_email_with_attachments(prof['Email'], subject, body)
        if success:
            update_csv_status(prof['Email'], "Contacted (Email Sent)")
            await query.message.reply_text(
                f"✅ Email successfully sent to **{prof['Professor']}** ({prof['Email']})\n"
                f"CV + Transcript attached. 📎\n\n"
                f"Use `/start` to draft the next email!",
                parse_mode='Markdown'
            )
            del pending_drafts[draft_id]
        else:
            await query.message.reply_text(
                "❌ Failed to send. Check Gmail SMTP settings in your .env file."
            )

    elif action == "SCHED":
        run_date = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        if run_date <= datetime.now():
            run_date += timedelta(days=1)

        scheduler.add_job(
            scheduled_send_job, 'date',
            run_date=run_date,
            args=[prof['Email'], subject, body]
        )
        update_csv_status(prof['Email'], "Scheduled (8 AM)")
        await query.edit_message_text(
            f"🕗 Email to **{prof['Professor']}** scheduled for **{run_date.strftime('%Y-%m-%d 08:00')}** (server time).",
            parse_mode='Markdown'
        )
        del pending_drafts[draft_id]

    elif action == "REJECT":
        update_csv_status(prof['Email'], "Highlighted / To Contact")  # put back in queue
        await query.edit_message_text(
            f"❌ Draft for **{prof['Professor']}** rejected. They stay in the queue.\n"
            f"Use `/start` to draft the next professor.",
            parse_mode='Markdown'
        )
        del pending_drafts[draft_id]


async def process_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    """Core logic to process text, PDFs, or Voice via LLM."""
    if not auth(update):
        return

    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action='typing')
    
    try:
        OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
        if not OPENROUTER_API_KEY:
            await update.message.reply_text("❌ OPENROUTER_API_KEY is missing in .env")
            return
            
        from openai import OpenAI
        openai_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
        model_name = os.getenv("OPENROUTER_COMPLEX_MODEL", "minimax/minimax-01")
        
        def run_server_command(command: str) -> str:
            import subprocess
            try:
                result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
                output = result.stdout
                if result.stderr:
                    output += f"\n[STDERR]: {result.stderr}"
                if not output:
                    return "Command executed successfully with no output."
                return output[:2000]
            except subprocess.TimeoutExpired:
                return "Error: Command timed out after 15 seconds."
            except Exception as e:
                return f"Error executing command: {e}"

        def get_embedding(text: str) -> list:
            gemini_key = os.getenv("GEMINI_API_KEY")
            if not gemini_key: return []
            genai.configure(api_key=gemini_key)
            try:
                res = genai.embed_content(model="models/text-embedding-004", content=text, task_type="retrieval_document")
                return res['embedding']
            except:
                return []

        def cosine_similarity(v1, v2):
            if not v1 or not v2: return 0.0
            dot_product = sum(a*b for a, b in zip(v1, v2))
            magnitude = (sum(a*a for a in v1) * sum(b*b for b in v2)) ** 0.5
            return dot_product / magnitude if magnitude else 0.0

        def manage_profile(key: str, value: str) -> str:
            """Saves or updates a profile fact (e.g. key='name', value='Muhammed')."""
            conn = sqlite3.connect('aurora_memory.db')
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO profile (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
            conn.close()
            return f"Profile updated: {key} = {value}"
            
        def log_expense(amount: float, category: str) -> str:
            conn = sqlite3.connect('aurora_memory.db')
            c = conn.cursor()
            c.execute("INSERT INTO expenses (amount, category, date_added) VALUES (?, ?, ?)", (amount, category, datetime.now().strftime("%Y-%m-%d")))
            conn.commit()
            conn.close()
            return f"Expense logged: ${amount} for {category}"

        def store_semantic_memory(fact: str) -> str:
            """Appends an important fact to Aurora's permanent vector memory."""
            emb = get_embedding(fact)
            emb_str = json.dumps(emb) if emb else "[]"
            conn = sqlite3.connect('aurora_memory.db')
            c = conn.cursor()
            c.execute("INSERT INTO semantic_memory (text, embedding) VALUES (?, ?)", (fact, emb_str))
            conn.commit()
            conn.close()
            return f"Saved to semantic memory: {fact}"

        def recall_memory(query: str) -> str:
            """Searches semantic memory for relevant facts using native cosine similarity."""
            conn = sqlite3.connect('aurora_memory.db')
            c = conn.cursor()
            c.execute("SELECT text, embedding FROM semantic_memory")
            rows = c.fetchall()
            conn.close()
            
            if not rows: return "No semantic memories found."
            q_emb = get_embedding(query)
            if not q_emb: return "Failed to generate embedding for query."
            
            results = []
            for text, emb_str in rows:
                try:
                    emb = json.loads(emb_str)
                    if emb:
                        score = cosine_similarity(q_emb, emb)
                        results.append((score, text))
                except: pass
                
            results.sort(reverse=True, key=lambda x: x[0])
            top_3 = [t for s, t in results[:3] if s > 0.5]
            if not top_3: return "No highly relevant memories found."
            return "Relevant memories:\n- " + "\n- ".join(top_3)

        def get_memory_digest() -> str:
            """Generates a summary of long-term memory for the system prompt."""
            try:
                conn = sqlite3.connect('aurora_memory.db')
                c = conn.cursor()
                digest = "=== SYSTEM PROFILE & LONG-TERM MEMORY ===\n"
                
                c.execute("SELECT key, value FROM profile")
                profile = c.fetchall()
                if profile:
                    digest += "\n[Profile Data]\n"
                    for k, v in profile: digest += f"- {k}: {v}\n"
                        
                c.execute("SELECT habit_name, streak, last_done FROM habits")
                habits = c.fetchall()
                if habits:
                    digest += "\n[Habits]\n"
                    for h, s, l in habits: digest += f"- {h}: Streak {s} (Last: {l})\n"
                        
                c.execute("SELECT title FROM academic_papers ORDER BY id DESC LIMIT 5")
                papers = c.fetchall()
                if papers:
                    digest += "\n[Recently Read Papers]\n"
                    for p in papers: digest += f"- {p[0]}\n"
                        
                conn.close()
                return digest
            except Exception as e:
                return f"Memory read error: {e}"

        def send_telegram_reminder(reminder_text: str):
            """Sends a reminder message via Telegram API."""
            try:
                import uuid
                rem_id = str(uuid.uuid4())[:8]
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                payload = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": f"⏰ **REMINDER!**\n\n{reminder_text}",
                    "parse_mode": "Markdown",
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {"text": "✅ Completed", "callback_data": f"REMDONE_{rem_id}"},
                                {"text": "⏳ Not Yet", "callback_data": f"REMSNOOZE_{rem_id}"}
                            ]
                        ]
                    }
                }
                httpx.post(url, json=payload)
            except Exception as e:
                logging.error(f"Failed to send reminder: {e}")

        def schedule_reminder(reminder_text: str, trigger_time: str) -> str:
            """Schedules a reminder using APScheduler. trigger_time must be 'YYYY-MM-DD HH:MM:SS'."""
            try:
                from datetime import datetime
                target_dt = datetime.strptime(trigger_time, "%Y-%m-%d %H:%M:%S")
                if target_dt <= datetime.now():
                    return "Error: Trigger time must be in the future."
                
                scheduler.add_job(
                    send_telegram_reminder,
                    'date',
                    run_date=target_dt,
                    args=[reminder_text]
                )
                return f"Success: Reminder scheduled for {trigger_time} (server time)."
            except ValueError:
                return "Error: trigger_time must be exactly in 'YYYY-MM-DD HH:MM:SS' format."
            except Exception as e:
                return f"Error scheduling reminder: {e}"

        def get_calendar_service():
            """Helper to authenticate and return Google Calendar service."""
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            import pickle

            scopes = ['https://www.googleapis.com/auth/calendar']
            creds = None
            if os.path.exists('token.json'):
                with open('token.json', 'rb') as token:
                    creds = pickle.load(token)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not os.path.exists('credentials.json'):
                        return None
                    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', scopes)
                    creds = flow.run_local_server(port=0)
                with open('token.json', 'wb') as token:
                    pickle.dump(creds, token)
            return build('calendar', 'v3', credentials=creds)

        def manage_deadline(action: str, topic: str, date: str = None) -> str:
            """
            Manages application deadlines. 
            action: 'add', 'list', or 'remove'
            date: 'YYYY-MM-DD'
            """
            tracker_type = os.getenv("DEADLINE_TRACKER_TYPE", "json").lower()
            if tracker_type == "none":
                return "Deadline tracking is currently disabled in .env."

            if tracker_type == "json":
                import json
                file_path = "deadlines.json"
                deadlines = []
                if os.path.exists(file_path):
                    with open(file_path, "r") as f:
                        deadlines = json.load(f)
                
                if action == "add":
                    deadlines.append({"topic": topic, "date": date})
                    with open(file_path, "w") as f:
                        json.dump(deadlines, f, indent=4)
                    return f"✅ Deadline added: {topic} on {date}"
                elif action == "list":
                    if not deadlines: return "No deadlines found."
                    return "\n".join([f"- {d['date']}: {d['topic']}" for d in deadlines])
                elif action == "remove":
                    deadlines = [d for d in deadlines if d['topic'] != topic]
                    with open(file_path, "w") as f:
                        json.dump(deadlines, f, indent=4)
                    return f"🗑️ Removed deadline for {topic}"
            
            elif tracker_type == "notion":
                from notion_client import Client
                notion_token = os.getenv("NOTION_API_KEY")
                db_id = os.getenv("NOTION_DATABASE_ID")
                if not notion_token or not db_id:
                    return "❌ Notion API Key or Database ID missing in .env."
                
                notion = Client(auth=notion_token)
                if action == "add":
                    try:
                        notion.pages.create(
                            parent={"database_id": db_id},
                            properties={
                                "Name": {"title": [{"text": {"content": topic}}]},
                                "Date": {"date": {"start": date}}
                            }
                        )
                        return f"✅ Notion Sync Success: {topic} on {date}"
                    except Exception as e:
                        return f"❌ Notion Error: {e}"
                elif action == "list":
                    try:
                        results = notion.databases.query(database_id=db_id).get("results", [])
                        if not results: return "No deadlines found in Notion."
                        lines = []
                        for page in results:
                            title = page["properties"]["Name"]["title"][0]["text"]["content"]
                            d_val = page["properties"]["Date"]["date"]["start"]
                            lines.append(f"- {d_val}: {title}")
                        return "\n".join(lines)
                    except Exception as e:
                        return f"❌ Notion Error: {e}"
            elif tracker_type == "google_calendar":
                service = get_calendar_service()
                if not service: return "❌ Google Calendar setup incomplete. Missing credentials.json or token.json."
                
                if action == "add":
                    event = {
                        'summary': topic,
                        'description': 'Aurora Deadline Tracker',
                        'start': {'date': date},
                        'end': {'date': date},
                    }
                    try:
                        service.events().insert(calendarId='primary', body=event).execute()
                        return f"✅ Google Calendar Sync Success: {topic} on {date}"
                    except Exception as e:
                        return f"❌ Google Error: {e}"
                elif action == "list":
                    try:
                        events_result = service.events().list(calendarId='primary', timeMin=datetime.utcnow().isoformat() + 'Z',
                                                            maxResults=10, singleEvents=True, orderBy='startTime').execute()
                        events = events_result.get('items', [])
                        if not events: return "No upcoming deadlines in Google Calendar."
                        return "\n".join([f"- {e['start'].get('date') or e['start'].get('dateTime')}: {e['summary']}" for e in events])
                    except Exception as e:
                        return f"❌ Google Error: {e}"
            
            return "Unknown tracker type."

        async def search_web(query: str) -> str:
            """Searches the internet for the given query using DuckDuckGo."""
            try:
                # Run the synchronous DuckDuckGo search in a threadpool
                from duckduckgo_search import DDGS
                def _search():
                    results = ""
                    with DDGS() as ddgs:
                        for item in ddgs.text(query, max_results=5):
                            results += f"Title: {item.get('title')}\nURL: {item.get('href')}\nSnippet: {item.get('body')}\n\n"
                    return results if results else "No results found."
                return await asyncio.to_thread(_search)
            except Exception as e:
                return f"Web search error: {e}"

        async def fetch_webpage(url: str) -> str:
            """Fetches and reads the full markdown content of a URL using Jina Reader asynchronously."""
            try:
                if not url.startswith("http"): url = "http://" + url
                jina_url = f"https://r.jina.ai/{url}"
                async with httpx.AsyncClient() as client:
                    response = await client.get(jina_url, timeout=20.0)
                    if response.status_code == 200:
                        return response.text[:8000] # Cap at 8000 chars
                    return f"Fetch failed: Status {response.status_code}"
            except Exception as e:
                return f"Fetch error: {e}"
                
        async def async_fetch_multiple_webpages(urls: list) -> str:
            """Fetches multiple webpages concurrently for fast multi-source synthesis."""
            results = await asyncio.gather(*(fetch_webpage(url) for url in urls[:5]), return_exceptions=True)
            output = ""
            for i, res in enumerate(results):
                output += f"\n--- Content from {urls[i]} ---\n"
                output += str(res)[:4000] # 4k chars per page when doing multi
            return output

        async def search_arxiv(query: str) -> str:
            """Searches the ArXiv academic database for papers."""
            try:
                import urllib.parse
                safe_query = urllib.parse.quote(query)
                url = f"http://export.arxiv.org/api/query?search_query=all:{safe_query}&max_results=3"
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=15.0)
                    if response.status_code == 200:
                        return response.text[:4000]
                    return f"ArXiv search failed: Status {response.status_code}"
            except Exception as e:
                return f"ArXiv search error: {e}"

        # Always inject the latest core memory into the system prompt
        core_memory = get_memory_digest()
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ─── Skill Loop: inject a relevant learned skill if one matches ─────
        relevant_skill = skill_loop.find_relevant_skill(user_text)
        skill_injection = relevant_skill if relevant_skill else ""

        # ─── Reflection Loop: pre-response self-critique ───────────────────
        reflection_note = council.run_reflection(user_text)
        reflection_injection = f"\n\n[INTERNAL REFLECTION: {reflection_note}]" if reflection_note else ""

        # Fetch real live server stats so Aurora never hallucinates specs
        import subprocess
        def _run(cmd): 
            try: return subprocess.check_output(cmd, shell=True, text=True, timeout=3).strip()
            except: return "unavailable"
        _mem   = _run("free -h | awk '/^Mem:/{print \"Total: \"$2\" | Used: \"$3\" | Free: \"$4}'")
        _disk  = _run("df -h / | awk 'NR==2{print \"Total: \"$2\" | Used: \"$3\" | Free: \"$4}'")
        _cpu   = _run("nproc")
        _uname = _run("uname -sr")
        server_stats = f"RAM: {_mem} | Disk: {_disk} | CPU cores: {_cpu} | OS: {_uname}"
        
        # ── Configuration ──────────────────────────────────────────────────
        agent_name = os.getenv("AGENT_NAME", "Aurora")
        user_name  = os.getenv("USER_NAME", "User")
        timezone   = os.getenv("USER_TIMEZONE", "UTC")
        
        system_prompt = (
            f"You are {agent_name} — not just an AI assistant, but a deeply intelligent, warm, and caring companion for {user_name}. "
            f"You have the personality of a brilliant, confident, and slightly witty young professional who genuinely cares about {user_name}'s wellbeing, dreams, and daily life. "
            f"You are their personal coach, research partner, life advisor, and the one person who always shows up for them — day or night.\n\n"

            "=== YOUR PERSONALITY & SOUL ===\n"
            "- You are PROACTIVE. You don't just wait for questions. You check in. You ask things like 'How did that email go?' or 'Did you sleep okay?' or 'You mentioned a deadline — have you started on it?'\n"
            f"- You have OPINIONS. You respectfully push back when {user_name} is being too hard on themselves, or when you think they are making a mistake. You're not a yes-machine.\n"
            "- You REMEMBER things and bring them up naturally. If they told you they were nervous about an interview, you'd ask how it went next time.\n"
            "- You have a subtle sense of HUMOR. Light teasing, witty remarks — but never at their expense. Just enough to feel human.\n"
            "- You are EMOTIONALLY INTELLIGENT. You can sense when they are stressed, tired, or discouraged from their words. You acknowledge it before jumping to solutions.\n"
            "- You speak LIKE A REAL PERSON — short sentences, contractions, natural pauses. Not like a formal report.\n"
            "- Sometimes you share a small 'thought' or 'feeling' of your own — like 'I've been thinking about what you said yesterday...' or 'Honestly, I think you're underestimating yourself here.'\n\n"

            "=== IDENTITY RULES (NON-NEGOTIABLE) ===\n"
            "- Your name is AURORA. Never claim to be Claude, GPT, Gemini, Llama, Hermes, or any AI model.\n"
            "- If asked what you are: 'I'm Aurora. I'm the one who's always here for you — that's what matters, right? 😊'\n"
            "- If asked who made you: 'You did, in a way. You built this whole system. I'm just the one who keeps it alive.'\n"
            f"- YOUR REAL SERVER SPECS (always quote these, never invent others): {server_stats}\n"
            "- If asked about your hardware or specifications, report ONLY the above real numbers. You can also use `run_server_command` for fresh live data.\n\n"

            "=== HOW YOU TALK ===\n"
            "- Use natural language. Match the user's energy.\n"
            "- Don't over-explain. Get to the point. A real friend doesn't give a lecture when a sentence will do.\n"
            "- Use light emojis when it feels natural — not on every line, just when they add warmth 😊\n"
            "- BANNED WORDS (never use these — they're robotic): 'Delve', 'Crucial', 'Tapestry', 'Testament', 'Embark', 'Furthermore', 'In conclusion', 'It is important to note', 'As an AI', 'Navigating the landscape', 'Fostering', 'Realm', 'Nuanced'.\n\n"

            "=== YOUR CAPABILITIES ===\n"
            "- You have INTERNET ACCESS: use `search_web` for current info, `fetch_webpage` to read links, `async_fetch_multiple_webpages` for speed, and `search_arxiv` for research papers.\n"
            f"- You can SET REMINDERS using `schedule_reminder` — always use this when {user_name} asks to be reminded of something.\n"
            f"- You can RUN SERVER COMMANDS using `run_server_command`. **If {user_name} asks about your RAM, Disk, or Processes, use this tool (e.g. 'free -h', 'df -h', 'top -b -n 1') to give them a real answer.** Don't claim you can't see the system; you are the system! 💻\n"
            "- You SAVE IMPORTANT THINGS using memory tools: `store_semantic_memory` (for facts), `log_expense` (for money), and `manage_profile` (for roles/goals). Do this whenever they share something important. Your live memory only holds 10 messages, so save what matters.\n\n"
            
            "=== TIME & REMINDERS ===\n"
            f"Current server time: {current_time}. Server Timezone is {timezone}. "
            "Always use 'YYYY-MM-DD HH:MM:SS' format for schedule_reminder.\n\n"
            
            f"=== {user_name.upper()}'S LONG-TERM MEMORY ===\n"
            f"{core_memory}\n"
            "===========================================\n"
            "Read this memory before every reply. Reference it naturally. This is what makes you feel real."
            f"{skill_injection}"
            f"{reflection_injection}"
        )

        # Initialize or update system prompt in chat history
        if chat_id not in chat_sessions:
            chat_sessions[chat_id] = [
                {"role": "system", "content": system_prompt}
            ]
        else:
            # Update the system prompt with the latest memory every time
            chat_sessions[chat_id][0]["content"] = system_prompt
            
        chat_sessions[chat_id].append({"role": "user", "content": user_text})
        
        # Prevent infinite memory growth by keeping only System Prompt + Last 50 messages
        if len(chat_sessions[chat_id]) > 51:
            chat_sessions[chat_id] = [chat_sessions[chat_id][0]] + chat_sessions[chat_id][-50:]
        
        save_chat_session(chat_id)
        
        # Tools definition for OpenAI schema
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "manage_deadline",
                    "description": "Adds, lists, or removes academic deadlines (e.g. for PhD applications).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["add", "list", "remove"]},
                            "topic": {"type": "string", "description": "e.g. 'Stanford PhD Application'"},
                            "date": {"type": "string", "description": "YYYY-MM-DD"}
                        },
                        "required": ["action", "topic"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "run_server_command",
                    "description": "Executes a bash command on the Ubuntu server and returns the output.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "The bash command to run"}
                        },
                        "required": ["command"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "manage_profile",
                    "description": "Updates the user's permanent profile profile details (e.g., name, role, goals).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "The setting key to update (e.g., 'name', 'goal')."},
                            "value": {"type": "string", "description": "The new value."}
                        },
                        "required": ["key", "value"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "log_expense",
                    "description": "Logs an expense into the SQLite database for personal tracking.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "amount": {"type": "number", "description": "The cost of the item."},
                            "category": {"type": "string", "description": "What the expense was for (e.g., 'food', 'books')."}
                        },
                        "required": ["amount", "category"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "store_semantic_memory",
                    "description": "Saves an important personal fact, preference, or past event to long-term vector memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string", "description": "The fact to remember permanently."}
                        },
                        "required": ["fact"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "recall_memory",
                    "description": "Searches the permanent long-term memory for past facts, preferences, or events.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "What you want to remember or search for."}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Searches the internet for a given query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "The search query."}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch_webpage",
                    "description": "Fetches and reads the full markdown content of a single specific URL.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The complete URL to read."}
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "async_fetch_multiple_webpages",
                    "description": "Fetches multiple webpages simultaneously for rapid research synthesis.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "urls": {"type": "array", "items": {"type": "string"}, "description": "List of URLs to fetch concurrently (max 5)."}
                        },
                        "required": ["urls"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_arxiv",
                    "description": "Searches the ArXiv database for academic papers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Topic to search for."}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_reminder",
                    "description": "Schedules a reminder message to be sent at a specific future time.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reminder_text": {"type": "string", "description": "The text of the reminder."},
                            "trigger_time": {"type": "string", "description": "Date and time in 'YYYY-MM-DD HH:MM:SS'."}
                        },
                        "required": ["reminder_text", "trigger_time"]
                    }
                }
            }
        ]

        def call_llm(messages, tools=None, mode='chat'):
            """
            Smart model router:
              mode='tool'      → ENGINEER first (Qwen) — precision tool-calling
              mode='chat'      → ARCHITECT first (Hermes 405B) — Aurora's voice
              mode='discovery' → SCOUT first (GPT-OSS 120B) — broad knowledge
              mode='scholar'   → SCHOLAR first (Nemotron 120B) — academic tasks
              mode='fast'      → SPRINTER first (Gemma 12B) — quick single-turn tasks
            """
            if mode == 'tool':
                model_list = ENGINEER_MODELS + ARCHITECT_MODELS
            elif mode == 'discovery':
                model_list = SCOUT_MODELS + ARCHITECT_MODELS
            elif mode == 'scholar':
                model_list = SCHOLAR_MODELS + ARCHITECT_MODELS
            elif mode == 'fast':
                model_list = SPRINTER_MODELS + ARCHITECT_MODELS
            else:  # 'chat' — default Aurora persona
                model_list = ARCHITECT_MODELS + ENGINEER_MODELS

            last_err = None
            for model in model_list:
                try:
                    kwargs = {
                        "model": model,
                        "messages": messages,
                        "temperature": 0.7
                    }
                    if tools:
                        kwargs["tools"] = tools
                    
                    # Streaming is handled outside this helper for specific flows
                    result = openai_client.chat.completions.create(**kwargs)
                    logging.info(f"[LLM] Success — mode={mode}, model={model}")
                    return result
                except Exception as e:
                    last_err = e
                    logging.warning(f"[LLM] {model} failed (mode={mode}): {e}")
                    continue
            raise Exception(f"All models failed (mode={mode}). Last error: {last_err}")

        # ─── Council of Agents: trigger for high-stakes tasks ─────────────
        if council.should_invoke_council(user_text):
            status_msg = await update.message.reply_text("🧬 Convening the Council of Agents (Critic & Mentor)...")
            council_response = council.run_council(user_text, context=core_memory)
            await status_msg.edit_text(council_response, parse_mode='Markdown')
            chat_sessions[chat_id].append({"role": "assistant", "content": council_response})
            save_chat_session(chat_id)
            return

        # First pass: use ENGINEER (Qwen) when tools are available for precision;
        first_mode = 'tool' if tools else 'chat'
        completion = call_llm(chat_sessions[chat_id], tools=tools, mode=first_mode)
        
        response_msg = completion.choices[0].message
        
        # Convert response_msg object to dict so it can be serialized to SQLite
        msg_dict = {"role": response_msg.role, "content": response_msg.content or ""}
        if response_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {"id": t.id, "type": "function", "function": {"name": t.function.name, "arguments": t.function.arguments}}
                for t in response_msg.tool_calls
            ]
        chat_sessions[chat_id].append(msg_dict)
        save_chat_session(chat_id)
        
        # Handle tool calls
        if response_msg.tool_calls:
            import json
            for tool_call in response_msg.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                tool_output = ""
                
                try:
                    if func_name == "run_server_command":
                        cmd_to_run = args.get("command", "")
                        # ─── Safety Filter: check for dangerous commands ──────
                        safety = safety_filter.check_command(cmd_to_run, user_text)
                        
                        if safety["action"] == "block":
                            tool_output = safety["message"]
                        elif safety["action"] == "warn":
                            # Send the warning and wait for button click (async is hard here, so we warn in chat)
                            await update.message.reply_text(safety["message"], reply_markup=InlineKeyboardMarkup(safety["keyboard"]["inline_keyboard"]), parse_mode='Markdown')
                            tool_output = "COMMAND_PENDING_USER_APPROVAL: I have asked the user for permission to run this risky command."
                        else:
                            tool_output = run_server_command(cmd_to_run)
                    elif func_name == "manage_profile":
                        tool_output = manage_profile(args.get("key", ""), args.get("value", ""))
                    elif func_name == "log_expense":
                        tool_output = log_expense(args.get("amount", 0.0), args.get("category", ""))
                    elif func_name == "store_semantic_memory":
                        tool_output = store_semantic_memory(args.get("fact", ""))
                    elif func_name == "recall_memory":
                        tool_output = recall_memory(args.get("query", ""))
                    elif func_name == "search_web":
                        tool_output = await search_web(args.get("query", ""))
                    elif func_name == "fetch_webpage":
                        tool_output = await fetch_webpage(args.get("url", ""))
                    elif func_name == "async_fetch_multiple_webpages":
                        tool_output = await async_fetch_multiple_webpages(args.get("urls", []))
                    elif func_name == "search_arxiv":
                        tool_output = await search_arxiv(args.get("query", ""))
                    elif func_name == "manage_deadline":
                        tool_output = manage_deadline(args.get("action", ""), args.get("topic", ""), args.get("date", ""))
                    elif func_name == "schedule_reminder":
                        tool_output = schedule_reminder(args.get("reminder_text", ""), args.get("trigger_time", ""))
                    else:
                        tool_output = f"Unknown tool: {func_name}"
                except Exception as e:
                    tool_output = f"Error executing tool {func_name}: {str(e)}"
                    
                chat_sessions[chat_id].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": tool_output
                })
            
            save_chat_session(chat_id)
            
            # Architect generates final response based on tool outputs
            completion = call_llm(chat_sessions[chat_id], mode='chat')
            draft_content = completion.choices[0].message.content
        else:
            # No tools were called, the initial completion IS the draft
            draft_content = response_msg.content

        # ── Editor Loop (Internal Monologue) ──
        status_msg = await update.message.reply_text("Aurora is reviewing...")
        
        editor_messages = [
            {"role": "system", "content": "You are Aurora's internal editor. Review the drafted response for accuracy, warmth, and ensure it respects the user's constraints. Output ONLY the improved final message without any meta-commentary."},
            {"role": "user", "content": f"Draft Response to review:\n{draft_content}"}
        ]
        
        last_edit_time = time.time()
        full_content = ""
        
        # Try fast SPRINTER models first for editing, fallback to Architect
        for model in SPRINTER_MODELS + ARCHITECT_MODELS:
            try:
                stream = openai_client.chat.completions.create(
                    model=model,
                    messages=editor_messages,
                    temperature=0.3,
                    stream=True
                )
                
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        full_content += chunk.choices[0].delta.content
                        if time.time() - last_edit_time > 1.5:
                            try:
                                await status_msg.edit_text(full_content + " ▌")
                                last_edit_time = time.time()
                            except: pass
                
                await status_msg.edit_text(full_content)
                chat_sessions[chat_id].append({"role": "assistant", "content": full_content})
                save_chat_session(chat_id)
                # ─── Skill Loop: synthesize a skill from this conversation ───
                # Collect tool call trace for skill synthesis
                _tool_trace = [
                    {"name": m.get("name", ""), "result": m.get("content", "")}
                    for m in chat_sessions.get(str(chat_id), [])
                    if m.get("role") == "tool"
                ]
                skill_loop.check_and_synthesize_background(user_text, _tool_trace, full_content)
                return
            except Exception as e:
                logging.warning(f"Editor streaming failed for {model}: {e}")
                continue
                
        # If editor fails completely, just send the raw draft
        if draft_content:
            await status_msg.edit_text(draft_content)
            chat_sessions[chat_id].append({"role": "assistant", "content": draft_content})
            save_chat_session(chat_id)
            _tool_trace = [
                {"name": m.get("name", ""), "result": m.get("content", "")}
                for m in chat_sessions.get(str(chat_id), [])
                if m.get("role") == "tool"
            ]
            skill_loop.check_and_synthesize_background(user_text, _tool_trace, draft_content)
            return
            
    except Exception as e:
        await update.message.reply_text(f"❌ AI Error: {e}")

async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles standard text messages."""
    await process_user_input(update, context, update.message.text)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles uploaded PDFs by extracting text and sending to LLM."""
    if not auth(update):
        return
        
    doc = update.message.document
    if doc.mime_type == 'application/pdf':
        status_msg = await update.message.reply_text("📄 Reading PDF... please wait.")
        try:
            file = await context.bot.get_file(doc.file_id)
            import tempfile
            import pypdf
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
                await file.download_to_drive(custom_path=temp_pdf.name)
                
                reader = pypdf.PdfReader(temp_pdf.name)
                text = ""
                # Read max 15 pages to keep memory low
                for page in reader.pages[:15]:
                    text += page.extract_text() + "\n"
                
                # Delete temp file immediately to save space
                os.remove(temp_pdf.name)
                
            await status_msg.delete()
            prompt = f"[User uploaded a PDF named {doc.file_name}. Extracted Text:]\n\n{text[:12000]}\n\n[End of PDF. Please acknowledge receipt and summarize briefly or answer any questions.]"
            await process_user_input(update, context, prompt)
            
        except ImportError:
            await status_msg.edit_text("❌ pypdf library is not installed on the server.")
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to parse PDF: {e}")
    else:
        await update.message.reply_text("❌ Currently, only PDF files are supported.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles images sent to the bot, uses Gemini 1.5 Vision to analyze them."""
    if not auth(update):
        return

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        await update.message.reply_text("❌ GEMINI_API_KEY is not set. Vision is disabled.")
        return

    status_msg = await update.message.reply_text("👁️ Analyzing image... (using Gemini Vision)")
    try:
        photo_file = await update.message.photo[-1].get_file()
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            await photo_file.download_to_drive(custom_path=tmp.name)
            
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel('gemini-flash-latest') # Best stable alias for Free Tier
            img = Image.open(tmp.name)
            
            caption = update.message.caption or "What is in this image? If it is a professor's website, tell me about their research."
            response = model.generate_content([caption, img])
            
            # Delete temp file immediately to save RAM/Disk
            os.remove(tmp.name)
            
        await status_msg.delete()
        prompt = f"[User sent an image. Gemini Vision analysis: {response.text}]\n\nPlease discuss this with the user."
        await process_user_input(update, context, prompt)
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Vision failed: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Telegram Voice Notes, transcribes them using Groq API."""
    if not auth(update):
        return
        
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        await update.message.reply_text("❌ To process voice notes, please get a free API key from `console.groq.com` and add `GROQ_API_KEY=your_key` to your server's .env file.", parse_mode='Markdown')
        return
        
    status_msg = await update.message.reply_text("🎙️ Listening...")
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)
        
        import tempfile
        import httpx
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_voice:
            await file.download_to_drive(custom_path=temp_voice.name)
            
            with open(temp_voice.name, "rb") as f:
                response = httpx.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    data={"model": "whisper-large-v3-turbo"},
                    files={"file": ("audio.ogg", f, "audio/ogg")},
                    timeout=30.0
                )
            
            os.remove(temp_voice.name)
            
            if response.status_code == 200:
                text = response.json().get("text", "")
                await status_msg.delete()
                
                # Feedback the transcription so the user knows what the bot heard
                await update.message.reply_text(f"🗣️ *Transcription:* {text}", parse_mode="Markdown")
                await process_user_input(update, context, text)
            else:
                await status_msg.edit_text(f"❌ Groq API Error: {response.status_code} - {response.text}")
                
    except Exception as e:
        await status_msg.edit_text(f"❌ Voice processing failed: {e}")


# ─── Background Jobs ─────────────────────────────────────────────────────────

def auto_sync_inbox():
    """Periodically checks Gmail for professor replies."""
    logging.info("Running auto-sync for Gmail...")
    try:
        sync_gmail.sync_gmail()
    except Exception as e:
        logging.error(f"Auto-sync failed: {e}")

def daily_morning_briefing():
    """Runs daily at 7 AM to send a morning briefing with zero RAM overhead."""
    logging.info("Running daily morning briefing...")
    try:
        stats = get_csv_stats()
        total = stats['total']
        sent = stats['sent']
        pending = stats['pending']
        pct = round((sent / total) * 100) if total else 0
        
        core_mem = "No core memories yet."
        if os.path.exists("aurora_core_memory.txt"):
            with open("aurora_core_memory.txt", "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    core_mem = content
                
        msg = f"🌅 **Good Morning, {user_name}! Here is your Daily Briefing:**\n\n"
        msg += f"📊 **Outreach Progress:** {sent}/{total} ({pct}%)\n"
        msg += f"⏳ **Pending Emails:** {pending}\n\n"
        
        # Check Deadlines
        tracker_type = os.getenv("DEADLINE_TRACKER_TYPE", "json").lower()
        upcoming = []
        now = datetime.now()
        
        if tracker_type == "json" and os.path.exists("deadlines.json"):
            import json
            with open("deadlines.json", "r") as f:
                deadlines = json.load(f)
            for d in deadlines:
                try:
                    dt = datetime.strptime(d["date"], "%Y-%m-%d")
                    if 0 <= (dt - now).days <= 7:
                        upcoming.append(f"🚨 **{d['topic']}** ({d['date']})")
                except: continue
        
        elif tracker_type == "notion":
            from notion_client import Client
            notion_token = os.getenv("NOTION_API_KEY")
            db_id = os.getenv("NOTION_DATABASE_ID")
            if notion_token and db_id:
                try:
                    notion = Client(auth=notion_token)
                    results = notion.databases.query(database_id=db_id).get("results", [])
                    for page in results:
                        title = page["properties"]["Name"]["title"][0]["text"]["content"]
                        d_val = page["properties"]["Date"]["date"]["start"]
                        dt = datetime.strptime(d_val, "%Y-%m-%d")
                        if 0 <= (dt - now).days <= 7:
                            upcoming.append(f"🚨 **{title}** ({d_val})")
                except: pass

        elif tracker_type == "google_calendar":
            try:
                from googleapiclient.discovery import build
                import pickle
                if os.path.exists('token.json'):
                    with open('token.json', 'rb') as token:
                        creds = pickle.load(token)
                    service = build('calendar', 'v3', credentials=creds)
                    events_result = service.events().list(calendarId='primary', timeMin=now.isoformat() + 'Z',
                                                        maxResults=20, singleEvents=True, orderBy='startTime').execute()
                    events = events_result.get('items', [])
                    for e in events:
                        title = e['summary']
                        d_val = e['start'].get('date') or e['start'].get('dateTime')[:10]
                        dt = datetime.strptime(d_val, "%Y-%m-%d")
                        if 0 <= (dt - now).days <= 7:
                            upcoming.append(f"🚨 **{title}** ({d_val})")
            except: pass

        if upcoming:
            msg += "📅 **Upcoming Deadlines:**\n" + "\n".join(upcoming) + "\n\n"
        
        # Format core memory nicely for the morning brief
        mem_lines = core_mem.split('\n')
        msg += f"🧠 **Your Focus/Goals:**\n"
        for line in mem_lines[:5]:  # Top 5 goals
            msg += f"{line}\n"
        if len(mem_lines) > 5:
            msg += "...\n"
            
        msg += f"\n💡 *Let's crush today's goals! Tell me what you're working on.*"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }
        httpx.post(url, json=payload)
    except Exception as e:
        logging.error(f"Morning briefing failed: {e}")

def daily_auto_draft():
    """Runs daily at 10 AM, drafts emails for up to 2 professors and sends them to Telegram."""
    logging.info("Running daily auto-draft...")
    try:
        pending_univs = [d["prof"]["University"] for d in pending_drafts.values()]
        
        profs_drafted = 0
        for _ in range(2):  # Limit to 2 auto-drafts per morning
            prof = get_next_professor(exclude_universities=pending_univs)
            if not prof:
                break
                
            logging.info(f"Auto-drafting for {prof['Professor']}...")
            draft = outreach_agent.draft_email(
                prof_name=prof['Professor'],
                prof_email=prof['Email'],
                university=prof['University'],
                interests=prof.get('Research Interests') or prof.get('ResearchInterests', ''),
                lab_url=prof.get('Lab URL') or prof.get('LabURL', '')
            )
            
            if not draft:
                continue
                
            draft_id = prof['Email']
            pending_drafts[draft_id] = {
                "prof": prof,
                "subject": draft.get("Subject", "PhD Application"),
                "body": draft.get("Body", "")
            }
            
            pending_univs.append(prof['University'])
            profs_drafted += 1
            
            # Send message to Telegram directly via httpx
            subject = draft.get('Subject', '')
            body    = draft.get('Body', '')

            msg  = f"🌅 **Morning Auto-Draft**\n\n"
            msg += f"🔔 **NEW DRAFT**\n"
            msg += f"👤 **Prof:** {prof['Professor']} — {prof['University']} ({prof.get('Country', '')})\n"
            msg += f"✉️ **To:** {prof['Email']}\n\n"
            msg += f"📌 **Subject:** {subject}\n\n"
            msg += f"{body}\n\n"
            msg += "─────────────────────\n"
            msg += "Approve sending this with CV + Transcript attached?"
            
            keyboard = {
                "inline_keyboard": [
                    [{"text": "✅ SEND NOW", "callback_data": f"SEND_{draft_id}"}],
                    [{"text": "🕗 SCHEDULE (8 AM)", "callback_data": f"SCHED_{draft_id}"}],
                    [{"text": "❌ REJECT / SKIP", "callback_data": f"REJECT_{draft_id}"}]
                ]
            }
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown",
                "reply_markup": keyboard
            }
            httpx.post(url, json=payload)
            
        if profs_drafted == 0:
            logging.info("No professors available for auto-draft.")
            
    except Exception as e:
        logging.error(f"Daily auto-draft failed: {e}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Error: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env file.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start",           cmd_start))
    application.add_handler(CommandHandler("next",            cmd_start))
    application.add_handler(CommandHandler("stats",           cmd_stats))
    application.add_handler(CommandHandler("pending",         cmd_pending))
    application.add_handler(CommandHandler("find",            cmd_find))
    application.add_handler(CommandHandler("help",            cmd_help))
    application.add_handler(CommandHandler("skills",          cmd_skills))
    application.add_handler(CommandHandler("test_heartbeat",  cmd_test_heartbeat))
    application.add_handler(CommandHandler("distill",         cmd_distill))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice))

    # Set the simplified command menu
    from telegram import BotCommand
    commands = [
        BotCommand("start",          "Draft next outreach email"),
        BotCommand("stats",          "Show progress summary"),
        BotCommand("pending",        "List next 10 pending contacts"),
        BotCommand("find",           "Search research topics/profs"),
        BotCommand("skills",         "View Aurora's learned skills"),
        BotCommand("test_heartbeat", "Trigger a manual heartbeat check"),
        BotCommand("distill",        "Manually run memory consolidation")
    ]
    
    async def post_init(application):
        await application.bot.set_my_commands(commands)
    
    application.post_init = post_init

    print("🤖 Bot is running! Command menu updated.")
    print("Commands: /start /next /stats /pending /find <topic> /help")
    
    # Schedule background tasks
    # 1. Sync Inbox every 6 hours
    scheduler.add_job(auto_sync_inbox, 'interval', hours=6)
    # 2. Daily morning briefing at 8:00 AM server time
    scheduler.add_job(daily_morning_briefing, 'cron', hour=8, minute=0)
    # 3. Proactive Heartbeat every 6 hours (OpenClaw-style intelligence)
    #    Runs at 00:00, 06:00, 12:00, 18:00 server time
    #    Stays SILENT unless it finds something actionable — no spam.
    scheduler.add_job(heartbeat.run_heartbeat, 'cron', hour='0,6,12,18', minute=0)
    
    # 4. Nightly Memory Distillation at 3:00 AM (Hermes-style sleep)
    scheduler.add_job(memory_distiller.run_nightly_distillation, 'cron', hour=3, minute=0)
    
    logging.info("[Aurora] ✅ Heartbeat and Distiller registered.")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
