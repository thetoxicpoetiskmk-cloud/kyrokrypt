import subprocess
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

# ---------------- LOAD ENV VARIABLES ----------------
# Load environment variables from .env file
load_dotenv()  # pip install python-dotenv

BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID"))
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET")
PROXY_URL = os.environ.get("PROXY_URL")  # Optional

# Paths
SCRIPT_PATH = "sizet2.py"  # Relative path in repo (Render uses repo folder as working dir)
# ---------------------------------------------------

async def trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /run command"""
    user_id = update.effective_user.id
    if user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("Unauthorized user!")
        print("Unauthorized attempt blocked.")
        return

    await update.message.reply_text("Trigger received! Running sizet2.py...")
    print(f"Launching sizet2.py for user {user_id}...")

    # Prepare environment with API keys
    env = os.environ.copy()
    env["BINANCE_API_KEY"] = BINANCE_API_KEY
    env["BINANCE_API_SECRET"] = BINANCE_API_SECRET

    # Optional: include proxy if set
    if PROXY_URL:
        env["PROXY_URL"] = PROXY_URL

    # Launch sizet2.py exactly like original code
    try:
        subprocess.Popen(
            ["python", SCRIPT_PATH],
            cwd=os.getcwd(),  # current working directory (repo root)
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
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("run", trigger))

print("Telegram trigger bot is running...")
app.run_polling()