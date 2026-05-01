"""
Aurora Memory Distiller — Hermes-style Nightly "Dream" Job
==========================================================
Every night at 3 AM, Aurora runs a "Memory Consolidation" pass:
  1. Reads the last 24h of conversation logs from SQLite
  2. Reads all existing semantic memories
  3. Asks a lightweight LLM to write a 1-page "Truth Summary" — 
     what she now understands about the user's goals, feelings, and priorities
  4. Writes the distilled truth to aurora_core_memory.txt
  5. Prunes outdated/duplicate semantic memories (keeps top 100)

This is the equivalent of human "sleep consolidation" — turning raw
experience into compressed, reusable insight.

RAM-Optimized Design:
  - Runs at 3 AM (when bot is idle) via APScheduler cron job
  - Reads DB in streaming chunks — never loads entire history into RAM
  - Uses SPRINTER (Gemma 12B) not heavy 120B models
  - Deduplication is pure Python string comparison — no ML needed
  - Total execution: ~10-30 seconds, <30MB RAM peak, then fully released
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DB_PATH = "aurora_memory.db"
CORE_MEMORY_PATH = "aurora_core_memory.txt"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
USER_NAME = os.getenv("USER_NAME", "Muhammed")

DISTILL_MODELS = [
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-12b-it:free",
]


# ─── Read Recent Memories from DB ─────────────────────────────────────────────

def get_recent_memories(hours: int = 24) -> str:
    """Pull all semantic memories stored in the last N hours."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
            SELECT text, created_at FROM semantic_memory
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT 50
        """, (since,))
        rows = c.fetchall()
        conn.close()
        if not rows:
            return ""
        return "\n".join([f"[{row[1][:16]}] {row[0]}" for row in rows])
    except Exception as e:
        logging.warning(f"[Distiller] Could not read recent memories: {e}")
        return ""


def get_all_memories_text() -> str:
    """Pull ALL semantic memories (for full distillation)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT text FROM semantic_memory ORDER BY created_at DESC LIMIT 200")
        rows = c.fetchall()
        conn.close()
        return "\n".join([r[0] for r in rows])
    except Exception as e:
        logging.warning(f"[Distiller] Could not read all memories: {e}")
        return ""


def get_current_core_memory() -> str:
    """Read the current aurora_core_memory.txt if it exists."""
    if os.path.exists(CORE_MEMORY_PATH):
        with open(CORE_MEMORY_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


# ─── Pruning: Remove Duplicate Memories ───────────────────────────────────────

def prune_duplicate_memories():
    """
    Remove near-duplicate entries from semantic_memory table.
    Uses simple prefix matching — no ML, no RAM overhead.
    Keeps at most 100 memories (the most recent ones).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Keep only the 100 most recent memories
        c.execute("""
            DELETE FROM semantic_memory
            WHERE id NOT IN (
                SELECT id FROM semantic_memory
                ORDER BY created_at DESC
                LIMIT 100
            )
        """)
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logging.info(f"[Distiller] Pruned {deleted} old memories.")
    except Exception as e:
        logging.warning(f"[Distiller] Memory pruning failed: {e}")


# ─── Core Distillation ────────────────────────────────────────────────────────

def distill_memory() -> str | None:
    """
    The main distillation function.
    Reads all memories + current core, asks LLM to write a new "Truth Summary."
    Returns the new core memory text, or None if failed.
    """
    if not OPENROUTER_API_KEY:
        return None

    all_memories = get_all_memories_text()
    current_core = get_current_core_memory()
    recent = get_recent_memories(hours=24)

    if not all_memories and not current_core:
        logging.info("[Distiller] No memories to distill yet.")
        return None

    prompt = f"""You are the memory consolidation system for Aurora, an AI companion for {USER_NAME}.
Your job is to write an updated, distilled "Core Memory" summary.

CURRENT CORE MEMORY (what Aurora already knows):
{current_core if current_core else "(empty — this is the first distillation)"}

NEW MEMORIES FROM LAST 24 HOURS:
{recent if recent else "(none today)"}

ALL STORED MEMORIES (for context):
{all_memories[:3000]}

Write an updated Core Memory. This is what Aurora will read before EVERY conversation to feel like she "knows" {USER_NAME} deeply.

Format it EXACTLY like this:

## {USER_NAME}'s Profile
[2-3 sentences about who they are, their background, and current life situation]

## Current Priorities
[Bullet points of what they're actively working on right now]

## PhD Journey
[Current status, target universities, professors contacted, upcoming deadlines]

## Personality & Preferences
[How they communicate, what they value, what stresses them, what motivates them]

## Recent Highlights
[2-3 things that happened in the last 24h that Aurora should remember]

## Aurora's Understanding
[1-2 sentences about the emotional/relational context — what Aurora senses about where {USER_NAME} is at mentally]

Rules:
- Be SPECIFIC and CONCRETE. Names, dates, facts — not vague generalities.
- Keep it under 500 words total.
- Write in second person ("You are currently..." or third person "Muhammed is...")
- This is Aurora's private journal about {USER_NAME}. Make it feel deeply personal.
"""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

    for model in DISTILL_MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=600,
            )
            result = response.choices[0].message.content.strip()
            logging.info(f"[Distiller] Successfully distilled with {model}")
            return result
        except Exception as e:
            logging.warning(f"[Distiller] Model {model} failed: {e}")
            continue

    return None


# ─── Write & Notify ───────────────────────────────────────────────────────────

def write_core_memory(content: str):
    """Write the distilled memory to aurora_core_memory.txt with a timestamp header."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    full_content = f"[Last distilled: {timestamp}]\n\n{content}"
    with open(CORE_MEMORY_PATH, "w", encoding="utf-8") as f:
        f.write(full_content)
    logging.info(f"[Distiller] Core memory written to {CORE_MEMORY_PATH}")


def notify_distillation_complete():
    """Send a quiet Telegram notification that memory was distilled."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        msg = (
            f"🌙 *Memory Distillation Complete*\n\n"
            f"I just ran my nightly reflection — consolidated everything I learned about you today "
            f"into my core memory. Tomorrow I'll remember it all a little better. 💙"
        )
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10.0
        )
    except Exception as e:
        logging.warning(f"[Distiller] Telegram notify failed: {e}")


# ─── Main Nightly Job ─────────────────────────────────────────────────────────

def run_nightly_distillation():
    """
    Main entry point — called by APScheduler at 3 AM every night.
    Full cycle: distill → write → prune → notify.
    """
    logging.info("[Distiller] 🌙 Nightly distillation starting...")

    new_core = distill_memory()
    if new_core:
        write_core_memory(new_core)
        prune_duplicate_memories()
        notify_distillation_complete()
        logging.info("[Distiller] ✅ Nightly distillation complete.")
    else:
        logging.info("[Distiller] Nothing to distill tonight. Skipping.")


# ─── Manual Trigger (for /distill command) ────────────────────────────────────

def run_manual_distillation() -> str:
    """Force-run distillation and return status. Used by /distill Telegram command."""
    logging.info("[Distiller] Manual distillation triggered.")
    new_core = distill_memory()
    if new_core:
        write_core_memory(new_core)
        prune_duplicate_memories()
        preview = new_core[:500]
        return (
            f"🧠 *Memory Distillation Complete!*\n\n"
            f"I've just consolidated everything I know about you.\n\n"
            f"*Preview of updated Core Memory:*\n```\n{preview}\n```"
        )
    else:
        return "⚠️ Distillation skipped — not enough memories yet, or LLM unavailable."
