import os

def print_header(title):
    print("\n" + "="*50)
    print(f" {title}")
    print("="*50)

def main():
    print_header("Aurora AI Agent - Initial Setup")
    print("Welcome! This interactive script will configure your AI assistant.")
    print("Don't worry if you don't have all keys right now. You can edit the '.env' file later.\n")

    env_vars = {}

    # 1. Telegram
    print_header("1. Telegram Setup")
    print("Get this from @BotFather on Telegram.")
    env_vars["TELEGRAM_BOT_TOKEN"] = input("Enter TELEGRAM_BOT_TOKEN: ").strip()
    print("\nSend a message to @userinfobot to get your Chat ID.")
    env_vars["TELEGRAM_CHAT_ID"] = input("Enter TELEGRAM_CHAT_ID: ").strip()

    # 2. AI APIs
    print_header("2. AI API Keys")
    print("OpenRouter provides access to models like Hermes and Qwen (free tier available).")
    env_vars["OPENROUTER_API_KEY"] = input("Enter OPENROUTER_API_KEY: ").strip()
    print("\nGoogle Gemini API is used for processing images (vision).")
    env_vars["GEMINI_API_KEY"] = input("Enter GEMINI_API_KEY: ").strip()
    print("\nGroq API is used for fast voice note transcription.")
    env_vars["GROQ_API_KEY"] = input("Enter GROQ_API_KEY: ").strip()

    # 3. Persona Settings
    print_header("3. Persona Settings")
    agent_name = input("What would you like to name your agent? [Default: Aurora]: ").strip()
    env_vars["AGENT_NAME"] = agent_name if agent_name else "Aurora"
    
    user_name = input("What is your name? [Default: User]: ").strip()
    env_vars["USER_NAME"] = user_name if user_name else "User"

    timezone = input("What is your timezone? (e.g., UTC+6, America/New_York) [Default: UTC]: ").strip()
    env_vars["USER_TIMEZONE"] = timezone if timezone else "UTC"

    # 4. Deadlines
    print_header("4. Deadline Tracker Setup")
    print("How would you like the bot to track your deadlines?")
    print("  1) json (Simple local file - Recommended for beginners)")
    print("  2) google_calendar (Google Calendar integration)")
    print("  3) notion (Notion database integration)")
    print("  4) none (Skip deadline tracking)")
    
    choice = input("\nEnter choice (1-4) [Default: 1]: ").strip()
    tracker_type = "json"
    if choice == "2":
        tracker_type = "google_calendar"
    elif choice == "3":
        tracker_type = "notion"
    elif choice == "4":
        tracker_type = "none"
        
    env_vars["DEADLINE_TRACKER_TYPE"] = tracker_type

    if tracker_type == "notion":
        print("\nNotion Setup:")
        env_vars["NOTION_API_KEY"] = input("Enter NOTION_API_KEY: ").strip()
        env_vars["NOTION_DATABASE_ID"] = input("Enter NOTION_DATABASE_ID: ").strip()
    elif tracker_type == "google_calendar":
        print("\nGoogle Calendar Setup:")
        env_vars["GOOGLE_CALENDAR_CREDENTIALS_PATH"] = input("Enter path to credentials.json [Default: credentials.json]: ").strip() or "credentials.json"

    # 5. Gmail
    print_header("5. Gmail SMTP Setup (Optional)")
    print("Used for sending automated cold emails.")
    env_vars["GMAIL_USER"] = input("Enter GMAIL_USER (your email): ").strip()
    env_vars["GMAIL_APP_PASSWORD"] = input("Enter GMAIL_APP_PASSWORD: ").strip()

    # Write to .env
    print_header("Saving Configuration")
    
    with open(".env", "w", encoding="utf-8") as f:
        for key, value in env_vars.items():
            f.write(f'{key}="{value}"\n')
            
    print("✅ Configuration saved to .env file successfully!")
    print("You can now start the bot using: python telegram_bot.py")

if __name__ == "__main__":
    main()
