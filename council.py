"""
Aurora Council of Agents — Multi-Agent Orchestration
=====================================================
For high-stakes tasks (interview prep, email review, research deep-dives),
Aurora can spawn two internal "Sub-Agents" that debate each other:

  ┌─────────────┐     ┌─────────────┐
  │  THE CRITIC │ vs. │  THE MENTOR │
  │ Finds flaws │     │ Builds you up│
  └─────────────┘     └─────────────┘
         ↓                   ↓
    ┌─────────────────────────┐
    │   AURORA (Synthesizer)  │
    │ Combines both into one  │
    │ balanced, honest answer │
    └─────────────────────────┘

Use cases:
  - Mock interview: Critic asks hard questions, Mentor coaches the answers
  - Email review: Critic finds weak spots, Mentor suggests improvements
  - Research: Critic challenges assumptions, Mentor maps the solution space

RAM-Optimized Design:
  - All 3 agents are API calls — no local model loading
  - Critic and Mentor run sequentially (not parallel) to avoid RAM spikes
  - Uses SPRINTER models (Gemma 12B) for Critic/Mentor, ARCHITECT for final synthesis
  - Max 3 rounds total (Critic + Mentor + Synthesizer) to keep token cost low
"""

import os
import logging
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
USER_NAME = os.getenv("USER_NAME", "Muhammed")
AGENT_NAME = os.getenv("AGENT_NAME", "Aurora")

import time

# Agent Model Assignment (all free, light-to-heavy)
CRITIC_MODELS = [
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-coder:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free"
]
MENTOR_MODELS = [
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-coder:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free"
]
SYNTHESIZER_MODELS = [
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen3-coder:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free"
]

# ─── Detect Council-Worthy Tasks ──────────────────────────────────────────────

COUNCIL_TRIGGERS = [
    "interview", "mock interview", "practice interview",
    "review my email", "check my email", "critique my",
    "review this", "is this good", "how does this sound",
    "help me prepare", "practice", "drill me",
    "what are my weaknesses", "play devil's advocate",
    "debate", "challenge me", "stress test",
]


def should_invoke_council(user_text: str) -> bool:
    """Returns True if the user's message warrants the Council of Agents."""
    text_lower = user_text.lower()
    return any(trigger in text_lower for trigger in COUNCIL_TRIGGERS)


# ─── The Critic Agent ─────────────────────────────────────────────────────────

def run_critic(task: str, context: str = "") -> str:
    """
    The Critic: Find weaknesses, gaps, and hard questions.
    For interview prep: asks the toughest questions a professor might ask.
    For email review: finds all the weak, vague, or risky parts.
    """
    if not OPENROUTER_API_KEY:
        return "Critic unavailable (no API key)."

    prompt = f"""You are The Critic — a sharp, honest academic reviewer.
Your ONLY job is to find problems, weaknesses, and gaps.
Do NOT be nice. Be honest and direct — like a tough PhD committee member.

Context about {USER_NAME}: {context[:500] if context else 'PhD applicant in Water Policy / AI research'}

Task to critique:
{task}

Output format:
**Critical Weaknesses:**
1. [Issue 1] — [Why this is a problem]
2. [Issue 2] — [Why this is a problem]
3. [Issue 3] — [Why this is a problem]

**Hardest Questions Someone Might Ask:**
- [Question 1]
- [Question 2]
- [Question 3]

Be specific. No vague feedback. Max 250 words."""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
    for model in CRITIC_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=400,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logging.warning(f"[Council/Critic] {model} failed: {e}")
            time.sleep(2)
    return "Critic could not generate a response."


# ─── The Mentor Agent ─────────────────────────────────────────────────────────

def run_mentor(task: str, critic_output: str, context: str = "") -> str:
    """
    The Mentor: Having seen the Critic's feedback, suggest concrete improvements.
    Warm but substantive. Like a supportive senior PhD student.
    """
    if not OPENROUTER_API_KEY:
        return "Mentor unavailable (no API key)."

    prompt = f"""You are The Mentor — a warm, experienced senior researcher who wants {USER_NAME} to succeed.
The Critic just identified these problems:
{critic_output}

The original task was:
{task}

Context: {context[:300] if context else 'PhD applicant in Water Policy / AI'}

Your job: Give SPECIFIC, ACTIONABLE improvements that address each criticism.
Also provide model answers to the hard questions the Critic raised.

Output format:
**How to Strengthen This:**
1. [Fix for Issue 1]
2. [Fix for Issue 2]
3. [Fix for Issue 3]

**Model Answers to the Hard Questions:**
Q: [repeat question 1]
A: [strong, concrete answer {USER_NAME} can adapt]

Q: [repeat question 2]
A: [strong, concrete answer]

Be encouraging but concrete. Max 300 words."""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
    for model in MENTOR_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=500,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logging.warning(f"[Council/Mentor] {model} failed: {e}")
            time.sleep(2)
    return "Mentor could not generate a response."


