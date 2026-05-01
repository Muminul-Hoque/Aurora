"""
Aurora Skill Loop — Hermes-style Self-Improving Memory
=====================================================
After any conversation with 3+ tool calls, Aurora reviews its own workflow
and auto-generates a reusable Markdown skill file. These skill files are:
  1. Saved to skills/ directory (disk, zero RAM cost)
  2. Indexed in SQLite for fast retrieval
  3. Injected into future conversations when relevant

RAM-Optimized Design:
  - Uses SPRINTER (Gemma 12B via API) not a local model — zero local RAM
  - Synthesis runs in a background thread — never blocks the user
  - Skill files are flat Markdown — no in-memory cache
  - One SQLite table added to existing aurora_memory.db
"""

import os
import re
import json
import logging
import sqlite3
import threading
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

SKILLS_DIR = "skills"
DB_PATH = "aurora_memory.db"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Use lightweight SPRINTER models for synthesis (saves RAM vs. 120B Scholar)
SYNTHESIS_MODELS = [
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]

# ─── DB Setup ──────────────────────────────────────────────────────────────────

def init_skills_db():
    """Create the skills index table and the skills directory if needed."""
    os.makedirs(SKILLS_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS skills_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT UNIQUE,
            trigger_keywords TEXT,
            description TEXT,
            file_path TEXT,
            use_count INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_skills_db()

# ─── Core Decision Gate ────────────────────────────────────────────────────────

def should_synthesize(tool_call_trace: list) -> bool:
    """
    Returns True if the conversation is worth turning into a skill.
    Trigger: 3 or more distinct tool calls in one turn.
    """
    return len(tool_call_trace) >= 3


# ─── Skill Synthesis ───────────────────────────────────────────────────────────

def synthesize_skill(user_query: str, tool_call_trace: list, final_answer: str) -> dict | None:
    """
    Ask the LLM to synthesize a reusable skill from this successful workflow.
    Returns dict with: skill_name, trigger_keywords, description, content
    """
    if not OPENROUTER_API_KEY:
        return None

    # Build a clean summary of what tools were called
    tool_summary = "\n".join(
        [f"  {i+1}. Tool: `{t.get('name')}` → Result: {str(t.get('result', ''))[:200]}"
         for i, t in enumerate(tool_call_trace)]
    )

    synthesis_prompt = f"""You are Aurora's self-improvement engine. A task was completed successfully.
Your job: Create a reusable skill file so Aurora can do this type of task faster next time.

USER QUERY: {user_query}

TOOL WORKFLOW USED:
{tool_summary}

FINAL ANSWER DELIVERED: {final_answer[:500]}

Write a reusable skill in this EXACT JSON format (no markdown, raw JSON only):
{{
  "skill_name": "snake_case_name_under_5_words",
  "trigger_keywords": "comma separated words that would trigger this skill",
  "description": "One sentence: what this skill does",
  "content": "## Skill: [Name]\\n\\n### When to use:\\n[situation]\\n\\n### Steps:\\n1. [step]\\n2. [step]\\n...\\n\\n### Key Tips:\\n- [tip]"
}}

Rules:
- skill_name must be short and descriptive (e.g. "canadian_professor_search")
- trigger_keywords must be simple words a user would type (e.g. "canada, professor, phd, search")
- content must have concrete, reusable steps — not generic advice
- Output ONLY the JSON, no other text."""

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

    for model in SYNTHESIS_MODELS:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": synthesis_prompt}],
                temperature=0.3,
                max_tokens=800,  # Keep output small to save tokens
            )
            raw = response.choices[0].message.content.strip()
            # Extract JSON robustly
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                data = json.loads(json_match.group(0))
                if all(k in data for k in ["skill_name", "trigger_keywords", "description", "content"]):
                    logging.info(f"[SkillLoop] Synthesized skill: {data['skill_name']}")
                    return data
        except Exception as e:
            logging.warning(f"[SkillLoop] Synthesis model {model} failed: {e}")
            continue
    return None


