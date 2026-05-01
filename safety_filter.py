"""
Aurora Safety Filter — OpenClaw-style Command Sandboxing
=========================================================
Since Aurora can run shell commands on your server via run_server_command,
this module acts as a security gate that:

  1. Classifies every command as SAFE, WARN, or DANGEROUS
  2. SAFE commands execute immediately
  3. WARN commands ask for confirmation with an inline button
  4. DANGEROUS commands are BLOCKED unless you type the master passphrase

This prevents Aurora from ever accidentally (or maliciously) wiping your
server, leaking credentials, or making irreversible changes.

Dangerous pattern examples:
  - rm -rf / or rm -rf ~
  - chmod 777 or chown root
  - DROP TABLE or DELETE FROM (SQL)
  - curl | bash (code injection)
  - Any command touching .env or credentials

RAM: Zero overhead. Pure string matching — no ML, no models.
"""

import re
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# The master passphrase to override a DANGEROUS block (set in .env)
SAFETY_PASSPHRASE = os.getenv("AURORA_SAFETY_PASSPHRASE", "AURORA-OVERRIDE")

# ─── Pattern Library ──────────────────────────────────────────────────────────

# These patterns are BLOCKED unless the user types the master passphrase
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",           # rm -rf / (wipe entire filesystem)
    r"rm\s+-rf\s+~",           # rm -rf ~ (wipe home)
    r"rm\s+-rf\s+\*",          # rm -rf * (wipe current dir)
    r"rm\s+--no-preserve-root",
    r"mkfs\.",                  # format a disk
    r"dd\s+if=.*of=/dev/",     # disk overwrite
    r":(){:|:&};:",             # fork bomb
    r"chmod\s+777",            # make everything world-writable
    r"chown\s+root",           # change ownership to root
    r"curl.*\|\s*bash",        # remote code execution
    r"wget.*\|\s*bash",        # remote code execution
    r"curl.*\|\s*sh",
    r"wget.*\|\s*sh",
    r"DROP\s+TABLE",           # SQL nuke
    r"DELETE\s+FROM\s+\w+\s*;?\s*$",  # SQL delete all rows
    r"TRUNCATE\s+TABLE",
    r"\.env",                  # touching .env file
    r"credentials\.json",
    r"token\.json",
    r"id_rsa",                 # SSH private key
    r"id_ed25519",             # SSH private key
    r"Aurora_key.*\.pem",      # your server key
    r"systemctl\s+stop",       # stopping system services
    r"kill\s+-9\s+1",          # killing init process
    r"shutdown",
    r"reboot",
    r"passwd",                 # changing passwords
    r"visudo",
    r">/dev/sda",              # writing to raw disk
    r"apt\s+remove\s+python",  # removing Python (breaks the bot)
]

# These patterns require a confirmation button (not a full block)
WARN_PATTERNS = [
    r"rm\s+-r",                # recursive delete (but not -rf /)
    r"rm\s+-f",                # force delete
    r"git\s+reset\s+--hard",  # destroys local changes
    r"git\s+push\s+--force",  # force push
    r"sudo\s+apt\s+remove",   # uninstalling packages
    r"pip\s+uninstall",
    r"systemctl\s+restart",   # restarting services (usually safe but confirm)
    r"kill\s+-9",             # force-killing a process
    r"pkill",
    r"truncate",
    r"crontab\s+-r",          # deleting all cron jobs
    r"DROP\s+INDEX",
    r"ALTER\s+TABLE",
]

# ─── Classifier ───────────────────────────────────────────────────────────────

def classify_command(command: str) -> str:
    """
    Returns: 'SAFE', 'WARN', or 'DANGEROUS'
    Classification is order-dependent: DANGEROUS checked first.
    """
    cmd_lower = command.lower().strip()

    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            logging.warning(f"[SafetyFilter] DANGEROUS pattern matched: '{pattern}' in: {command[:80]}")
            return "DANGEROUS"

    for pattern in WARN_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            logging.info(f"[SafetyFilter] WARN pattern matched: '{pattern}' in: {command[:80]}")
            return "WARN"

    return "SAFE"


def is_override(user_text: str) -> bool:
    """Returns True if the user's message contains the safety override passphrase."""
    return SAFETY_PASSPHRASE.lower() in user_text.lower()


# ─── Response Generators ──────────────────────────────────────────────────────

def get_dangerous_block_message(command: str) -> str:
    return (
        f"🛑 *Safety Block Activated*\n\n"
        f"I can't run this command — it matches a DANGEROUS pattern:\n"
        f"```\n{command[:200]}\n```\n\n"
        f"This could cause irreversible damage (data loss, system corruption, credential exposure).\n\n"
        f"If you're 100% sure you want to run this, type:\n"
        f"`{SAFETY_PASSPHRASE}: {command}`\n\n"
        f"_This override is logged._"
    )


def get_warn_message(command: str) -> dict:
    """Returns the warning text and an inline keyboard for confirmation."""
    text = (
        f"⚠️ *Caution — This command needs confirmation:*\n\n"
        f"```\n{command[:200]}\n```\n\n"
        f"This is a potentially destructive operation. Confirm?"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Yes, run it", "callback_data": f"RUNCMD_{command[:100]}"},
                {"text": "❌ Cancel", "callback_data": "CANCEL_CMD"}
            ]
        ]
    }
    return {"text": text, "keyboard": keyboard}


# ─── Audit Log ────────────────────────────────────────────────────────────────

def log_command_audit(command: str, classification: str, was_overridden: bool = False):
    """Write a command audit log entry to disk."""
    try:
        timestamp = __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        override_flag = " [OVERRIDE]" if was_overridden else ""
        entry = f"[{timestamp}] [{classification}{override_flag}] {command}\n"
        with open("command_audit.log", "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logging.warning(f"[SafetyFilter] Audit log failed: {e}")


# ─── Public API ───────────────────────────────────────────────────────────────

def check_command(command: str, user_message: str = "") -> dict:
    """
    Main entry point. Call this before executing any run_server_command.

    Returns a dict:
    {
        "action": "execute" | "warn" | "block",
        "classification": "SAFE" | "WARN" | "DANGEROUS",
        "message": str  (only for warn/block actions),
        "keyboard": dict  (only for warn action)
    }
    """
    classification = classify_command(command)
    log_command_audit(command, classification)

    if classification == "SAFE":
        return {"action": "execute", "classification": "SAFE"}

    elif classification == "WARN":
        warn_data = get_warn_message(command)
        return {
            "action": "warn",
            "classification": "WARN",
            "message": warn_data["text"],
            "keyboard": warn_data["keyboard"]
        }

    else:  # DANGEROUS
        # Check for override passphrase
        if is_override(user_message):
            log_command_audit(command, classification, was_overridden=True)
            logging.warning(f"[SafetyFilter] DANGEROUS command OVERRIDDEN by user passphrase: {command[:80]}")
            return {"action": "execute", "classification": "DANGEROUS_OVERRIDE"}
        else:
            return {
                "action": "block",
                "classification": "DANGEROUS",
                "message": get_dangerous_block_message(command)
            }
