import os
import re
import queue
import logging
import threading
import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler

# Configure logging
logger = logging.getLogger(__name__)

# Global variables
download_queue = None
active_downloads = None
queue_lock = None
db = None
TELEGRAM_BOT_TOKEN = None
FREEPIK_URL_PATTERN = None
MAX_QUEUE_SIZE = None
BANK_DETAILS = {}
ADMIN_CHAT_IDS = []

# Conversation states
MAIN_MENU, SERVICE_MENU, FREEPIK_MENU, SUBSCRIPTION_MENU, AWAITING_PAYMENT, AWAITING_LICENSE_CONFIRM = range(6)

# Callback data identifiers
FREEPIK_SERVICE = "service_freepik"
ENVATO_SERVICE = "service_envato"
STORYBLOCKS_SERVICE = "service_storyblocks"
FREEPIK_DOWNLOADS = "freepik_downloads"
FREEPIK_SEND_URL = "freepik_send_url"
FREEPIK_INFO = "freepik_info"
SUBSCRIPTION_INFO = "subscription_info"
SUBSCRIPTION_PLANS = "subscription_plans"
FREEPIK_MONTHLY = "freepik_monthly"
FREEPIK_YEARLY = "freepik_yearly"
BACK_MAIN_MENU = "back_main_menu"
BACK_SERVICE = "back_service"
BACK_FREEPIK = "back_freepik"
LICENSE_YES = "license_yes"
LICENSE_NO = "license_no"

def init_bot(token, url_pattern, max_queue_size=10, queue=None, active_downloads_dict=None, lock=None, database=None, bank_details=None, admin_chat_ids=None):
    """Initialize the bot's global variables."""
    global TELEGRAM_BOT_TOKEN, FREEPIK_URL_PATTERN, MAX_QUEUE_SIZE
    global download_queue, active_downloads, queue_lock, db, BANK_DETAILS, ADMIN_CHAT_IDS
    
    TELEGRAM_BOT_TOKEN = token
    FREEPIK_URL_PATTERN = url_pattern
    MAX_QUEUE_SIZE = max_queue_size
    BANK_DETAILS = bank_details or {}
    ADMIN_CHAT_IDS = admin_chat_ids or []
    
    # Use provided resources if available
    if queue is not None:
        download_queue = queue
    else:
        download_queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        
    if active_downloads_dict is not None:
        active_downloads = active_downloads_dict
    else:
        active_downloads = {}
        
    if lock is not None:
        queue_lock = lock
    else:
        queue_lock = threading.Lock()
        
    if database is not None:
        db = database
    
    return download_queue, active_downloads, queue_lock

async def setup_commands(bot):
    """Set up command menu buttons for the bot."""
    logger.info("Setting up command menu buttons...")
    commands = [
        BotCommand("start", "Start or restart the bot"),
        BotCommand("info", "View your account information"),
        BotCommand("freepik", "Download Freepik resources"),
        BotCommand("subscriptions", "Manage your subscriptions"),
        BotCommand("status", "Check download status"),
        BotCommand("help", "Get help with using the bot")
    ]
    await bot.set_my_commands(commands)
    logger.info("Command menu buttons set up successfully")

# Then call this in your run_bot function:
async def run_bot(token):
    """Start the bot with improved error handling."""
    try:
        # Create the Application and pass it your bot's token
        application = Application.builder().token(token).build()

        # Set up handlers
        setup_bot_handlers(application)
        
        # Set up command menu buttons
        await setup_commands(application.bot)
        
        # Start the Bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
        return application
    except Exception as e:
        logger.critical(f"Failed to start bot: {e}")
        # Re-raise to ensure the error is visible
        raise

# --------------------------------
# Telegram Bot Command Handlers
# --------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the /start command and show welcome message with user ID."""
    user = update.effective_user
    user_id = user.id
    
    # Register or update user in the database with enhanced information
    if db:
        try:
            user_info = db.create_or_update_user(
                user_id=user_id, 
                username=user.username, 
                name=user.full_name,
                first_name=user.first_name,
                last_name=user.last_name,
                telegram_info={
                    "is_premium": getattr(user, "is_premium", False),
                    "language_code": getattr(user, "language_code", None)
                }
            )
            logger.info(f"User registered/updated in database: {user_id}")
        except Exception as e:
            logger.error(f"Error registering user in database: {e}")
    
    # Send welcome message with user ID
    await update.message.reply_text(
        f"👋 Welcome to the Premium Asset Downloader, {user.first_name}!\n\n"
        f"Your User ID: {user_id}\n\n"
        f"This bot helps you download premium resources from various platforms.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Continue →", callback_data="continue_to_menu")]
        ])
    )
    
    return MAIN_MENU

async def continue_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the main menu."""
    query = update.callback_query
    await query.answer()
    
    # Show main menu options
    await query.edit_message_text(
        "🌟 *Main Menu* 🌟\n\n"
        "Choose an option below:",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("ℹ️ My Info", callback_data="my_info")],
            [InlineKeyboardButton("🌐 Freepik", callback_data=FREEPIK_SERVICE)],
            [InlineKeyboardButton("🔄 Envato Elements", callback_data=ENVATO_SERVICE)],
            [InlineKeyboardButton("🎬 Storyblocks", callback_data=STORYBLOCKS_SERVICE)],
            [InlineKeyboardButton("💳 Subscriptions", callback_data=SUBSCRIPTION_INFO)],
            [InlineKeyboardButton("❓ Help", callback_data="help")]
        ])
    )
    
    return MAIN_MENU

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "🔍 *How to use this bot:*\n\n"
        "1. Choose a service from the main menu (e.g., Freepik)\n"
        "2. Send a URL from that service\n"
        "3. Wait for your download to complete\n"
        "4. I'll send you the file!\n\n"
        "📊 *Subscription Plans:*\n"
        "• Freepik Monthly: LKR 1,500 (10 files/day)\n"
        "• Freepik Yearly: LKR 5,800 (10 files/day)\n\n"
        "Available commands:\n"
        "/start - Open main menu\n"
        "/help - Show this help message\n"
        "/status - Check your download status\n"
        "/queue - View the current download queue\n"
        "/subscriptions - Manage your subscriptions",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
        ])
    )

async def subscriptions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the /subscriptions command."""
    user_id = update.effective_user.id
    
    # Get user subscriptions from database
    subscriptions = []
    if db:
        subscriptions = db.get_all_user_subscriptions(user_id)
    
    # Show subscription info
    text = "💳 *Your Subscriptions*\n\n"
    
    if subscriptions:
        for sub in subscriptions:
            service = sub['service'].capitalize()
            plan = sub['plan'].capitalize()
            status = sub['status'].capitalize()
            end_date = sub['end_date'].strftime("%Y-%m-%d")
            
            text += f"*{service} - {plan}*\n"
            text += f"Status: {status}\n"
            text += f"Expires: {end_date}\n\n"
    else:
        text += "You don't have any active subscriptions yet.\n\n"
    
    text += "Check available plans below:"
    
    await update.message.reply_text(
        text,
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("View Available Plans", callback_data=SUBSCRIPTION_PLANS)],
            [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
        ])
    )
    
    return SUBSCRIPTION_MENU

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check status of user's download."""
    user_id = update.effective_user.id
    
    with queue_lock:
        # Check if user has an active download
        if user_id in active_downloads:
            status = active_downloads[user_id]
            await update.message.reply_text(
                f"🔄 Your download is in progress!\n\n"
                f"Current status: {status}\n\n"
                f"I'll send you the file as soon as it's ready.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                ])
            )
        else:
            # Check if user is in queue
            position = 0
            for i in range(download_queue.qsize()):
                try:
                    item = download_queue.queue[i]
                    if item[0] == user_id:
                        position = i + 1
                        break
                except:
                    pass
            
            if position > 0:
                est_time = position * 2  # Rough estimate: 2 minutes per download
                await update.message.reply_text(
                    f"⏳ You're in the queue!\n\n"
                    f"Position: {position} of {download_queue.qsize()}\n"
                    f"Estimated wait time: ~{est_time} minutes\n\n"
                    f"I'll notify you when your download starts.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                    ])
                )
            else:
                await update.message.reply_text(
                    "📭 You don't have any active downloads.\n\n"
                    "Go to the main menu to start downloading!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                    ])
                )

