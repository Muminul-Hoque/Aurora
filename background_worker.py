"""
Aurora Background Worker — AutoGPT-Style Long-Running Tasks
==========================================================
Spawns an independent agent loop to handle complex, multi-step 
research goals that would otherwise time out the main Telegram bot.
Max 15 iterations per task to prevent infinite loops.
"""

import os
import json
import httpx
import logging
import asyncio
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Use a fallback list of strong instruction models to handle 429 rate limits
WORKER_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "qwen/qwen3-coder:free"
]

# ─── Stateless Research Tools ──────────────────────────────────────────────────

async def search_web(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        def _search():
            with DDGS() as ddgs:
                results = ""
                for item in ddgs.text(query, max_results=5):
                    results += f"Title: {item.get('title')}\nURL: {item.get('href')}\nSnippet: {item.get('body')}\n\n"
                return results if results else "No results found."
        return await asyncio.to_thread(_search)
    except Exception as e:
        return f"Web search error: {e}"

async def fetch_webpage(url: str) -> str:
    try:
        if not url.startswith("http"): url = "http://" + url
        jina_url = f"https://r.jina.ai/{url}"
        async with httpx.AsyncClient() as client:
            response = await client.get(jina_url, timeout=20.0)
            if response.status_code == 200:
                return response.text[:8000]
            return f"Fetch failed: Status {response.status_code}"
    except Exception as e:
        return f"Fetch error: {e}"

async def search_arxiv(query: str) -> str:
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

def execute_python_script(code: str) -> str:
    import tempfile
    import subprocess
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as tmp:
            tmp.write(code)
            tmp_name = tmp.name
        result = subprocess.check_output(f"python3 {tmp_name}", shell=True, text=True, stderr=subprocess.STDOUT, timeout=15)
        os.remove(tmp_name)
        return f"✅ Execution Success:\n```\n{result}\n```"
    except Exception as e:
        if 'tmp_name' in locals(): os.remove(tmp_name)
        return f"❌ Execution Error:\n```\n{str(e)}\n```"

# ─── Worker Definition ────────────────────────────────────────────────────────

WORKER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Searches the internet for a given query.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Fetches and reads the full markdown content of a single specific URL.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_arxiv",
            "description": "Searches the ArXiv database for academic papers.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python_script",
            "description": "Writes and executes a Python script to solve complex data or math tasks.",
            "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "finish_task",
            "description": "Call this ONLY when you have fully completed the background goal. Provide a comprehensive markdown report summarizing your findings.",
            "parameters": {"type": "object", "properties": {"final_report": {"type": "string"}}, "required": ["final_report"]}
        }
    }
]

# ─── Main Executor ────────────────────────────────────────────────────────────

async def send_status(chat_id: str, text: str):
    """Sends a non-blocking Telegram message."""
    if not TELEGRAM_TOKEN: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload)
    except Exception as e:
        logging.error(f"[Worker] Status update failed: {e}")

async def run_background_agent(goal: str, chat_id: str):
    """
    Executes an autonomous loop to achieve the given goal.
    Max 15 iterations.
    """
    await send_status(chat_id, f"⚙️ **Background Worker Spawned**\n_Goal:_ {goal}\n_Please wait, this may take a few minutes..._")
    
    if not OPENROUTER_API_KEY:
        await send_status(chat_id, "❌ Error: Missing OPENROUTER_API_KEY.")
        return

    system_prompt = (
        "You are an autonomous background research agent. Your job is to completely resolve the user's complex goal.\n"
        "You must break the problem down, search for information, read pages, and synthesize the results.\n"
        "Think step-by-step. Use tools repeatedly until you are confident you have the full answer.\n"
        "When you are finished, you MUST call `finish_task` with your final, comprehensive report."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Here is your goal: {goal}"}
    ]

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
    
    max_steps = 15
    for step in range(max_steps):
        try:
            response = None
            last_err = None
            for model in WORKER_MODELS:
                try:
                    # We run the synchronous OpenRouter call in a thread to not block the event loop
                    response = await asyncio.to_thread(
                        client.chat.completions.create,
                        model=model,
                        messages=messages,
                        tools=WORKER_TOOLS,
                        temperature=0.5
                    )
                    break  # Success
                except Exception as e:
                    logging.warning(f"[Worker] Model {model} failed: {e}")
                    last_err = e
                    continue
                    
            if not response:
                raise Exception(f"All models failed due to rate limits. Last error: {last_err}")
            
            msg = response.choices[0].message
            
            # Convert to dict for appending to context
            msg_dict = {"role": msg.role, "content": msg.content or ""}
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {"id": t.id, "type": "function", "function": {"name": t.function.name, "arguments": t.function.arguments}}
                    for t in msg.tool_calls
                ]
            messages.append(msg_dict)
            
            if not msg.tool_calls:
                # LLM spoke without calling a tool. Force it to continue or finish.
                messages.append({"role": "user", "content": "Please continue working or call finish_task if you are completely done."})
                continue
                
            # Process tool calls
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                tool_output = ""
                
                if func_name == "finish_task":
                    final_report = args.get("final_report", "No report generated.")
                    await send_status(chat_id, f"✅ **Background Task Complete!**\n\n{final_report}")
                    return # Exit successfully
                    
                # Execute research tool
                await send_status(chat_id, f"🔍 _Worker is running:_ `{func_name}`")
                
                if func_name == "search_web":
                    tool_output = await search_web(args.get("query", ""))
                elif func_name == "fetch_webpage":
                    tool_output = await fetch_webpage(args.get("url", ""))
                elif func_name == "search_arxiv":
                    tool_output = await search_arxiv(args.get("query", ""))
                elif func_name == "execute_python_script":
                    tool_output = execute_python_script(args.get("code", ""))
                else:
                    tool_output = f"Unknown tool: {func_name}"
                    
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": tool_output
                })

        except Exception as e:
            logging.error(f"[Worker] Step {step} failed: {e}")
            await send_status(chat_id, f"❌ **Background Worker Error:** {str(e)}")
            return
            
    # If we exit the loop, we hit the step limit
    await send_status(chat_id, "⚠️ **Background Worker Stopped:** Reached maximum step limit (15) without calling finish_task. The task might be too broad.")
