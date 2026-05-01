<div align="center">

# 🌌 Aurora
**Autonomous Academic Research Framework for Low-Resource Servers**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![RAM: 1GB Optimized](https://img.shields.io/badge/RAM-1GB_Optimized-success.svg)](https://github.com/Muminul-Hoque/Aurora/blob/main/create_swap.sh)
[![Architecture: Agentic](https://img.shields.io/badge/Architecture-Agentic-9cf.svg)](#-agentic-architecture)
[![Interface: Telegram](https://img.shields.io/badge/Interface-Telegram-2CA5E0.svg)](#-telegram-commands)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](#-license)

*An autonomous AI framework combining AutoGPT-style background workers, OpenClaw persistence, and Hermes self-learning—designed specifically for PhD students and researchers running on cheap cloud VMs.*

</div>

---

## ⚡ Why Aurora?

Traditional AI assistants require expensive subscriptions or heavy local hardware. Aurora is built for researchers who want a powerful, always-on AI companion running on **low-resource cloud instances** (tested on a 1GB RAM Azure VM).

By routing all inference to API-based LLMs via OpenRouter and Gemini, Aurora consumes almost zero local RAM while delivering state-of-the-art autonomous capabilities.

---

## 🤖 Agentic Architecture

Aurora is not a simple chatbot; she is a complete **Agentic Framework** utilizing patterns from the most advanced open-source AI projects:

*   **AutoGPT Background Workers:** Delegate massive, multi-step tasks (e.g., "Research 50 papers on X"). Aurora spawns an independent, non-blocking asynchronous worker thread to complete the task over several minutes.
*   **Hermes-Style Skill Engine:** Aurora learns from her mistakes. If a tool call fails, she analyzes the failure and writes a permanent Markdown "skill" to her local directory so she never makes the same mistake twice.
*   **Nightly Memory Distillation:** To solve LLM amnesia, Aurora runs a 3 AM scheduled job that compresses raw daily chat logs into a persistent, structured "Truth Summary."
*   **Council of Agents:** For high-stakes queries (e.g., reviewing an academic email), Aurora spawns a **Critic** and a **Mentor** to debate internally before presenting you with a synthesized response.
*   **OpenClaw Proactive Heartbeat:** A lightweight script runs every 5 minutes scanning your upcoming deadlines, habits, and outreach pace. She will proactively message you if (and only if) action is required.
*   **Command Sandboxing:** Aurora can execute real bash commands on your server, protected by a strict Regex-based Safety Filter that blocks dangerous patterns (`rm -rf`, `DROP TABLE`) without a master passphrase.

---

## ✨ Core Capabilities

| Feature | Description |
| :--- | :--- |
| **🧠 Multi-Model Routing** | Routes tasks to the best-fit free LLM via OpenRouter. 5 specialized model groups: Architect, Engineer, Scout, Scholar, Sprinter. |
| **⚙️ Self-Scripting** | If a task requires complex data processing or math, Aurora can write and execute her own Python scripts on the fly. |
| **👁️ Vision & Images** | Send a screenshot, graph, or photo via Telegram — Gemini Flash analyzes it instantly. |
| **📅 Deadline Tracking** | Tracks deadlines with proactive warnings. Connects to local JSON, **Notion**, or **Google Calendar**. |
| **🔍 Deep Research** | Searches DuckDuckGo, scrapes full webpages via Jina Reader, and queries the **ArXiv API** for academic papers. |
| **📧 Professor Outreach** | Drafts personalized cold emails to academic supervisors from a CSV tracker. Supports send-now or schedule-for-8AM. |
| **🖥️ Server Monitoring** | Ask Aurora about your VM's RAM, disk, or running processes — she runs real bash commands and reports back. |
| **🔒 Single-User Auth** | Locked to your Telegram Chat ID — no one else can interact with your instance. |

---

## 🧠 Multi-Model Routing

Aurora uses task-specific model groups, each with automatic failover to prevent rate-limit crashes:

| Group | Best For | Primary Model |
|---|---|---|
| **Architect** | Email drafting, reasoning, persona | Hermes 3 405B |
| **Engineer** | Tool calls, JSON tasks, server commands | Qwen3 Coder |
| **Scout** | Professor discovery, broad world knowledge | GPT-OSS 120B |
| **Scholar** | Paper summaries, research interest extraction | Nemotron 120B |
| **Sprinter** | Fast single-turn tasks, sentiment, status | Gemma 3 27B |

All models are **free-tier via OpenRouter** — no paid API required for core functionality.

---

## 🚀 Quick Start (One-Command Install)

> ⚠️ **Security note:** Only run install scripts from repositories you trust and have reviewed.

```bash
curl -sL https://raw.githubusercontent.com/Muminul-Hoque/Aurora/main/install.sh | bash
```

The installer clones the repo, creates a virtual environment, installs dependencies, and launches the interactive setup wizard. A `.env` file is generated automatically.

---

### 🛠️ Manual Installation

```bash
# 1. Clone
git clone https://github.com/Muminul-Hoque/Aurora.git
cd Aurora

# 2. Run setup wizard
python setup.py

# 3. Start the bot
python telegram_bot.py
```

For 1GB RAM servers, run the swap script first:

```bash
bash create_swap.sh
```

---

## 🤖 Telegram Commands

| Command | What it does |
|---|---|
| `/start` | Welcome message and status overview |
| `/stats` | Outreach progress summary (emails sent, pending, scheduled) |
| `/pending` | List the next 10 professors in the outreach queue |
| `/find <topic>` | Discover professors by research area |
| `/schedule_reminder <time> <message>` | Set a custom reminder |
| `/distill` | Force a manual memory consolidation |
| `/help` | Show all available commands |

You can also chat naturally — ask Aurora to run a background task, summarize an ArXiv paper, analyze an image, or check your RAM.

---

## ⚙️ Configuration

Set these in your `.env` file (generated by the setup wizard):

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your personal chat ID (locks the bot to you) |
| `OPENROUTER_API_KEY` | For multi-model LLM routing (free tier available) |
| `GEMINI_API_KEY` | For vision, image analysis, and semantic memory embeddings |
| `AGENT_NAME` / `USER_NAME` | Customize Aurora's name and what she calls you |
| `AURORA_SAFETY_PASSPHRASE` | Master password to override the Bash Safety Filter |
| `DEADLINE_TRACKER_TYPE` | `json` (local), `notion`, or `google_calendar` |

---

## 📁 Project Structure

```
Aurora/
├── telegram_bot.py       # Main bot — all commands, memory, tool routing
├── background_worker.py  # AutoGPT-style long-running research agent
├── council.py            # Multi-agent debate orchestrator (Critic/Mentor)
├── heartbeat.py          # Proactive 5-minute intelligence scanner
├── memory_distiller.py   # Nightly memory consolidation (3 AM)
├── safety_filter.py      # Bash command sandboxing and security
├── skill_loop.py         # Autonomous skill generation engine
├── agent.py              # Cold email drafting with anti-hallucination rules
├── email_sender.py       # Gmail SMTP email sending with attachments
├── sync_gmail.py         # Automated inbox syncing for replies
├── aurora-agent.service  # Systemd service file for 24/7 deployment
├── create_swap.sh        # Swap memory script for 1GB RAM servers
├── setup.py              # Interactive setup wizard
├── install.sh            # One-command installer
├── requirements.txt      # Python dependencies
└── .env.example          # Environment variable template
```

---

## 📦 Dependencies

Core stack — no LangChain, no local models:

```
python-telegram-bot>=20.0
openai                      # Used as OpenRouter client
google-generativeai         # Gemini Flash vision + embeddings
apscheduler                 # Proactive scheduling
duckduckgo-search           # Web search
beautifulsoup4              # Web scraping
httpx                       # Async HTTP (Jina Reader, ArXiv API)
```

---

## 🚢 24/7 Deployment (Linux)

Use the included systemd service to keep Aurora running after reboots:

```bash
sudo cp aurora-agent.service /etc/systemd/system/
sudo systemctl enable aurora-agent
sudo systemctl start aurora-agent
```

---

## 📄 License

This project is licensed under the **GNU AGPL v3** License. 

You are free to use, modify, and distribute this software for personal, academic, and open-source projects. However, if you use this code in a commercial product or service, you **must** open-source your entire project under the same AGPL v3 license.

## 🤝 Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 🌟 Support the Project

If you found this repository helpful, please consider **starring** it! It helps others find the project and motivates further development. 

[![Star on GitHub](https://img.shields.io/github/stars/Muminul-Hoque/Aurora?style=social)](https://github.com/Muminul-Hoque/Aurora/stargazers)

---

<div align="center">
  <i>Built for Researchers. Powered by Open Source.</i>
</div>
