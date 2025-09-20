import subprocess
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

# ---------------- LOAD ENV VARIABLES ----------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID", "0"))
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

# ---------------- PATHS ----------------
WORKING_DIR = os.getenv("WORKING_DIR", "/opt/render/project/src")
SCRIPT_PATH = os.path.join(WORKING_DIR, "sizet2.py")

# ---------------- TELEGRAM HANDLERS ----------------
async def trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /run command"""
    user_id = update.effective_user.id
    if user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("Unauthorized user!")
        print("Unauthorized attempt blocked.")
        return

    await update.message.reply_text("Trigger received! Running sizet2.py...")
    print(f"Launching sizet2.py for user {user_id}...")

    # Pass API keys to environment
    env = os.environ.copy()
    env["BINANCE_API_KEY"] = BINANCE_API_KEY
    env["BINANCE_API_SECRET"] = BINANCE_API_SECRET

    # Launch sizet2.py as a separate process
    try:
        subprocess.Popen(
            ["python", SCRIPT_PATH],
            cwd=WORKING_DIR,
            env=env,
            shell=False
        )
        print("sizet2.py launched successfully.")
    except Exception as e:
        await update.message.reply_text(f"Error launching sizet2.py: {e}")
        print("Error launching sizet2.py:", e)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command"""
    await update.message.reply_text("Bot is running. Send /run to execute sizet2.py.")
    print(f"/start received from user {update.effective_user.id}")

# ---------------- MAIN ----------------
def main():
    if not BOT_TOKEN or not BINANCE_API_KEY or not BINANCE_API_SECRET:
        print("[ERROR] Missing environment variables. Please check .env")
        return

    # Build application (v20+ async API)
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("run", trigger))

    print("Telegram trigger bot is running (Python 3.13 compatible)...")
    app.run_polling()

if __name__ == "__main__":
    main()
