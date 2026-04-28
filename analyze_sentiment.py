import csv
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CSV_FILE = 'tracker.csv'

# ─── Model Groups ──────────────────────────────────────────────────────────────
# Sprinter: Gemma 12B — fast, cheap, great for single-turn classification tasks.
# We don't need a 405B model to classify a reply as Positive/Negative.
SPRINTER_MODELS = [
    "google/gemma-3-12b-it:free",
    "google/gemma-3-27b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]


def classify_with_llm(response_text: str, openai_client) -> str:
    """
    Use a Sprinter (Gemma 12B) model to classify a contact's reply.
    Returns: 'Positive', 'Negative', or 'Neutral'
    Catches nuanced soft rejections that keyword matching misses entirely.
    """
    prompt = f"""You are classifying an email reply from a contact into one of three categories.

Categories:
- Positive: Contact is interested, wants to meet, or is open to discussion.
- Negative: Contact is rejecting (even politely), has no availability, or redirecting elsewhere.
- Neutral: No reply, auto-reply, generic acknowledgement, or unclear intent.

IMPORTANT: Detect SOFT REJECTIONS. Phrases like "I have a full group at the moment",
"unfortunately not taking students this cycle", or "I wish you the best in your search"
are NEGATIVE even if polite.

Reply to classify:
---
{response_text[:1500]}
---

Respond with ONLY ONE WORD: Positive, Negative, or Neutral."""

    for model in SPRINTER_MODELS:
        try:
            completion = openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=5,
            )
            result = completion.choices[0].message.content.strip().capitalize()
            if result in ("Positive", "Negative", "Neutral"):
                logging.info(f"[sentiment] '{result}' via {model}")
                return result
        except Exception as e:
            logging.warning(f"[sentiment] Sprinter model {model} failed: {e}")
            continue

    return None  # Signal to fall back to keyword matching


def keyword_classify(response: str) -> str:
    """Fallback keyword-based classifier used when LLM is unavailable."""
    POSITIVE_KEYWORDS = [
        'interview', 'zoom', 'chat', 'meeting', 'encourage', 'apply', 'opening',
        'funding', 'vacancy', 'impressive', 'strong candidate', 'interested',
        'discuss', 'skype', 'call', 'fit your background'
    ]
    NEGATIVE_KEYWORDS = [
        'full', 'no openings', 'not taking', 'not accepting', 'no funding',
        'not a good fit', 'best of luck elsewhere', 'cannot accept',
        'retirement', 'leaving', 'position filled', 'already hired',
        'full group', 'not recruiting', 'unfortunately'
    ]
    is_positive = any(kw in response for kw in POSITIVE_KEYWORDS)
    is_negative = any(kw in response for kw in NEGATIVE_KEYWORDS)

    if is_positive and not is_negative:
        return 'Positive'
    elif is_negative:
        return 'Negative'
    return 'Neutral'


def analyze_sentiment(use_llm: bool = True):
    if not os.path.exists(CSV_FILE):
        print("CSV not found.")
        return

    openai_client = None
    if use_llm:
        try:
            from dotenv import load_dotenv
            from openai import OpenAI
            load_dotenv()
            api_key = os.getenv("OPENROUTER_API_KEY")
            if api_key:
                openai_client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=api_key,
                )
                logging.info("[sentiment] LLM mode: ON (Gemma 12B / Sprinter)")
            else:
                logging.warning("[sentiment] OPENROUTER_API_KEY not set. Falling back to keywords.")
        except ImportError:
            logging.warning("[sentiment] openai package not installed. Falling back to keywords.")

    rows = []
    headers = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames)
        if 'Sentiment' not in headers:
            headers.append('Sentiment')
        rows = list(reader)

    positive_count = 0
    negative_count = 0
    llm_count = 0
    keyword_count = 0

    for row in rows:
        response = str(row.get('Response', '')).lower().strip()
        if not response or response in ('', '[] ...', 'none', 'n/a'):
            row['Sentiment'] = 'Neutral'
            continue

        sentiment = None

        if openai_client:
            sentiment = classify_with_llm(response, openai_client)
            if sentiment:
                llm_count += 1

        if sentiment is None:
            sentiment = keyword_classify(response)
            keyword_count += 1

        row['Sentiment'] = sentiment
        if sentiment == 'Positive':
            positive_count += 1
        elif sentiment == 'Negative':
            negative_count += 1

    with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ Sentiment Analysis Complete!")
    print(f"   🟢 Positive:  {positive_count}")
    print(f"   🔴 Negative:  {negative_count}")
    print(f"   ⚪ Neutral:   {len(rows) - positive_count - negative_count}")
    print(f"   🤖 LLM classified:     {llm_count}")
    print(f"   🔑 Keyword classified: {keyword_count}")

    import subprocess
    subprocess.run(["python", "sync_dashboard.py"])


if __name__ == "__main__":
    analyze_sentiment(use_llm=True)