# ─── Aurora Synthesizer ───────────────────────────────────────────────────────

def run_synthesizer(task: str, critic_output: str, mentor_output: str) -> str:
    """
    Aurora herself synthesizes the Critic and Mentor into one warm, balanced response.
    She frames the debate as if she's talking to the user directly.
    """
    if not OPENROUTER_API_KEY:
        return f"Critic:\n{critic_output}\n\nMentor:\n{mentor_output}"

    prompt = f"""You are {AGENT_NAME}. You just ran your internal "Council of Agents" for {USER_NAME}.

The Critic said:
{critic_output}

The Mentor responded:
{mentor_output}

Now write ONE final, cohesive response for {USER_NAME} in your warm, direct voice.
DO NOT use section headers like "Critic:" or "Mentor:" — just talk to them naturally.
Blend both perspectives. Start with the most important point.
Keep it under 300 words. End with one specific action item they can do RIGHT NOW.

Banned words: Delve, Crucial, Tapestry, Furthermore, In conclusion."""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
    for model in SYNTHESIZER_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=400,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logging.warning(f"[Council/Synthesizer] {model} failed: {e}")
            time.sleep(2)

    # Fallback: just show both
    return f"🔍 **The Critic found:**\n{critic_output[:400]}\n\n💡 **The Mentor suggests:**\n{mentor_output[:400]}"


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def run_council(task: str, context: str = "") -> str:
    """
    Full Council run: Critic → Mentor → Aurora Synthesizer.
    Returns the final synthesized response as a Telegram-ready string.
    Total: 3 API calls, ~5-15 seconds, zero local RAM.
    """
    logging.info(f"[Council] Convening for task: {task[:80]}...")

    critic_out = run_critic(task, context)
    logging.info("[Council] Critic done.")

    mentor_out = run_mentor(task, critic_out, context)
    logging.info("[Council] Mentor done.")

    final = run_synthesizer(task, critic_out, mentor_out)
    logging.info("[Council] Synthesis done. ✅")

    return final


# ─── Reflection Loop (Pre-Response Self-Critique) ────────────────────────────
# This is the "Reflection" feature — DIFFERENT from the full Council.
# It's a lightweight internal check Aurora runs before answering:
# "Wait, is my plan actually good? What am I missing?"

REFLECTION_MODELS = [
    "google/gemma-3-12b-it:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-coder:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
]

REFLECTION_TRIGGERS = [
    "email", "draft", "professor", "phd", "application",
    "research", "deadline", "interview", "plan", "strategy",
    "how should i", "what should i", "help me", "advice",
]


def should_reflect(user_text: str) -> bool:
    """Returns True for queries that benefit from self-reflection before answering."""
    text_lower = user_text.lower()
    # Only reflect for non-trivial, task-oriented messages
    if len(user_text) < 20:
        return False
    return any(trigger in text_lower for trigger in REFLECTION_TRIGGERS)


def run_reflection(user_query: str, planned_answer_hint: str = "") -> str | None:
    """
    Pre-response reflection: Aurora asks herself "What could go wrong with my plan?"
    Returns a short correction/enhancement, or None if no improvement needed.
    This is injected into the system prompt as a "thinking note."
    """
    if not OPENROUTER_API_KEY:
        return None

    prompt = f"""You are Aurora's internal critic (hidden from the user).
The user asked: "{user_query}"

Before Aurora answers, think:
1. What information might Aurora be MISSING to give a perfect answer?
2. What assumption might Aurora make that could be WRONG?
3. Is there a BETTER approach than the obvious one?

If Aurora's plan is already solid, just say: "REFLECT: Plan is good. Proceed."
If there's a meaningful improvement, say: "REFLECT: [one specific thing to check or do differently]"

Be BRIEF — one sentence max. This is Aurora's internal thought, not the user's answer."""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
    for model in REFLECTION_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=80,  # Very short — just a hint
            )
            result = resp.choices[0].message.content.strip()
            if "plan is good" in result.lower() or "proceed" in result.lower():
                return None  # No improvement needed — silence
            return result
        except Exception as e:
            logging.warning(f"[Council/Reflection] {model} failed: {e}")
            time.sleep(2)
    return None
