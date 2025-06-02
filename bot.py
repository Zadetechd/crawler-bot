import os
import requests # For making HTTP requests to APIs
import logging # For seeing what the bot is doing
import asyncio # For the set_webhook call if done programmatically
import tracemalloc # For tracing memory allocations and getting more context on certain warnings

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---
# These will be read from environment variables set in your hosting environment.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
XMR_WALLET_ADDRESS = os.environ.get("XMR_WALLET_ADDRESS")
EXCHANGERATE_API_KEY = os.environ.get("EXCHANGERATE_API_KEY")

# --- Webhook Specific Configuration ---
# The port your web server will listen on. Hosting platforms usually set this.
PORT = int(os.environ.get("PORT", "8080")) # Default to 8080 if not set
# The public domain name your bot is accessible at (e.g., "your-bot.onrender.com")
# Do NOT include https:// or the path here.
WEBHOOK_DOMAIN = os.environ.get("WEBHOOK_DOMAIN")

# --- Enable tracemalloc (as early as possible) ---
tracemalloc.start()


# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# Reduce default logging level for httpx and telegram.vendor.ptb_urllib3 to WARNING
# to avoid overly verbose logs from the underlying HTTP client in python-telegram-bot
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.vendor.ptb_urllib3.urllib3.connectionpool").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Helper Functions to Get Data ---

def get_xmr_pool_stats(wallet_address):
    """Fetches mining stats from SupportXMR pool."""
    url = f"https://supportxmr.com/api/miner/{wallet_address}/stats"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        hashrate = data.get("hash", 0)
        workers = len(data.get("workers", []))
        pending_balance_atomic = data.get("amtDue", 0)
        pending_balance_xmr = pending_balance_atomic / 1_000_000_000_000
        return {
            "hashrate": int(hashrate) if str(hashrate).isdigit() else 0,
            "workers": workers,
            "pending_xmr": round(pending_balance_xmr, 8)
        }
    except requests.RequestException as e:
        logger.error(f"Error fetching pool stats: {e}")
        return None
    except (KeyError, ValueError, TypeError) as e: # Added TypeError
        logger.error(f"Error parsing pool stats data: {e} - Data: {response.text if 'response' in locals() else 'N/A'}")
        return None

def get_xmr_to_usd_price():
    """Fetches XMR to USD price from CoinGecko."""
    url = "https://api.coingecko.com/api/v3/simple/price?ids=monero&vs_currencies=usd"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("monero", {}).get("usd")
    except requests.RequestException as e:
        logger.error(f"Error fetching XMR price: {e}")
        return None
    except (KeyError, ValueError) as e:
        logger.error(f"Error parsing XMR price data: {e}")
        return None

def get_usd_to_ghs_rate(api_key):
    """Fetches USD to GHS exchange rate."""
    if not api_key or api_key == "YOUR_EXCHANGERATE_API_KEY_HERE":
        logger.warning("ExchangeRate API key not configured or is placeholder.")
        return None
    url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/USD"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("conversion_rates", {}).get("GHS")
    except requests.RequestException as e:
        logger.error(f"Error fetching GHS exchange rate: {e}")
        return None
    except (KeyError, ValueError) as e:
        logger.error(f"Error parsing GHS exchange rate data: {e}")
        return None

# --- Telegram Command Handler ---

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends mining stats when the /stats command is issued."""
    chat_id = update.effective_chat.id
    logger.info(f"Received /stats command from chat_id: {chat_id}")

    processing_message = await context.bot.send_message(chat_id=chat_id, text="Fetching your Monero mining stats, please wait...")

    pool_stats = get_xmr_pool_stats(XMR_WALLET_ADDRESS)
    xmr_usd_price = get_xmr_to_usd_price()
    usd_ghs_rate = get_usd_to_ghs_rate(EXCHANGERATE_API_KEY)

    if not pool_stats:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text="Sorry, I couldn't fetch your mining pool stats right now. Please try again later."
        )
        return

    message_parts = [
        f"⛏️ **Monero Mining Stats for ...{XMR_WALLET_ADDRESS[-6:]}** ⛏️",
        f"------------------------------------",
        f"Workers Online: {pool_stats['workers']}",
        f"Current Hashrate: {pool_stats['hashrate']} H/s",
        f"Pending Balance: {pool_stats['pending_xmr']:.8f} XMR"
    ]

    if xmr_usd_price:
        pending_usd = pool_stats['pending_xmr'] * xmr_usd_price
        message_parts.append(f"Value (USD): ${pending_usd:.2f}")

        if usd_ghs_rate:
            pending_ghs = pending_usd * usd_ghs_rate
            message_parts.append(f"Value (GHS): GH₵ {pending_ghs:.2f}")
        else:
            message_parts.append("Could not fetch GHS exchange rate to show value in Cedis.")
    else:
        message_parts.append("Could not fetch XMR price to show value in fiat.")

    message_parts.append("------------------------------------")
    message_parts.append("Data from SupportXMR & CoinGecko.")

    final_message = "\n".join(message_parts)
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=processing_message.message_id,
        text=final_message,
        parse_mode='Markdown'
    )

# --- Function to set the webhook ---
async def set_bot_webhook(application: Application, webhook_full_url: str):
    """Sets the bot's webhook with Telegram."""
    logger.info(f"Attempting to set webhook to: {webhook_full_url}")
    try:
        await application.bot.set_webhook(url=webhook_full_url, allowed_updates=Update.ALL_TYPES)
        logger.info(f"Webhook successfully set to {webhook_full_url}")
        webhook_info = await application.bot.get_webhook_info()
        logger.info(f"Current webhook info: {webhook_info}")
        if webhook_info.url != webhook_full_url:
            logger.warning(f"Webhook URL mismatch! Expected {webhook_full_url}, got {webhook_info.url}")
    except Exception as e:
        logger.error(f"Error setting webhook: {e}", exc_info=True) # Added exc_info for more detail