async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the current download queue."""
    with queue_lock:
        queue_size = download_queue.qsize()
        
        if queue_size == 0:
            await update.message.reply_text(
                "✅ The download queue is currently empty!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                ])
            )
        else:
            await update.message.reply_text(
                f"👥 Current download queue: {queue_size} items\n\n"
                f"Estimated processing time: ~{queue_size * 2} minutes\n\n"
                f"Use /status to check your position in the queue.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                ])
            )

async def my_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show user information and subscription details."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user info and subscriptions from database
    user_info = None
    subscriptions = []
    download_stats = {}
    payment_history = []  # Add payment history
    
    if db:
        user_info = db.get_user(user_id)
        subscriptions = db.get_all_user_subscriptions(user_id)
        
        # Get download stats for Freepik
        freepik_limit = db.get_download_limit(user_id, "freepik")
        if freepik_limit:
            download_stats["freepik"] = {
                "today": freepik_limit["count"],
                "limit": freepik_limit["limit"]
            }
            
        # Get recent payment history
        try:
            payment_history = db.get_user_payments(user_id, limit=3)
        except Exception as e:
            logger.error(f"Error getting payment history: {e}")
    
    # Format subscriptions info
    subscription_text = ""
    if subscriptions:
        active_subscriptions = [s for s in subscriptions if s["status"] == "active"]
        
        if active_subscriptions:
            subscription_text = "\n\n*Active Subscriptions:*\n"
            for sub in active_subscriptions:
                service = sub["service"].capitalize()
                plan = sub["plan"].capitalize()
                end_date = sub["end_date"].strftime("%Y-%m-%d")
                subscription_text += f"• {service} {plan} (Expires: {end_date})\n"
        else:
            subscription_text = "\n\n*No active subscriptions*"
    else:
        subscription_text = "\n\n*No subscriptions found*"
    
    # Format download stats
    stats_text = "\n\n*Download Stats (Today):*\n"
    if "freepik" in download_stats:
        stats_text += f"• Freepik: {download_stats['freepik']['today']}/{download_stats['freepik']['limit']} downloads\n"
    else:
        stats_text += "• No stats available\n"
    
    # Format payment history
    payment_text = ""
    if payment_history:
        payment_text = "\n\n*Recent Payments:*\n"
        for payment in payment_history:
            service = payment.get("service", "Unknown").capitalize()
            plan = payment.get("plan", "Unknown").capitalize()
            amount = payment.get("amount", 0)
            currency = payment.get("currency", "LKR")
            status = payment.get("status", "pending").capitalize()
            date = payment.get("payment_date", datetime.datetime.utcnow()).strftime("%Y-%m-%d")
            
            payment_text += f"• {service} {plan}: {currency} {amount} - {status} ({date})\n"
    
    # Registration date
    reg_date = "Unknown"
    if user_info and "registration_date" in user_info:
        reg_date = user_info["registration_date"].strftime("%Y-%m-%d")
    
    await query.edit_message_text(
        f"📋 *User Information*\n\n"
        f"*User ID:* {user_id}\n"
        f"*Username:* {query.from_user.username or 'Not set'}\n"
        f"*Name:* {query.from_user.full_name}\n"
        f"*Registered:* {reg_date}"
        f"{subscription_text}"
        f"{stats_text}"
        f"{payment_text}"
        f"\n\nDownload limits are reset daily at 00:00 UTC.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Manage Subscriptions", callback_data=SUBSCRIPTION_INFO)],
            [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
        ])
    )
    
    return MAIN_MENU

async def handle_service_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle service selection from main menu."""
    query = update.callback_query
    await query.answer()
    
    # Store selected service in context
    service = query.data
    context.user_data["selected_service"] = service
    
    if service == FREEPIK_SERVICE:
        return await show_freepik_menu(update, context)
    elif service in [ENVATO_SERVICE, STORYBLOCKS_SERVICE]:
        # For services that are not yet available
        service_name = "Envato Elements" if service == ENVATO_SERVICE else "Storyblocks"
        await query.edit_message_text(
            f"🚧 *{service_name} Coming Soon!* 🚧\n\n"
            f"We're working hard to integrate {service_name} downloads.\n"
            f"Please check back later!",
            parse_mode=constants.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
            ])
        )
        return MAIN_MENU
    
    return MAIN_MENU