# ─── Save & Index ──────────────────────────────────────────────────────────────

def save_skill(skill_data: dict) -> str | None:
    """Write the skill to disk and index it in SQLite. Returns file path."""
    try:
        skill_name = re.sub(r'[^a-z0-9_]', '', skill_data["skill_name"].lower().replace(" ", "_"))
        if not skill_name:
            return None

        file_path = os.path.join(SKILLS_DIR, f"{skill_name}.md")

        # Write Markdown to disk
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(skill_data["content"])

        # Index in SQLite
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO skills_index
            (skill_name, trigger_keywords, description, file_path, use_count, created_at)
            VALUES (?, ?, ?, ?, COALESCE((SELECT use_count FROM skills_index WHERE skill_name=?), 0), ?)
        """, (
            skill_name,
            skill_data["trigger_keywords"],
            skill_data["description"],
            file_path,
            skill_name,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        conn.close()

        logging.info(f"[SkillLoop] Saved skill: {file_path}")
        return file_path
    except Exception as e:
        logging.error(f"[SkillLoop] Failed to save skill: {e}")
        return None


# ─── Skill Retrieval ───────────────────────────────────────────────────────────

def find_relevant_skill(user_query: str) -> str | None:
    """
    Fast keyword match to find the most relevant skill for a query.
    Returns the skill file content (injected into system prompt) or None.
    RAM-safe: reads one file max, then closes.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT skill_name, trigger_keywords, file_path FROM skills_index")
        skills = c.fetchall()
        conn.close()

        if not skills:
            return None

        query_words = set(user_query.lower().split())
        best_match = None
        best_score = 0

        for skill_name, trigger_keywords, file_path in skills:
            if not file_path or not os.path.exists(file_path):
                continue
            keywords = set(k.strip().lower() for k in trigger_keywords.split(","))
            score = len(query_words & keywords)
            if score > best_score:
                best_score = score
                best_match = (skill_name, file_path)

        if best_match and best_score >= 2:
            skill_name, file_path = best_match
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Increment use count
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE skills_index SET use_count = use_count + 1 WHERE skill_name = ?", (skill_name,))
            conn.commit()
            conn.close()

            logging.info(f"[SkillLoop] Injecting skill '{skill_name}' (score={best_score})")
            return f"\n\n=== RELEVANT SKILL (from past experience) ===\n{content}\n===END SKILL===\n"

    except Exception as e:
        logging.error(f"[SkillLoop] Skill retrieval failed: {e}")
    return None


# ─── Background Synthesizer (Non-Blocking) ────────────────────────────────────

def check_and_synthesize_background(user_query: str, tool_call_trace: list, final_answer: str):
    """
    Entry point: called after every response.
    Only triggers synthesis if 3+ tools were used.
    Runs in a daemon thread — never blocks the user.
    """
    if not should_synthesize(tool_call_trace):
        return

    def _run():
        try:
            skill_data = synthesize_skill(user_query, tool_call_trace, final_answer)
            if skill_data:
                save_skill(skill_data)
        except Exception as e:
            logging.error(f"[SkillLoop] Background synthesis error: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ─── List Skills (for /skills command) ────────────────────────────────────────

def list_all_skills() -> str:
    """Returns a formatted Telegram-ready list of all learned skills."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT skill_name, description, use_count, created_at FROM skills_index ORDER BY use_count DESC")
        skills = c.fetchall()
        conn.close()

        if not skills:
            return "🧠 No skills learned yet. Complete a multi-step task (3+ tools) and I'll auto-generate one!"

        lines = ["🧠 **Aurora's Learned Skills:**\n"]
        for i, (name, desc, uses, created) in enumerate(skills, 1):
            lines.append(f"{i}. **{name}** (used {uses}x)\n   _{desc}_\n   📅 {created[:10]}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Could not load skills: {e}"
