"""
Volo Drop-In Watcher — Telegram Bot
------------------------------------
Commands (from your phone):
  /watch   — start checking every 5 minutes
  /stop    — stop checking
  /check   — run a one-time check right now
  /status  — show whether the watcher is active

Setup:
  1. Message @BotFather on Telegram → /newbot → follow prompts → copy the token
  2. Start a chat with your new bot, send any message, then run:
       python3 volo_bot.py --get-chat-id
     to print your chat ID.
  3. Set environment variables (or create a .env file):
       TELEGRAM_TOKEN=your_token
       TELEGRAM_CHAT_ID=your_chat_id
  4. pip install -r requirements.txt
  5. python3 volo_bot.py
"""

import asyncio
import json
import logging
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path

import requests as http_requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from volo_client import fetch_drop_in_games, format_game

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "state.json"

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)


# ── Config from environment variables ─────────────────────────────────────────

def load_config() -> dict:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    sports_raw = os.environ.get("VOLO_SPORTS", "Soccer")
    city = os.environ.get("VOLO_CITY", "Washington DC")
    min_spots = int(os.environ.get("VOLO_MIN_MALE_SPOTS", "1"))
    interval = int(os.environ.get("CHECK_INTERVAL_SECONDS", "300"))

    if not token:
        raise ValueError("Missing TELEGRAM_TOKEN environment variable.")
    if not chat_id:
        raise ValueError("Missing TELEGRAM_CHAT_ID environment variable.")

    return {
        "telegram_token": token,
        "chat_id": chat_id,
        "check_interval_seconds": interval,
        "sports": [s.strip() for s in sports_raw.split(",")],
        "city": city,
        "min_male_spots": min_spots,
    }


# ── State (seen game IDs + active flag) ────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_games": {}, "watching": False}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Core check logic ───────────────────────────────────────────────────────────

async def run_check(context: ContextTypes.DEFAULT_TYPE):
    """Called by the JobQueue every N seconds. Sends alerts for new games."""
    config = context.bot_data["config"]
    state = load_state()

    if not state.get("watching"):
        return

    try:
        games = fetch_drop_in_games(
            sports=config["sports"],
            city=config["city"],
            min_male_spots=config["min_male_spots"],
        )
    except Exception as e:
        logger.error(f"Error fetching games: {e}")
        return

    seen = state.get("seen_games", {})  # game_id -> last alerted spot count
    new_games = []
    for g in games:
        gid = g["game_id"]
        current_spots = g.get("game", {}).get("drop_in_capacity", {}).get("total_available_spots", 0)
        last_spots = seen.get(gid, 0)
        if gid not in seen or current_spots > last_spots:
            new_games.append(g)

    if new_games:
        lines = []
        for i, game in enumerate(new_games, 1):
            gid = game["game_id"]
            current_spots = game.get("game", {}).get("drop_in_capacity", {}).get("total_available_spots", 0)
            lines.append(format_game(game))
            seen[gid] = current_spots

        message = "\n".join(lines)
        await context.bot.send_message(
            chat_id=config["chat_id"],
            text=message,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        state["seen_games"] = seen
        save_state(state)
        logger.info(f"Sent alert for {len(new_games)} game(s).")
    else:
        logger.info("Check complete — no new games.")


# ── Bot command handlers ────────────────────────────────────────────────────────

async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = context.bot_data["config"]
    if str(update.effective_chat.id) != str(config["chat_id"]):
        return

    state = load_state()
    if state.get("watching"):
        await update.message.reply_text("👀 Already watching! Use /stop to pause.")
        return

    state["watching"] = True
    save_state(state)

    interval = config["check_interval_seconds"]
    await update.message.reply_text(
        f"✅ Watching started! I'll check every {interval // 60} min and notify you of new drop-in slots.\n"
        f"Sports: {', '.join(config['sports'])} | City: {config['city']}\n\n"
        "Use /stop to pause."
    )
    logger.info("Watching started via /watch command.")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = context.bot_data["config"]
    if str(update.effective_chat.id) != str(config["chat_id"]):
        return

    state = load_state()
    state["watching"] = False
    save_state(state)
    await update.message.reply_text("⏸️ Watching paused. Send /watch to resume.")
    logger.info("Watching stopped via /stop command.")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = context.bot_data["config"]
    if str(update.effective_chat.id) != str(config["chat_id"]):
        return

    await update.message.reply_text("🔍 Running a one-time check now...")
    try:
        games = fetch_drop_in_games(
            sports=config["sports"],
            city=config["city"],
            min_male_spots=config["min_male_spots"],
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return

    if not games:
        await update.message.reply_text("No drop-in games currently available.")
        return

    lines = []
    for i, game in enumerate(games, 1):
        lines.append(format_game(game))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config = context.bot_data["config"]
    if str(update.effective_chat.id) != str(config["chat_id"]):
        return

    state = load_state()
    watching = state.get("watching", False)
    seen_count = len(state.get("seen_games", {}))
    interval = config["check_interval_seconds"]
    status = "✅ Active" if watching else "⏸️ Paused"

    await update.message.reply_text(
        f"*Volo Watcher Status*\n"
        f"Status: {status}\n"
        f"Check interval: every {interval // 60} min\n"
        f"Sports: {', '.join(config['sports'])}\n"
        f"City: {config['city']}\n"
        f"Games already notified: {seen_count}",
        parse_mode="Markdown",
    )


# ── Helper: get chat ID ────────────────────────────────────────────────────────

def get_chat_id(token: str):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    resp = http_requests.get(url)
    data = resp.json()
    results = data.get("result", [])
    if not results:
        print("No messages found. Send any message to your bot first, then re-run.")
        return
    for update in results[-3:]:
        msg = update.get("message", {})
        chat = msg.get("chat", {})
        print(f"Chat ID: {chat.get('id')}  |  From: {chat.get('first_name')} {chat.get('last_name', '')}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--get-chat-id",
        action="store_true",
        help="Print the chat ID from recent bot messages and exit.",
    )
    args = parser.parse_args()

    if args.get_chat_id:
        token = os.environ.get("TELEGRAM_TOKEN", "")
        if not token:
            print("Set TELEGRAM_TOKEN in your environment or .env file first.")
            return
        get_chat_id(token)
        return

    config = load_config()

    app = Application.builder().token(config["telegram_token"]).build()
    app.bot_data["config"] = config

    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("status", cmd_status))

    interval = config["check_interval_seconds"]
    app.job_queue.run_repeating(run_check, interval=interval, first=10)

    logger.info(f"Bot started. Checking every {interval // 60} min when watching is active.")
    logger.info("Send /watch from your phone to begin.")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.run_polling()


if __name__ == "__main__":
    main()