async def show_freepik_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show Freepik service menu with absolutely no formatting to avoid entity issues."""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Check subscription status
    subscription = None
    limit_info = {"count": 0, "limit": 0}
    
    if db:
        subscription = db.get_active_subscription(user_id, "freepik")
        
        # Add debugging code for subscription check
        is_valid, reason = db.debug_subscription_status(user_id, "freepik")
        logger.info(f"Subscription check: valid={is_valid}, reason={reason}")
        
        limit_info = db.get_download_limit(user_id, "freepik")
    
    # Determine subscription status text - with NO FORMATTING at all
    if subscription:
        plan_name = subscription["plan"].capitalize()
        end_date = subscription["end_date"].strftime("%Y-%m-%d")
        sub_text = f"✅ Active Subscription: {plan_name}\n"
        sub_text += f"Expires: {end_date}\n"
        sub_text += f"Daily Limit: {limit_info['count']}/{limit_info['limit']} downloads used today\n\n"
    else:
        sub_text = "❌ No Active Subscription\n"
        sub_text += "You need a subscription to download resources.\n\n"
    
    try:
        # Answer the callback query first
        await query.answer()
        
        # Send a completely new message instead of editing
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🌐 Freepik Downloads\n\n{sub_text}What would you like to do?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Send Freepik URL", callback_data=FREEPIK_SEND_URL)],
                [InlineKeyboardButton("📋 My Downloads", callback_data=FREEPIK_DOWNLOADS)],
                [InlineKeyboardButton("💳 Get Subscription", callback_data=SUBSCRIPTION_PLANS)],
                [InlineKeyboardButton("ℹ️ About Freepik", callback_data=FREEPIK_INFO)],
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=BACK_MAIN_MENU)]
            ])
        )
    except Exception as e:
        logger.error(f"Error in show_freepik_menu: {e}")
        try:
            # Fallback approach - just send a minimal message
            await context.bot.send_message(
                chat_id=user_id,
                text="Freepik Downloads - Select an option:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 Send Freepik URL", callback_data=FREEPIK_SEND_URL)],
                    [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                ])
            )
        except Exception as e2:
            logger.error(f"Second approach also failed: {e2}")
    
    return FREEPIK_MENU

async def show_freepik_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show information about Freepik service."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "*About Freepik Downloads*\n\n"
        "Freepik is a popular platform for graphic resources, including:\n"
        "• Vector graphics\n"
        "• Stock photos\n"
        "• PSD files\n"
        "• Icons and illustrations\n\n"
        "*How to use:*\n"
        "1. Find a resource you like on Freepik\n"
        "2. Copy the URL\n"
        "3. Send it to this bot\n"
        "4. Receive your downloaded file\n\n"
        "*Subscription Details:*\n"
        "• Monthly: LKR 1,500 (10 downloads/day)\n"
        "• Yearly: LKR 5,800 (10 downloads/day)\n\n"
        "Limits reset daily at 00:00 UTC.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
        ])
    )
    
    return FREEPIK_MENU

async def show_user_downloads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show user's recent downloads."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    today = datetime.datetime.utcnow().date()
    
    # Get user downloads from database
    downloads = []
    if db:
        # Get today's downloads
        downloads = db.get_user_downloads_for_date(user_id, "freepik", today)
    
    # Format downloads info
    text = "📥 *Your Freepik Downloads Today*\n\n"
    
    if downloads:
        for i, download in enumerate(downloads, 1):
            file_name = download.get("file_name", "Unknown file")
            file_size_mb = download.get("file_size", 0) / (1024 * 1024)
            download_time = download.get("download_date", datetime.datetime.utcnow()).strftime("%H:%M:%S")
            
            text += f"{i}. {file_name}\n"
            text += f"   Size: {file_size_mb:.2f} MB\n"
            text += f"   Time: {download_time}\n\n"
    else:
        text += "You haven't downloaded any Freepik resources today.\n\n"
    
    # Add limit information
    limit_info = {"count": 0, "limit": 0}
    if db:
        limit_info = db.get_download_limit(user_id, "freepik")
    
    text += f"*Usage:* {limit_info['count']}/{limit_info['limit']} downloads\n"
    text += f"*Resets:* Daily at 00:00 UTC"
    
    await query.edit_message_text(
        text,
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
        ])
    )
    
    return FREEPIK_MENU

async def prompt_for_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user to send a Freepik URL with simplified workflow."""
    query = update.callback_query
    
    # Just answer the callback without trying to edit the message
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    # Check if user has active subscription
    has_subscription = False
    can_download = False
    limit_info = {"count": 0, "limit": 0}
    
    if db:
        subscription = db.get_active_subscription(user_id, "freepik")
        
        # Add debugging code for subscription check
        is_valid, reason = db.debug_subscription_status(user_id, "freepik")
        logger.info(f"Subscription check in prompt_for_url: valid={is_valid}, reason={reason}")
        
        has_subscription = subscription is not None
        can_download = db.can_download(user_id, "freepik")
        limit_info = db.get_download_limit(user_id, "freepik")
    
    # Send a new message without editing original message
    if not has_subscription:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ No Active Subscription\n\nYou need a subscription to download Freepik resources.\nPlease purchase a subscription to continue.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Get Subscription", callback_data=SUBSCRIPTION_PLANS)],
                [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
            ])
        )
        return FREEPIK_MENU
    
    if not can_download:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Daily Limit Reached\n\nYou've used {limit_info['count']}/{limit_info['limit']} downloads today.\nYour limit will reset at 00:00 UTC.\n\nPlease try again tomorrow.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
            ])
        )
        return FREEPIK_MENU
    
    # Send a plain text message without any special formatting
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📤 Please paste your Freepik URL below\n\nExample: https://www.freepik.com/premium-photo/example_12345.htm\n\nYou have used {limit_info['count']}/{limit_info['limit']} downloads today.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Cancel", callback_data=BACK_FREEPIK)]
        ])
    )
    
    # Set state to expect URL
    context.user_data["awaiting_url"] = True
    
    return FREEPIK_MENU

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Freepik URLs sent by users."""
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Check if we're expecting a URL from this user
    if not context.user_data.get("awaiting_url", False):
        await update.message.reply_text(
            "Please use the menu buttons to navigate the bot. If you want to download a Freepik resource, select that option from the menu.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Go to Main Menu", callback_data=BACK_MAIN_MENU)]
            ])
        )
        return MAIN_MENU
    
    # Reset the awaiting URL flag
    context.user_data["awaiting_url"] = False
    
    # Check if the message contains a valid Freepik URL
    if not re.search(FREEPIK_URL_PATTERN, message_text):
        await update.message.reply_text(
            "❌ That doesn't look like a valid Freepik URL.\n\n"
            "Please send a link like this:\n"
            "https://www.freepik.com/premium-photo/example_12345.htm",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Try Again", callback_data=FREEPIK_SEND_URL)],
                [InlineKeyboardButton("Back to Freepik Menu", callback_data=BACK_FREEPIK)]
            ])
        )
        return FREEPIK_MENU
    
    # Extract the complete URL including query parameters and fragments
    url_match = re.search(FREEPIK_URL_PATTERN, message_text)
    freepik_url = url_match.group(0)
    
    # If we're missing query parameters or hash fragments that exist in the original text, append them
    # This ensures we catch any parameters after the pattern match
    if '#' in message_text and '#' not in freepik_url:
        fragment = message_text.split('#', 1)[1]
        freepik_url = f"{freepik_url}#{fragment}"
    
    if '?' in message_text and '?' not in freepik_url:
        query = message_text.split('?', 1)[1]
        freepik_url = f"{freepik_url}?{query}"
        
    logger.info(f"Extracted complete URL: {freepik_url}")
    
    # Store the URL in the context for later use
    context.user_data["freepik_url"] = freepik_url
    
    # Check subscription and limit again before adding to queue
    has_subscription = False
    can_download = False
    
    if db:
        subscription = db.get_active_subscription(user_id, "freepik")
        
        # Add debugging for subscription check
        is_valid, reason = db.debug_subscription_status(user_id, "freepik")
        logger.info(f"Subscription check in handle_url: valid={is_valid}, reason={reason}")
        
        has_subscription = subscription is not None
        can_download = db.can_download(user_id, "freepik")
    
    if not has_subscription:
        await update.message.reply_text(
            "❌ No Active Subscription\n\n"
            "You need a subscription to download Freepik resources.\n"
            "Please purchase a subscription to continue.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Get Subscription", callback_data=SUBSCRIPTION_PLANS)],
                [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
            ])
        )
        return FREEPIK_MENU
    
    if not can_download:
        limit_info = db.get_download_limit(user_id, "freepik")
        await update.message.reply_text(
            "⚠️ Daily Limit Reached\n\n"
            f"You've used {limit_info['count']}/{limit_info['limit']} downloads today.\n"
            "Your limit will reset at 00:00 UTC.\n\n"
            "Please try again tomorrow.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
            ])
        )
        return FREEPIK_MENU
    
    # Check if user already has a download in progress
    with queue_lock:
        if user_id in active_downloads:
            await update.message.reply_text(
                "⚠️ You already have a download in progress!\n\n"
                "Please wait for it to complete before requesting another download.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Check Status", callback_data="check_status")],
                    [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
                ])
            )
            return FREEPIK_MENU
        
        # Check if user is already in queue
        for i in range(download_queue.qsize()):
            try:
                if download_queue.queue[i][0] == user_id:
                    await update.message.reply_text(
                        "⚠️ You already have a download in the queue!\n\n"
                        f"Use /status to check your position.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Check Status", callback_data="check_status")],
                            [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
                        ])
                    )
                    return FREEPIK_MENU
            except:
                pass
    
        # Try to add to queue
        try:
            download_queue.put_nowait((user_id, update.effective_chat.id, freepik_url, update.message.message_id))
            queue_position = download_queue.qsize()
            est_time = queue_position * 2  # Rough estimate: 2 minutes per download
            
            # Send processing message without markdown formatting
            processing_message = await update.message.reply_text(
                "⏳ Processing Your Download\n\n"
                f"URL: {freepik_url}\n\n"
                "Please wait while I download this resource for you..."
            )
            
            # Store the processing message ID in context
            context.user_data["processing_message_id"] = processing_message.message_id
            
            # Increment download count in database
            if db:
                db.increment_download_count(user_id, "freepik")
            
            # Update queue position message - no markdown
            await update.message.reply_text(
                f"✅ Your download request has been added to the queue!\n\n"
                f"URL: {freepik_url}\n"
                f"Queue position: {queue_position}\n"
                f"Estimated wait time: ~{est_time} minutes\n\n"
                f"I'll notify you when your download is complete.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
                ])
            )
        except queue.Full:
            await update.message.reply_text(
                "😔 I'm sorry, but the download queue is currently full.\n\n"
                "Please try again in a few minutes!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Freepik Menu", callback_data=BACK_FREEPIK)]
                ])
            )
    
    return FREEPIK_MENU

async def show_subscription_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show subscription information and options."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Get user subscriptions from database
    subscriptions = []
    if db:
        subscriptions = db.get_all_user_subscriptions(user_id)
    
    # Show subscription info
    text = "💳 *Your Subscriptions*\n\n"
    
    if subscriptions:
        active_subs = [s for s in subscriptions if s["status"] == "active"]
        if active_subs:
            for sub in active_subs:
                service = sub['service'].capitalize()
                plan = sub['plan'].capitalize()
                end_date = sub['end_date'].strftime("%Y-%m-%d")
                
                text += f"*{service} - {plan}*\n"
                text += f"Status: Active\n"
                text += f"Expires: {end_date}\n\n"
        else:
            text += "You don't have any active subscriptions.\n\n"
            
        pending_subs = [s for s in subscriptions if s["status"] == "pending"]
        if pending_subs:
            text += "*Pending Subscriptions:*\n"
            for sub in pending_subs:
                service = sub['service'].capitalize()
                plan = sub['plan'].capitalize()
                
                text += f"• {service} - {plan} (Awaiting payment verification)\n"
            text += "\n"
    else:
        text += "You don't have any subscriptions yet.\n\n"
    
    text += "Check out our subscription plans below!"
    
    await query.edit_message_text(
        text,
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Available Plans", callback_data=SUBSCRIPTION_PLANS)],
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data=BACK_MAIN_MENU)]
        ])
    )
    
    return SUBSCRIPTION_MENU

async def show_subscription_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show available subscription plans from the database."""
    query = update.callback_query
    await query.answer()
    
    # Get available plans from database
    plans_text = ""
    all_buttons = []
    service_plans = {}
    
    if db:
        # Get all active plans
        all_plans = db.get_subscription_plans()
        
        # Group plans by service
        for plan in all_plans:
            service = plan["service"]
            if service not in service_plans:
                service_plans[service] = []
            service_plans[service].append(plan)
    
    # Format the text and buttons
    if service_plans:
        for service, plans in service_plans.items():
            # Add service header
            plans_text += f"*{service.capitalize()} Plans:*\n"
            
            # List each plan
            for plan in plans:
                name = plan["name"]
                price = plan["price"]
                currency = plan["currency"]
                limit = plan["download_limit"]
                
                plans_text += f"• {name}: {currency} {price:,} ({limit} downloads/day)\n"
                
                # Create callback data
                callback_data = f"plan_{service}_{plan['plan_id']}"
                
                # Add button for this plan
                all_buttons.append([
                    InlineKeyboardButton(
                        f"{service.capitalize()} {name} - {currency} {price:,}", 
                        callback_data=callback_data
                    )
                ])
            
            plans_text += "\n"
    else:
        # Fallback if no plans in database
        plans_text = "*Freepik Plans:*\n"
        plans_text += "• Monthly: LKR 1,500 (10 downloads/day)\n"
        plans_text += "• Yearly: LKR 5,800 (10 downloads/day)\n\n"
        
        all_buttons = [
            [InlineKeyboardButton("Freepik Monthly - LKR 1,500", callback_data=FREEPIK_MONTHLY)],
            [InlineKeyboardButton("Freepik Yearly - LKR 5,800", callback_data=FREEPIK_YEARLY)]
        ]
    
    # Add coming soon services
    plans_text += "*Coming Soon:*\n"
    plans_text += "• Envato Elements\n"
    plans_text += "• Storyblocks\n\n"
    plans_text += "Please select a plan to subscribe:"
    
    # Add back button
    all_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=SUBSCRIPTION_INFO)])
    
    # Send the message
    await query.edit_message_text(
        f"📋 *Available Subscription Plans*\n\n{plans_text}",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(all_buttons)
    )
    
    return SUBSCRIPTION_MENU

