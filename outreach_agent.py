import os
import json
import logging
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    print("Warning: OPENROUTER_API_KEY is not set. Emails cannot be drafted.")

openai_client = None
if OPENROUTER_API_KEY:
    openai_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

# ─── Model Groups ─────────────────────────────────────────────────────────────────
# Architect: Hermes 405B first — best at human-like, persuasive academic tone
# Email drafting is the HIGHEST-STAKES task. Never use a coder model here.
ARCHITECT_MODELS = [
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "openai/gpt-oss-120b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]


def load_skill_prompt(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Warning: Could not load {filepath} - {e}")
        return ""


COLD_EMAIL_SKILL = load_skill_prompt("cold-email-professor_SKILL.md")


def fetch_web_content(url):
    import httpx
    try:
        if not url.startswith("http"):
            url = "http://" + url
        jina_url = f"https://r.jina.ai/{url}"
        print(f"Fetching live content from: {jina_url}")
        response = httpx.get(jina_url, timeout=20.0)
        if response.status_code == 200:
            return response.text[:10000] # Return max 10k chars to avoid token limit
    except Exception as e:
        print(f"Jina fetch failed for {url}: {e}")
    return None


def draft_email(prof_name, prof_email, university, interests, lab_url=None):
    """
    Drafts a personalized cold email using the new google-genai SDK.
    Returns a dict with 'Subject' and 'Body' keys.
    """
    website_content = ""
    hallucination_rules = """🚨 CRITICAL ANTI-HALLUCINATION RULES FOR THIS AUTOMATED RUN 🚨:
You DO NOT have internet access to verify papers. Therefore, you MUST NOT cite, name, or invent any specific paper titles, conferences, or publication years. 
Instead of praising a specific paper, you MUST praise their general research direction based ONLY on the "Research Interests" provided below. 
Example of what NOT to do: "I read your paper 'Dense X Retrieval'..." (This is a hallucination).
Example of what TO DO: "I have been following your work in retrieval-augmented generation and context representation..."
"""

    if lab_url and str(lab_url).strip():
        content = fetch_web_content(str(lab_url).strip())
        if content:
            website_content = f"\n\n=== REAL LIVE WEBSITE CONTENT FETCHED FOR THIS PROFESSOR ===\n{content}\n============================================================\n"
            hallucination_rules = """✅ LIVE WEBSITE CONTENT FETCHED ✅
I have successfully fetched the professor's live website content (provided below). 
You MUST read this content and find 2 specific, recent papers authored by this professor.
If you find real papers in the content below, you MAY cite them following the strict rules in the skill file.
If you do NOT find specific papers in the content below, you MUST fall back to praising their general Research Interests and MUST NOT hallucinate any paper titles."""

    system_instruction = f"""You are an autonomous AI outreach agent acting on behalf of the applicant.
Your task is to draft a highly personalized, natural, and compelling cold email to a professor for a PhD/MSc/RA position.

Here is the core profile and the general guidelines:
---
{COLD_EMAIL_SKILL}
---

{hallucination_rules}

IMPORTANT INSTRUCTIONS:
1. Output ONLY a raw JSON object with two keys: "Subject" and "Body". No markdown, no code blocks.
2. Make sure the body has proper paragraph breaks using \\n.
3. Ensure all facts about the applicant are 100% accurate based on the skill file.
4. 🚨 CLAUDE SCHOLAR ANTI-AI HUMANIZATION RULES 🚨:
   - Do NOT use robotic, cliché AI phrases.
   - BANNED WORDS: "Delve", "Crucial", "Tapestry", "Testament", "Embark", "Furthermore", "In conclusion", "It's important to note", "Navigating the landscape", "Fostering", "Realm", "Nuanced".
   - BANNED PHRASES: "I hope this email finds you well" (Replace with something natural like "I hope you are having a good week").
   - Tone: Direct, academic but natural. Do not be overly enthusiastic or sycophantic. Talk like a real, competent human PhD applicant. Keep sentences varied in length and avoid repetitive structures.
"""

    user_message = f"""Professor Name: {prof_name}
University: {university}
Email: {prof_email}
Research Interests: {interests}
Lab/Website: {lab_url if lab_url else 'Not provided'}
{website_content}

Please output ONLY a valid JSON object like this:
{{
    "Subject": "Prospective PhD Student — Interest in [specific topic]",
    "Body": "Dear Professor {prof_name},\\n\\nI hope this email finds you well...\\n\\nSincerely,\\nMuhammed Muminul Hoque"
}}
Do not include markdown blocks like ```json. Just raw JSON."""

    try:
        if not openai_client:
            print("Error: openai_client is not initialized.")
            return None

        # Use ARCHITECT_MODELS — Hermes 405B is the best free model for human-like
        # academic writing. We never use a coder model for professor outreach emails.
        response_text = None
        last_err = None
        for model in ARCHITECT_MODELS:
            try:
                completion = openai_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.7,
                )
                response_text = completion.choices[0].message.content.strip()
                logging.info(f"[draft_email] Success with Architect model: {model}")
                break
            except Exception as e:
                last_err = e
                logging.warning(f"[draft_email] Architect model {model} failed: {e}")
                continue
                
        if not response_text:
            print(f"Error: All Architect models failed. Last error: {last_err}")
            return None

        response_text = response_text.strip()
        
        # Robust JSON extraction using regex
        import re
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            json_str = json_match.group(0)
            email_data = json.loads(json_str)
            return email_data
        else:
            print(f"Error: No JSON found in response. Raw response: {response_text}")
            return None

    except Exception as e:
        print(f"Error drafting email for {prof_name}: {e}")
        return None
