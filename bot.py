import os
import requests # For making HTTP requests to APIs
import logging # For seeing what the bot is doing
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---
# It's BEST to get these from environment variables, especially on Render
# For local testing, you can put them here temporarily, but REMOVE before committing to GitHub
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
XMR_WALLET_ADDRESS = os.environ.get("XMR_WALLET_ADDRESS", "YOUR_XMR_WALLET_ADDRESS_HERE") # Your hardcoded wallet
EXCHANGERATE_API_KEY = os.environ.get("EXCHANGERATE_API_KEY", "YOUR_EXCHANGERATE_API_KEY_HERE")

# --- Logging Setup (to see messages in Render's logs) ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Helper Functions to Get Data ---

def get_xmr_pool_stats(wallet_address):
    """Fetches mining stats from SupportXMR pool."""
    url = f"https://supportxmr.com/api/miner/{wallet_address}/stats"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status() # Raise an error for bad status codes (4xx or 5xx)
        data = response.json()
        # Extract relevant data - check SupportXMR API docs for exact fields
        hashrate = data.get("hash", 0) # Current hashrate in H/s
        workers = len(data.get("workers", [])) # Number of active workers
        pending_balance_atomic = data.get("amtDue", 0) # Balance in atomic units (piconeros)
        pending_balance_xmr = pending_balance_atomic / 1_000_000_000_000 # Convert to XMR
        return {
            "hashrate": int(hashrate), # Often comes as string
            "workers": workers,
            "pending_xmr": round(pending_balance_xmr, 8) # Round to 8 decimal places
        }
    except requests.RequestException as e:
        logger.error(f"Error fetching pool stats: {e}")
        return None
    except (KeyError, ValueError) as e: # For issues with JSON structure or conversion
        logger.error(f"Error parsing pool stats data: {e}")
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
        logger.warning("ExchangeRate API key not configured.")
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

    await context.bot.send_message(chat_id=chat_id, text="Fetching your Monero mining stats, please wait...")

    pool_stats = get_xmr_pool_stats(XMR_WALLET_ADDRESS)
    xmr_usd_price = get_xmr_to_usd_price()
    usd_ghs_rate = get_usd_to_ghs_rate(EXCHANGERATE_API_KEY)

    if not pool_stats:
        await update.message.reply_text("Sorry, I couldn't fetch your mining pool stats right now. Please try again later.")
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
    await update.message.reply_text(final_message, parse_mode='Markdown')


# --- Main Bot Setup ---
def main() -> None:
    """Start the bot."""
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE" or not TELEGRAM_BOT_TOKEN:
        logger.error("FATAL: Telegram Bot Token is not configured!")
        return
    if XMR_WALLET_ADDRESS == "YOUR_XMR_WALLET_ADDRESS_HERE" or not XMR_WALLET_ADDRESS:
        logger.error("FATAL: XMR Wallet Address is not configured!")
        return
    if EXCHANGERATE_API_KEY == "YOUR_EXCHANGERATE_API_KEY_HERE" or not EXCHANGERATE_API_KEY:
        logger.warning("ExchangeRate API Key is not configured. GHS conversion will not be available.")


    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("stats", stats_command))

    # Run the bot until the user presses Ctrl-C
    logger.info("Bot starting to poll...")
    application.run_polling()

if __name__ == "__main__":
    main()