async def process_subscription_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process subscription plan selection."""
    query = update.callback_query
    await query.answer()
    
    # Extract plan details from callback data
    plan_data = query.data
    logger.info(f"Processing subscription selection: {plan_data}")
    
    # Check if this is a dynamic plan from database
    if plan_data.startswith("plan_"):
        # Parse service and plan_id from the callback data
        # Format: plan_service_planid
        parts = plan_data.split("_", 2)
        if len(parts) != 3:
            await query.edit_message_text(
                "❌ Invalid plan selection. Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Plans", callback_data=SUBSCRIPTION_PLANS)]
                ])
            )
            return SUBSCRIPTION_MENU
            
        service = parts[1]
        plan_id = parts[2]
        
        # Get plan details from database
        plan = None
        if db:
            plan = db.get_subscription_plan(service, plan_id)
        
        if not plan:
            await query.edit_message_text(
                "❌ Selected plan not found. Please try again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Plans", callback_data=SUBSCRIPTION_PLANS)]
                ])
            )
            return SUBSCRIPTION_MENU
            
        # Store plan details in context
        context.user_data["subscription_service"] = service
        context.user_data["subscription_plan"] = plan_id
        context.user_data["subscription_amount"] = plan["price"]
        context.user_data["subscription_name"] = plan["name"]
        context.user_data["subscription_currency"] = plan["currency"]
        
    # Handle legacy hardcoded plans
    elif plan_data == FREEPIK_MONTHLY:
        context.user_data["subscription_service"] = "freepik"
        context.user_data["subscription_plan"] = "monthly"
        context.user_data["subscription_amount"] = 1500
        context.user_data["subscription_name"] = "Monthly"
        context.user_data["subscription_currency"] = "LKR"
    elif plan_data == FREEPIK_YEARLY:
        context.user_data["subscription_service"] = "freepik"
        context.user_data["subscription_plan"] = "yearly"
        context.user_data["subscription_amount"] = 5800
        context.user_data["subscription_name"] = "Yearly"
        context.user_data["subscription_currency"] = "LKR"
    else:
        # Invalid plan
        await query.edit_message_text(
            "❌ Invalid plan selection. Please try again.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Plans", callback_data=SUBSCRIPTION_PLANS)]
            ])
        )
        return SUBSCRIPTION_MENU
    
    # Show bank details and payment instructions
    service = context.user_data["subscription_service"].capitalize()
    plan_name = context.user_data.get("subscription_name", context.user_data["subscription_plan"].capitalize())
    amount = context.user_data["subscription_amount"]
    currency = context.user_data.get("subscription_currency", "LKR")
    
    # Bank details
    bank_name = BANK_DETAILS.get("bank_name", "Bank of Ceylon")
    branch_name = BANK_DETAILS.get("branch_name", "Main Branch")
    account_name = BANK_DETAILS.get("account_name", "Your Name")
    account_number = BANK_DETAILS.get("account_number", "1234567890")
    
    # Debugging
    logger.info(f"Bank details: {BANK_DETAILS}")
    logger.info(f"Showing payment instructions for {service} {plan_name}, {currency} {amount}")
    
    # Format amount with commas
    formatted_amount = f"{amount:,}"
    
    await query.edit_message_text(
        f"💳 *Subscribe to {service} {plan_name}*\n\n"
        f"Amount: {currency} {formatted_amount}\n\n"
        "*Payment Instructions:*\n"
        "1. Make a payment to the bank account below\n"
        "2. Add your Telegram User ID as the reference\n"
        "3. Take a screenshot/photo of the payment receipt\n"
        "4. Send the screenshot/photo to this chat\n\n"
        "*Bank Details:*\n"
        f"Bank: {bank_name}\n"
        f"Branch: {branch_name}\n"
        f"Name: {account_name}\n"
        f"Account Number: {account_number}\n\n"
        f"Reference: {query.from_user.id} (Your Telegram User ID)\n\n"
        "Please send a photo of your payment receipt.",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data=SUBSCRIPTION_INFO)]
        ])
    )
    
    # Return the next state
    return AWAITING_PAYMENT

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Debug handler to log callback queries."""
    query = update.callback_query
    logger.info(f"Received callback query: {query.data} from user {query.from_user.id}")
    
    # Let the user know we received their callback
    await query.answer()

