# Aurora: Autonomous Personal AI Agent

Aurora is a robust, multi-backend AI assistant and Academic Relationship Manager designed to run continuously on **extremely low-resource servers (like a 1GB RAM Azure VM)**. By leveraging API-based Large Language Models (like Hermes 405B and Gemini Flash) instead of running heavy models locally, Aurora consumes almost zero local RAM while providing state-of-the-art intelligence. She operates via Telegram, acting as a proactive partner for tasks like deep academic research, synthesizing papers, deadline tracking, and preparing highly personalized, context-aware correspondence.

## ✨ Key Features

- **🧠 Multi-Model Architecture**: Intelligently routes tasks to the best free/open-source LLMs using OpenRouter (e.g., Hermes 405B for personality/chat, Qwen for tool usage, Gemma for quick tasks).
- **👁️ Vision & Documents**: Native support for image analysis (via Gemini Flash) and document parsing. Just send a screenshot or PDF via Telegram!
- **📅 Advanced Deadline Tracking**: Seamlessly tracks deadlines and provides proactive warnings. Configurable backends include local JSON, Notion, or Google Calendar.
- **✉️ Context-Aware Correspondence prep**: Synthesizes a professor's recent publications to help you draft deeply personalized, highly specific outreach. This is designed for quality and deep alignment, not bulk sending.
- **🔍 Research & Discovery**: Built-in tools to search the web (DuckDuckGo), read full webpage contents, and query the ArXiv academic database for research papers.
- **⏱️ Proactive Briefings & Reminders**: Scheduled daily morning briefings and a built-in reminder system (`/schedule_reminder`).
- **💬 Streaming Responses**: Provides real-time, word-by-word streaming responses in Telegram for a natural conversation flow.
- **🔒 Privacy First**: Your API keys and data remain entirely under your control.

## 🚀 Quick Start (Installation)

We have provided a streamlined setup script specifically designed for non-technical users to get Aurora running quickly.

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd <your-repo-directory>
```

### 2. Run the Setup Wizard
The setup script will guide you through installing dependencies, configuring your API keys, and setting up the Telegram Bot.

```bash
python setup.py
```
*Note: The script will prompt you for your Telegram Bot Token, OpenRouter API Key, and optional keys (Gemini for Vision, Notion for Deadlines, etc.). It will automatically create a `.env` file for you.*

### 3. Start the Bot
Once setup is complete, you can start the bot manually:
```bash
python telegram_bot.py
```
*Or, use the provided `aurora-agent.service` file to run it continuously as a systemd service.*

## 🤖 Core Commands (Telegram Menu)

Once the bot is running, you can interact with it on Telegram using these core commands:

- 📨 `/start` — Process the next item in your tracking sheet.
- 📊 `/stats` — Show a progress summary of your current tasks/outreach.
- ⏳ `/pending` — List the next 10 items to be processed.
- 🔍 `/find <topic>` — Search for research topics, professors, or general information.

You can also converse naturally! Send her an image, a PDF, or just ask her to summarize a topic.

## 📂 Configuration Options

Aurora is highly configurable. You can adjust the following settings in your generated `.env` file:

- **AGENT_NAME / USER_NAME**: Customize the bot's persona and your preferred name.
- **DEADLINE_TRACKER_TYPE**: Choose between `json` (local), `notion`, or `google_calendar`.
- **USER_TIMEZONE**: Ensure accurate reminders (e.g., `UTC`, `America/New_York`).

## 📜 License

This project is open-source. Feel free to fork, modify, and deploy your own personal assistant!
