<div align="center">
  
  # 🌌 Aurora
  **Autonomous Academic Research Agent Optimized for Low-Resource Servers**
  
  [![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
  [![Memory](https://img.shields.io/badge/RAM-1GB_Optimized-success.svg)](#)
  [![AI: Multi-Agent](https://img.shields.io/badge/AI-Multi--Agent-9cf.svg)](#)
  [![Interface: Telegram](https://img.shields.io/badge/Interface-Telegram-2CA5E0.svg)](#)

  <br>

  *A proactive AI partner for deep academic research, paper synthesis, and relationship management.*

</div>

---

## ⚡ Why Aurora?

Traditional AI agents require heavy local compute or expensive subscriptions. Aurora is engineered specifically for PhD students and researchers who need a powerful, proactive partner running 24/7 on **cheap, low-resource cloud instances** (like a 1GB RAM Azure VM). 

By leveraging API-based Large Language Models instead of running heavy models locally, Aurora consumes almost zero local RAM while routing tasks to powerful API-based LLMs like Gemini Flash and OpenRouter-hosted models.

---

## ✨ Key Features

| Feature | Description |
| :--- | :--- |
| **🧠 Core Differentiator: Persistent Memory** | Aurora maintains long-term, persistent context. She remembers your name, goals, papers you've read, deadlines, and habits. Unlike ChatGPT, she never starts from zero. |
| **🔄 Multi-Model Routing** | Intelligently routes tasks to the best LLMs via OpenRouter (e.g., Hermes 405B for chat, Qwen for tools, Gemma for speed). |
| **👁️ Vision & Documents** | Native support for image analysis (Gemini Flash) and document parsing. Just send a screenshot or PDF via Telegram! |
| **📅 Deadline Tracking** | Seamlessly tracks deadlines with proactive warnings. Connects to local JSON, **Notion**, or **Google Calendar**. |
| **🔍 Deep Research** | Built-in tools to search DuckDuckGo, scrape full webpages, and query the **ArXiv academic database** for papers. |
| **💬 Live Streaming** | Provides real-time, word-by-word streaming responses in Telegram for a natural, fast conversation flow. |
| **⏱️ Proactive Briefings** | Wakes up automatically to send scheduled daily morning briefings and handles custom reminders (`/schedule_reminder`). |

---

## 🚀 Quick Start (One-Command Install)

The easiest way to install and configure Aurora is using our one-command installer. This will automatically clone the repository, set up a secure virtual environment, install all dependencies, and launch the interactive setup wizard.

**Run this in your terminal:**
```bash
curl -sL https://raw.githubusercontent.com/Muminul-Hoque/Aurora/main/install.sh | bash
```

> **Note:** The setup wizard will securely prompt you for your Telegram Bot Token and API keys. A `.env` file will be generated automatically.

---

### 🛠️ Manual Installation
If you prefer to set it up manually:

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/Muminul-Hoque/Aurora.git
   cd Aurora
   ```

2. **Run the Setup Wizard:**
   ```bash
   python setup.py
   ```

3. **Start the Agent:**
   ```bash
   python telegram_bot.py
   ```

---

## 🤖 Telegram Commands

Once running, control Aurora directly from your phone or desktop via Telegram:

*   📨 `/start` — Process the next item in your tracking sheet.
*   📊 `/stats` — Show a progress summary of your current tasks.
*   ⏳ `/pending` — List the next 10 items to be processed.
*   🔍 `/find <topic>` — Search for research topics or professors.

You can also converse naturally! Ask her to summarize a topic, or send her an image of a complex graph.

---

## ⚙️ Configuration Options

Aurora is highly customizable. Adjust these settings in your `.env` file:

*   **`AGENT_NAME` / `USER_NAME`**: Customize her persona and what she calls you.
*   **`DEADLINE_TRACKER_TYPE`**: Choose between `json` (local), `notion`, or `google_calendar`.
*   **`USER_TIMEZONE`**: Ensure highly accurate reminders (e.g., `UTC`, `America/New_York`).

<div align="center">
  <br>
  <i>Built for Researchers. Powered by Open Source.</i>
</div>