async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle payment proof image uploads with enhanced storage."""
    user_id = update.effective_user.id
    user = update.effective_user
    
    # Get complete user information
    username = user.username
    first_name = user.first_name
    last_name = user.last_name
    full_name = user.full_name
    
    # Check if we're expecting payment proof
    if not context.user_data.get("subscription_service"):
        await update.message.reply_text(
            "Please use the menu to select a subscription plan first.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("View Plans", callback_data=SUBSCRIPTION_PLANS)]
            ])
        )
        return MAIN_MENU
    
    # Check if message contains a photo
    if not update.message.photo:
        await update.message.reply_text(
            "Please send a photo/screenshot of your payment receipt.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=SUBSCRIPTION_INFO)]
            ])
        )
        return AWAITING_PAYMENT
    
    # Get the largest photo (best quality)
    photo = update.message.photo[-1]
    
    try:
        # First acknowledge receipt to prevent timeout
        await update.message.reply_text(
            "📸 Received your payment receipt. Processing...",
            reply_markup=None
        )
        
        # Get file from Telegram with increased timeout
        photo_file = await context.bot.get_file(photo.file_id)
        file_url = photo_file.file_path
        
        # Get subscription details from context
        service = context.user_data.get("subscription_service")
        plan = context.user_data.get("subscription_plan")
        amount = context.user_data.get("subscription_amount")
        currency = context.user_data.get("subscription_currency", "LKR")
        
        # Save user information in database with enhanced details
        if db:
            db.create_or_update_user(
                user_id=user_id,
                username=username,
                name=full_name,
                first_name=first_name,
                last_name=last_name,
                telegram_info={
                    "is_premium": getattr(user, "is_premium", False),
                    "language_code": getattr(user, "language_code", None)
                }
            )
        
        # Create payment record in database
        payment_id = None
        subscription_id = None
        
        # Download the actual image file with timeout handling
        try:
            # Use a session with longer timeout
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            
            session = requests.Session()
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            # Download with extended timeout (30 seconds)
            response = session.get(file_url, timeout=30)
            image_data = response.content
            
            # Create a unique filename for the payment receipt
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            receipt_filename = f"payment_receipt_{user_id}_{timestamp}.jpg"
            
            # Save the image to a local directory
            receipts_dir = os.path.join("downloads", "payment_receipts")
            os.makedirs(receipts_dir, exist_ok=True)
            receipt_path = os.path.join(receipts_dir, receipt_filename)
            
            with open(receipt_path, "wb") as f:
                f.write(image_data)
                
            # Log the saved file path
            logger.info(f"Payment receipt saved locally at: {receipt_path}")
            
            if db:
                # Create payment record with enhanced information
                payment = db.create_payment(
                    user_id=user_id, 
                    amount=amount, 
                    currency=currency,
                    service=service, 
                    plan=plan, 
                    image_url=file_url,
                    image_file_id=photo.file_id,  # Store Telegram file ID
                    image_file_path=receipt_path,  # Store local file path
                    notes=update.message.caption or "",  # Include any caption as notes
                    payment_date=datetime.datetime.utcnow()
                )
                payment_id = payment["_id"]
                
                # Create subscription record linked to payment
                subscription = db.create_subscription(user_id, service, plan, payment_id)
                subscription_id = subscription["_id"]
        except requests.exceptions.Timeout:
            logger.error(f"Timeout downloading payment receipt image for user {user_id}")
            await update.message.reply_text(
                "❌ The image download timed out. Please try sending a smaller image or contact support.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                ])
            )
            return MAIN_MENU
        except Exception as e:
            logger.error(f"Error downloading payment image: {e}")
            # Fall back to just storing the Telegram file ID
            if db:
                payment = db.create_payment(
                    user_id=user_id, 
                    amount=amount, 
                    currency=currency,
                    service=service, 
                    plan=plan, 
                    image_url=file_url,
                    image_file_id=photo.file_id,
                    notes=update.message.caption or "",
                    payment_date=datetime.datetime.utcnow()
                )
                payment_id = payment["_id"]
                
                # Create subscription record linked to payment
                subscription = db.create_subscription(user_id, service, plan, payment_id)
                subscription_id = subscription["_id"]
        
        # Clean up context
        context.user_data.pop("subscription_service", None)
        context.user_data.pop("subscription_plan", None)
        context.user_data.pop("subscription_amount", None)
        context.user_data.pop("subscription_currency", None)
        context.user_data.pop("subscription_name", None)
        
        await update.message.reply_text(
            "✅ *Payment Proof Received!*\n\n"
            "Thank you for your payment. Your subscription will be activated after our admin verifies your payment.\n\n"
            "This usually takes 1-24 hours during business days.\n\n"
            "You'll receive a notification once your subscription is active.",
            parse_mode=constants.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
            ])
        )
        
        # Notify admin about new payment in a separate task to avoid timeout
        context.application.create_task(
            notify_admin_about_payment(context, user_id, payment_id, service, plan, amount, currency)
        )
        
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Error processing payment proof: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ There was an error processing your payment proof. Please try again later or contact support.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
            ])
        )
        return MAIN_MENU

async def notify_admin_about_payment(context, user_id, payment_id, service, plan, amount, currency):
    """Send notification to admin(s) about new payment with better error handling."""
    # Get admin chat IDs from config
    admin_chat_ids = ADMIN_CHAT_IDS
    
    if not admin_chat_ids or (len(admin_chat_ids) == 1 and admin_chat_ids[0] == ""):
        logger.warning("No admin chat IDs configured for payment notifications")
        return
    
    # Get user details from database
    user_info = ""
    if db:
        try:
            user = db.get_user(user_id)
            if user:
                username = user.get("username", "No username")
                name = user.get("name", "Unknown")
                user_info = f"Username: @{username}\nName: {name}\n"
        except Exception as e:
            logger.error(f"Error getting user info for notification: {e}")
    
    # Format notification message
    formatted_amount = f"{amount:,}"
    notification = (
        f"💰 *New Payment Received*\n\n"
        f"{user_info}"
        f"User ID: `{user_id}`\n"
        f"Service: {service.capitalize()}\n"
        f"Plan: {plan.capitalize()}\n"
        f"Amount: {currency} {formatted_amount}\n"
        f"Payment ID: `{payment_id}`\n\n"
        f"Use the admin panel to approve or reject this payment."
    )
    
    # Create approval/rejection buttons that can be used directly from Telegram
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"admin_approve_{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{payment_id}")
        ]
    ])
    
    # Send notification to all admins
    for admin_id in admin_chat_ids:
        try:
            admin_id = admin_id.strip()
            if admin_id.isdigit():
                await context.bot.send_message(
                    chat_id=int(admin_id),
                    text=notification,
                    parse_mode=constants.ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
                logger.info(f"Payment notification sent to admin {admin_id}")
                
                # Send the payment receipt image separately with error handling
                if db:
                    try:
                        payment = db.get_payment(payment_id)
                        if payment and "image_file_id" in payment:
                            await context.bot.send_photo(
                                chat_id=int(admin_id),
                                photo=payment["image_file_id"],
                                caption=f"Payment receipt for Payment ID: {payment_id}"
                            )
                            logger.info(f"Payment receipt image sent to admin {admin_id}")
                    except Exception as img_error:
                        logger.error(f"Error sending payment image to admin {admin_id}: {img_error}")
                        # Try to send a message about the error
                        try:
                            await context.bot.send_message(
                                chat_id=int(admin_id),
                                text=f"Failed to send payment receipt image: {img_error}"
                            )
                        except:
                            pass
        except Exception as e:
            logger.error(f"Failed to send payment notification to admin {admin_id}: {e}")

async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin approval/rejection of payments directly from Telegram."""
    query = update.callback_query
    await query.answer()
    
    # Extract action and payment ID from callback data
    # Format: admin_approve_paymentid or admin_reject_paymentid
    callback_data = query.data
    parts = callback_data.split('_', 2)
    
    if len(parts) != 3:
        await query.edit_message_text("Invalid callback data format.")
        return
    
    action = parts[1]
    payment_id = parts[2]
    
    # Verify this is an admin
    admin_chat_ids = [str(admin_id).strip() for admin_id in ADMIN_CHAT_IDS if admin_id]
    user_id = query.from_user.id
    
    if str(user_id) not in admin_chat_ids:
        await query.edit_message_text("You don't have permission to perform this action.")
        return
    
    if not db:
        await query.edit_message_text("Database connection not available.")
        return
    
    # Get payment details
    payment = db.get_payment(payment_id)
    if not payment:
        await query.edit_message_text(f"Payment with ID {payment_id} not found.")
        return
    
    # Get user ID and subscription details from payment
    payment_user_id = payment["user_id"]
    service = payment["service"]
    plan = payment["plan"]
    amount = payment["amount"]
    currency = payment.get("currency", "LKR")
    
    # Process based on action type
    if action == "approve":
        # Update payment status
        db.update_payment_status(payment_id, "approved", f"Approved by admin {user_id} via Telegram")
        
        # Find and activate subscription associated with this payment
        success = False
        subscriptions = db.get_all_user_subscriptions(payment_user_id)
        
        for sub in subscriptions:
            if str(sub.get("payment_id")) == str(payment_id):
                db.activate_subscription(sub["_id"])
                # Add additional user details to users table
                try:
                    user = await context.bot.get_chat(payment_user_id)
                    db.create_or_update_user(
                        user_id=payment_user_id,
                        username=user.username,
                        name=user.full_name,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        telegram_info={
                            "is_premium": getattr(user, "is_premium", False),
                            "language_code": getattr(user, "language_code", None),
                            "approved_payment_id": payment_id,
                            "payment_approved_at": datetime.datetime.utcnow()
                        }
                    )
                    logger.info(f"Updated user {payment_user_id} details after payment approval")
                except Exception as user_error:
                    logger.error(f"Failed to update user details after payment: {user_error}")
                success = True
                break
        
        # Notify user that their payment has been approved
        try:
            await context.bot.send_message(
                chat_id=payment_user_id,
                text=(
                    "✅ *Payment Approved!*\n\n"
                    f"Your payment for {service.capitalize()} {plan.capitalize()} subscription has been approved.\n\n"
                    "Your subscription is now active! You can now use the service."
                ),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            logger.info(f"Sent approval notification to user {payment_user_id}")
        except Exception as e:
            logger.error(f"Failed to send approval notification to user {payment_user_id}: {e}")
        
        # Update admin message - with a modified text to avoid BadRequest error
        current_text = query.message.text
        new_text = f"✅ Payment {payment_id} approved successfully.\n\nUser {payment_user_id} has been notified and their subscription is now active."
        
        # Only update if the text is different
        if current_text != new_text:
            try:
                await query.edit_message_text(new_text, reply_markup=None)
            except Exception as e:
                logger.error(f"Failed to update admin message: {e}")
                # Alternative approach: send a new message instead of editing
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"✅ Action completed: Payment {payment_id} approved.\n\nUser {payment_user_id} has been notified."
                )
        else:
            # If text would be the same, just remove the buttons
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as e:
                logger.error(f"Failed to update message reply markup: {e}")
                # Send a confirmation as a new message
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"✅ Action completed: Payment approved."
                )
    
    elif action == "reject":
        # Update payment status
        db.update_payment_status(payment_id, "rejected", f"Rejected by admin {user_id} via Telegram")
        
        # Notify user that their payment has been rejected
        try:
            await context.bot.send_message(
                chat_id=payment_user_id,
                text=(
                    "❌ *Payment Rejected*\n\n"
                    f"Your payment for {service.capitalize()} {plan.capitalize()} subscription could not be verified.\n\n"
                    "Please contact support if you believe this is an error or try again with a clearer payment proof."
                ),
                parse_mode=constants.ParseMode.MARKDOWN
            )
            logger.info(f"Sent rejection notification to user {payment_user_id}")
        except Exception as e:
            logger.error(f"Failed to send rejection notification to user {payment_user_id}: {e}")
        
        # Update admin message - with a modified text to avoid BadRequest error
        current_text = query.message.text
        new_text = f"❌ Payment {payment_id} has been rejected.\n\nUser {payment_user_id} has been notified."
        
        # Only update if the text is different
        if current_text != new_text:
            try:
                await query.edit_message_text(new_text, reply_markup=None)
            except Exception as e:
                logger.error(f"Failed to update admin message: {e}")
                # Alternative approach: send a new message instead of editing
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"❌ Action completed: Payment {payment_id} rejected.\n\nUser {payment_user_id} has been notified."
                )
        else:
            # If text would be the same, just remove the buttons
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as e:
                logger.error(f"Failed to update message reply markup: {e}")
                # Send a confirmation as a new message
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"❌ Action completed: Payment rejected."
                )
    
    else:
        await query.edit_message_text("Unknown action type.")