# --- Main Bot Setup ---
async def main() -> None:
    """Start the bot with webhooks."""
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("FATAL: Telegram Bot Token (TELEGRAM_BOT_TOKEN) is not configured!")
        return
    if not XMR_WALLET_ADDRESS:
        logger.critical("FATAL: XMR Wallet Address (XMR_WALLET_ADDRESS) is not configured!")
        return
    if not WEBHOOK_DOMAIN:
        logger.critical("FATAL: Webhook domain (WEBHOOK_DOMAIN) is not configured! This is needed to construct the webhook URL.")
        return
    if not EXCHANGERATE_API_KEY or EXCHANGERATE_API_KEY == "YOUR_EXCHANGERATE_API_KEY_HERE":
        logger.warning("ExchangeRate API Key (EXCHANGERATE_API_KEY) is not configured or is placeholder. GHS conversion will not be available.")

    url_path = TELEGRAM_BOT_TOKEN
    webhook_full_url = f"https://{WEBHOOK_DOMAIN.rstrip('/')}/{url_path}"

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("stats", stats_command))

    initialized_successfully = False
    try:
        logger.info("Attempting to initialize Telegram application...")
        await application.initialize()  # Explicitly initialize and await
        initialized_successfully = True
        logger.info("Telegram application initialized successfully.")
    except Exception as e:
        logger.critical(f"CRITICAL: Error during application.initialize(): {e}", exc_info=True)
        return # Stop if initialization fails

    if not initialized_successfully: # Should not be reached if the above return executes
        logger.error("Skipping webhook setup and server start due to initialization failure.")
        return

    await set_bot_webhook(application, webhook_full_url)

    try:
        logger.info(f"Attempting to start webhook server on 0.0.0.0:{PORT} with path /{url_path}")
        logger.info(f"Bot configured to listen for updates at: {webhook_full_url}")
        await application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=url_path,
            webhook_url=webhook_full_url,
        )
        logger.info("application.run_webhook has finished (e.g., due to a signal).")
    except SystemExit:
        logger.info("SystemExit caught, likely from PTB's signal handling during run_webhook. Preparing to shutdown.")
        # This allows the finally block to execute for cleanup.
    except Exception as e:
        logger.critical(f"CRITICAL: Error during application.run_webhook: {e}", exc_info=True)
    finally:
        logger.info("Entering finally block after run_webhook attempt.")
        # Check if the application was initialized and if it might have been started
        if initialized_successfully: # Ensure we only try to shutdown an initialized app
            # hasattr check is good practice before accessing application.running
            if hasattr(application, 'running') and application.running:
                logger.info("Application is marked as running, attempting graceful shutdown...")
            else:
                # If not 'running', it might have failed before self.start() in run_webhook,
                # or run_webhook exited cleanly. Still, try shutdown if initialized.
                logger.info("Application not marked as 'running' but was initialized. Attempting shutdown.")
            try:
                await application.shutdown()
                logger.info("Application shutdown() completed.")
            except Exception as e_shutdown:
                logger.error(f"Error during application.shutdown(): {e_shutdown}", exc_info=True)
        else:
            logger.info("Application was not initialized successfully; skipping shutdown.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt).")
    except Exception as e:
        # This catches exceptions that might escape main() if not handled there,
        # or if asyncio.run() itself has an issue.
        logger.critical(f"Bot crashed with unhandled exception in top level: {e}", exc_info=True)