async def handle_license_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle license confirmation after resource download."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    
    license_choice = query.data
    
    if license_choice == LICENSE_YES:
        # User wants the license file
        await query.edit_message_text(
            "⏳ Processing License Download\n\n"
            "Please wait while I download the license file for you...\n"
            "This may take up to 5 minutes to complete.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=LICENSE_NO)]
            ])
        )
        
        # Add to download queue with special flag for license only
        resource_url = context.user_data.get("last_download_url", "")
        
        if resource_url:
            with queue_lock:
                try:
                    # Special flag in the tuple to indicate license-only download
                    download_queue.put_nowait((user_id, chat_id, resource_url, query.message.message_id, True))
                    logger.info(f"Added license-only download to queue for user {user_id}")
                    
                    # Send a follow-up message explaining the wait
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="ℹ️ License downloads require visiting the Freepik downloads page, which can take some time. Please be patient while I retrieve your license file."
                    )
                except queue.Full:
                    await query.edit_message_text(
                        "😔 I'm sorry, but the download queue is currently full.\n\n"
                        "Please try again in a few minutes!",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                        ])
                    )
        else:
            await query.edit_message_text(
                "❌ Error: Could not find the resource URL for license download.\n\n"
                "Please try downloading the resource again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
                ])
            )
    else:
        # User doesn't want the license file
        await query.edit_message_text(
            "✅ Download Complete\n\n"
            "Thank you for using our service!\n"
            "You can download more resources from the main menu.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back to Main Menu", callback_data=BACK_MAIN_MENU)]
            ])
        )
    
    return MAIN_MENU

# --------------------------------
# Utility Functions
# --------------------------------

def send_user_message(chat_id, message: str):
    """Send a message to the user via Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": f"[BOT] {message}",
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=payload)
    except Exception as e:
        logger.error(f"Failed to send message to user: {e}")

def upload_to_telegram(chat_id, file_paths, context=None, is_resource=True):
    """
    Send the specified files to a Telegram chat.
    
    Args:
        chat_id: Telegram chat ID to send files to
        file_paths: List of file paths to upload
        context: Bot context for sending inline buttons after resource
        is_resource: Whether this is a resource file (not a license)
    """
    if not file_paths or all(not path for path in file_paths):
        logger.info("No files to upload to Telegram.")
        return False
        
    logger.info(f"Uploading {len(file_paths)} files to Telegram chat {chat_id}...")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    success = True
    
    for i, file_path in enumerate(file_paths):
        if not file_path or not os.path.exists(file_path):
            logger.error(f"File {file_path} doesn't exist, skipping.")
            continue
            
        try:
            # Calculate file size in MB
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            file_name = os.path.basename(file_path)
            
            logger.info(f"Uploading file {i+1}/{len(file_paths)}: {file_name} ({file_size_mb:.1f} MB)")
            
            # If file is large, notify user first
            if file_size_mb > 10 and context and hasattr(context, 'bot'):
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"📤 Uploading {file_name} ({file_size_mb:.1f} MB)...\nThis may take a few minutes."
                )
            
            with open(file_path, "rb") as f:
                # Different caption based on file type 
                if "license" in file_name.lower():
                    caption = "📝 Here's your license file."
                else:
                    caption = "🎁 Here's your downloaded resource file!"
                    
                response = requests.post(
                    url, 
                    data={"chat_id": chat_id, "caption": caption},
                    files={"document": f},
                    timeout=300  # 5 minutes timeout for large files
                )
            response.raise_for_status()
            logger.info(f"Successfully uploaded {file_name} to chat {chat_id}.")
            
            # Only show license confirmation buttons if we've uploaded only the resource file
            # and we didn't include a license file in this batch
            show_license_buttons = (
                is_resource and 
                len(file_paths) == 1 and 
                "license" not in file_name.lower() and
                context and 
                hasattr(context, 'bot')
            )
            
            if show_license_buttons:
                last_url = context.user_data.get("freepik_url")
                
                if last_url:
                    context.user_data["last_download_url"] = last_url
                    
                    # Send message with license confirmation buttons
                    context.bot.send_message(
                        chat_id=chat_id,
                        text="Would you like me to download the license file as well?\n\n⚠️ Note: This may take a few minutes.",
                        reply_markup=InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("Yes", callback_data=LICENSE_YES),
                                InlineKeyboardButton("No", callback_data=LICENSE_NO)
                            ]
                        ])
                    )
        except requests.exceptions.ReadTimeout:
            logger.error(f"Timeout uploading {os.path.basename(file_path)}")
            try:
                if context and hasattr(context, 'bot'):
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ The file upload timed out. The file might be too large for Telegram. Try downloading again or try a different resource."
                    )
                else:
                    send_user_message(chat_id, f"⚠️ The file upload timed out. The file might be too large for Telegram.")
            except Exception as e:
                logger.error(f"Failed to send timeout message: {e}")
            success = False
        except Exception as e:
            logger.error(f"Failed to upload {os.path.basename(file_path)}: {e}")
            success = False
            
    return success

# --------------------------------
# Telegram Bot Setup
# --------------------------------

def setup_bot_handlers(application):
    """Set up the bot command handlers with improved error handling."""
    logger.info("Setting up bot handlers...")
    
    # Add error handler to catch and log exceptions
    async def error_handler(update, context):
        """Log errors caused by Updates."""
        if isinstance(context.error, TimeoutError):
            logger.error(f"Timeout error processing update: {update}")
            if update and update.effective_chat:
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="⚠️ The operation timed out. Please try again or use a smaller image."
                    )
                except Exception as e:
                    logger.error(f"Error sending timeout message: {e}")
        else:
            logger.error(f"Update {update} caused error: {context.error}", exc_info=context.error)
            if update and update.effective_chat:
                # Notify user that an error occurred
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="An error occurred while processing your request. Please try again later."
                    )
                except Exception as e:
                    logger.error(f"Error sending error message: {e}")
    
    # Define conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CommandHandler("subscriptions", subscriptions_command),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(continue_to_menu, pattern="^continue_to_menu$"),
                CallbackQueryHandler(my_info, pattern="^my_info$"),
                CallbackQueryHandler(handle_service_selection, pattern=f"^{FREEPIK_SERVICE}$|^{ENVATO_SERVICE}$|^{STORYBLOCKS_SERVICE}$"),
                CallbackQueryHandler(show_subscription_info, pattern=f"^{SUBSCRIPTION_INFO}$"),
                CallbackQueryHandler(help_command, pattern="^help$"),
            ],
            SERVICE_MENU: [
                CallbackQueryHandler(show_freepik_menu, pattern=f"^{FREEPIK_SERVICE}$"),
                CallbackQueryHandler(continue_to_menu, pattern=f"^{BACK_MAIN_MENU}$"),
            ],
            FREEPIK_MENU: [
                CallbackQueryHandler(prompt_for_url, pattern=f"^{FREEPIK_SEND_URL}$"),
                CallbackQueryHandler(show_user_downloads, pattern=f"^{FREEPIK_DOWNLOADS}$"),
                CallbackQueryHandler(show_freepik_info, pattern=f"^{FREEPIK_INFO}$"),
                CallbackQueryHandler(show_subscription_plans, pattern=f"^{SUBSCRIPTION_PLANS}$"),
                CallbackQueryHandler(show_freepik_menu, pattern=f"^{BACK_FREEPIK}$"),
                CallbackQueryHandler(continue_to_menu, pattern=f"^{BACK_MAIN_MENU}$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url),
            ],
            SUBSCRIPTION_MENU: [
                CallbackQueryHandler(show_subscription_plans, pattern=f"^{SUBSCRIPTION_PLANS}$"),
                CallbackQueryHandler(show_subscription_info, pattern=f"^{SUBSCRIPTION_INFO}$"),
                # Update pattern to match both legacy and dynamic plan patterns
                CallbackQueryHandler(process_subscription_selection, pattern=f"^{FREEPIK_MONTHLY}$|^{FREEPIK_YEARLY}$|^plan_"),
                CallbackQueryHandler(continue_to_menu, pattern=f"^{BACK_MAIN_MENU}$"),
            ],
            AWAITING_PAYMENT: [
                CallbackQueryHandler(show_subscription_info, pattern=f"^{SUBSCRIPTION_INFO}$"),
                MessageHandler(filters.PHOTO, handle_payment_proof),
            ],
            AWAITING_LICENSE_CONFIRM: [
                CallbackQueryHandler(handle_license_confirmation, pattern=f"^{LICENSE_YES}$|^{LICENSE_NO}$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", start_command),
            CommandHandler("help", help_command),
            CommandHandler("status", status_command),
            CommandHandler("queue", queue_command),
            CommandHandler("subscriptions", subscriptions_command),
            CallbackQueryHandler(continue_to_menu, pattern=f"^{BACK_MAIN_MENU}$"),
        ],
        name="main_conversation",
        persistent=False,
        per_message=False  # Important: Handle callbacks for each message individually
    )
    
    # Add the conversation handler to the application
    application.add_handler(conv_handler)
    
    # Add standalone command handlers
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("queue", queue_command))
    
    # Add handler for admin actions (for payment approval/rejection)
    application.add_handler(CallbackQueryHandler(handle_admin_action, pattern="^admin_"))
    
    # Add a catch-all callback handler for debugging
    # This should be added AFTER other specific handlers
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    logger.info("Bot handlers setup complete")

def run_bot(token):
    """Start the bot with improved error handling."""
    try:
        # Create the Application and pass it your bot's token
        application = Application.builder().token(token).build()

        # Set up handlers
        setup_bot_handlers(application)
        
        # Start the Bot
        logger.info("Starting bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
        return application
    except Exception as e:
        logger.critical(f"Failed to start bot: {e}")
        # Re-raise to ensure the error is visible
        raise