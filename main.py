import os
import time
import threading
import logging
import signal
import sys
import datetime
from utils import setup_logging, load_config, create_shared_resources
from freepik_login import create_browser_context, login_to_freepik
from freepik_downloader import download_resource, download_license, cleanup_files
from telegram_bot import init_bot, run_bot, send_user_message, upload_to_telegram

# Configure logging
logger = setup_logging()

# Global flag for graceful shutdown
shutdown_flag = threading.Event()

def signal_handler(sig, frame):
    """Handle termination signals for graceful shutdown."""
    logger.info(f"Received signal {sig}. Initiating graceful shutdown...")
    shutdown_flag.set()
    
    # Give threads time to clean up, then exit
    time.sleep(3)
    logger.info("Exiting application.")
    sys.exit(0)

def monitor_resources():
    """Monitor system resources and log statistics."""
    while not shutdown_flag.is_set():
        try:
            # Log basic statistics
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            thread_count = threading.active_count()
            download_dir_size = get_directory_size("downloads")
            
            # Add payment receipts directory stats if it exists
            payment_receipts_dir = os.path.join("downloads", "payment_receipts")
            payment_receipts_size = 0
            payment_receipts_count = 0
            
            if os.path.exists(payment_receipts_dir):
                payment_receipts_size = get_directory_size(payment_receipts_dir)
                payment_receipts_count = count_files(payment_receipts_dir)
            
            logger.info(f"[MONITOR] Time: {current_time}, Active threads: {thread_count}, "
                        f"Downloads dir size: {download_dir_size} MB, "
                        f"Payment receipts: {payment_receipts_count} files ({payment_receipts_size} MB)")
        except Exception as e:
            logger.error(f"Error in monitoring thread: {e}")
        
        # Sleep for monitoring interval
        time.sleep(300)  # Check every 5 minutes

def get_directory_size(path='.'):
    """Get the size of a directory in megabytes."""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    
    # Convert bytes to megabytes
    return round(total_size / (1024 * 1024), 2)

def count_files(path='.'):
    """Count the number of files in a directory."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(path):
        count += len(filenames)
    return count

def cleanup_old_files(download_dir, max_age_days=7):
    """Clean up files older than max_age_days."""
    try:
        now = time.time()
        count = 0
        size_freed = 0
        
        for root, dirs, files in os.walk(download_dir):
            for f in files:
                file_path = os.path.join(root, f)
                if os.path.exists(file_path):
                    file_age = now - os.path.getmtime(file_path)
                    # If file is older than max age
                    if file_age > (max_age_days * 86400):  # Convert days to seconds
                        size = os.path.getsize(file_path)
                        try:
                            os.remove(file_path)
                            count += 1
                            size_freed += size
                            logger.debug(f"Deleted old file: {file_path}")
                        except Exception as e:
                            logger.error(f"Failed to delete old file {file_path}: {e}")
        
        if count > 0:
            size_freed_mb = round(size_freed / (1024 * 1024), 2)
            logger.info(f"Cleanup: Removed {count} old files, freed {size_freed_mb} MB")
    except Exception as e:
        logger.error(f"Error during file cleanup: {e}")

def process_download_queue(
    download_queue, 
    active_downloads, 
    queue_lock, 
    freepik_email, 
    freepik_password, 
    apikey_2captcha, 
    download_dir,
    database,
    headless=True
):
    """Process the download queue in a separate thread."""
    logger.info("Download queue processor started.")
    
    last_cleanup_time = time.time()
    cleanup_interval = 24 * 60 * 60  # Run cleanup once a day
    
    while not shutdown_flag.is_set():
        try:
            # Run cleanup if necessary
            current_time = time.time()
            if current_time - last_cleanup_time > cleanup_interval:
                cleanup_old_files(download_dir)
                last_cleanup_time = current_time
            
            # Check if queue is empty
            if download_queue.empty():
                time.sleep(10)  # Sleep for a bit if the queue is empty
                continue
            
            # Get the next item from the queue
            # Check if it's a license-only download (will have 5 elements instead of 4)
            queue_item = download_queue.get()
            license_only = False
            
            if len(queue_item) >= 5:
                user_id, chat_id, resource_url, message_id, license_only = queue_item
            else:
                user_id, chat_id, resource_url, message_id = queue_item
            
            # Update status
            with queue_lock:
                if license_only:
                    active_downloads[user_id] = "Downloading license..."
                else:
                    active_downloads[user_id] = "Starting download..."
            
            # Notify user
            if not license_only:
                send_user_message(chat_id, f"🚀 Your download is starting now!\n\nURL: {resource_url}")
            
            # Start the download process
            resource_file = ""
            license_file = ""
            
            try:
                # Create browser context
                playwright, browser, context, page = create_browser_context(headless=headless)
                
                try:
                    # Update status and log in first
                    with queue_lock:
                        active_downloads[user_id] = "Logging in..."
                    
                    # Create user directory for downloads
                    user_download_dir = os.path.join(download_dir, f"user_{user_id}")
                    os.makedirs(user_download_dir, exist_ok=True)
                    
                    # Login to Freepik first
                    logged_in = False
                    current_page = page
                    for attempt in range(1, 3):
                        with queue_lock:
                            active_downloads[user_id] = f"Login attempt {attempt}..."
                        
                        login_result, current_page = login_to_freepik(
                            browser, current_page, freepik_email, freepik_password, apikey_2captcha
                        )
                        if login_result:
                            logged_in = True
                            break
                        else:
                            time.sleep(2)
                    
                    if not logged_in:
                        send_user_message(chat_id, "❌ Login failed. Unable to download your resource.")
                        with queue_lock:
                            if user_id in active_downloads:
                                del active_downloads[user_id]
                        continue

                    # If this is a license-only download, skip the resource download
                    if not license_only:
                        # Download the resource
                        with queue_lock:
                            active_downloads[user_id] = "Downloading resource..."
                        
                        resource_file, download_success = download_resource(
                            current_page, resource_url, user_id, download_dir, send_user_message, chat_id
                        )
                        
                        if not download_success:
                            logger.error(f"Failed to download resource for user {user_id}")
                            with queue_lock:
                                if user_id in active_downloads:
                                    del active_downloads[user_id]
                            continue
                        
                        # Record the download in the database
                        if database and resource_file and download_success:
                            try:
                                file_name = os.path.basename(resource_file)
                                file_size = os.path.getsize(resource_file) if os.path.exists(resource_file) else 0
                                database.record_download(user_id, "freepik", resource_url, file_name, file_size)
                                logger.info(f"Recorded download in database for user {user_id}")
                            except Exception as db_error:
                                logger.error(f"Error recording download in database: {db_error}")
                    
                    if not license_only and download_success:
                        # Add a waiting period before attempting to get the license
                        with queue_lock:
                            active_downloads[user_id] = "Waiting for license to be available..."
    
                        # Send notification to user
                        send_user_message(chat_id, "✅ Resource downloaded successfully! Waiting 3-5 minutes for the license to become available...")
    
                        # Wait 3-5 minutes for the license to be available
                        time.sleep(180)  # 3 minutes in seconds
                    
                    # Download license
                    with queue_lock:
                        active_downloads[user_id] = "Downloading license..."
                    
                    # Try to download the license
                    license_file = download_license(current_page, resource_file or "dummy_path", user_id, download_dir)
                    
                    # Upload files to Telegram
                    with queue_lock:
                        active_downloads[user_id] = "Uploading files to Telegram..."
                    
                    if license_only:
                        # Only upload license file
                        if license_file:
                            license_upload_success = upload_to_telegram(chat_id, [license_file], None, False)
                            
                            if license_upload_success:
                                send_user_message(chat_id, "✅ License download complete!")
                            else:
                                send_user_message(chat_id, "⚠️ There was an issue sending the license file.")
                        else:
                            send_user_message(chat_id, "❌ Failed to download the license file.")
                    else:
                        # For regular downloads, upload BOTH resource file and license file if available
                        files_to_upload = []
                        if resource_file:
                            files_to_upload.append(resource_file)
                        
                        # Also upload the license file right away if we have it
                        if license_file:
                            files_to_upload.append(license_file)
                            
                        if files_to_upload:
                            upload_success = upload_to_telegram(chat_id, files_to_upload, context)
                            
                            if not upload_success:
                                send_user_message(chat_id, "⚠️ There was an issue sending the files.")
                        else:
                            send_user_message(chat_id, "❌ No files were downloaded.")
                finally:
                    # Close browser resources
                    try:
                        if context:
                            context.close()
                        if browser:
                            browser.close()
                        if playwright:
                            playwright.stop()
                    except Exception as e:
                        logger.error(f"Error closing browser resources: {e}")
            
            except Exception as e:
                logger.error(f"Error processing download for user {user_id}: {e}")
                send_user_message(chat_id, f"❌ An error occurred during your download: {str(e)[:100]}...\n\nPlease try again later.")
            
            finally:
                # Clean up files and status
                files_to_cleanup = [f for f in [resource_file, license_file] if f]
                if files_to_cleanup:
                    cleanup_files(files_to_cleanup)
                
                with queue_lock:
                    if user_id in active_downloads:
                        del active_downloads[user_id]
                
                # Mark task as done
                download_queue.task_done()
                
                logger.info(f"Finished processing download for user {user_id}.")
        
        except Exception as e:
            logger.error(f"Error in queue processor: {e}")
            time.sleep(10)  # Sleep to avoid rapid error looping
    
    logger.info("Download queue processor shutting down...")

def load_env_config():
    """Enhanced load_config function with admin chat IDs."""
    # Load configuration from environment variables
    config = load_config()
    
    # Add admin chat IDs for payment notifications
    admin_chat_ids = os.getenv("ADMIN_CHAT_IDS", "").split(",")
    config['admin_chat_ids'] = admin_chat_ids
    
    logger.info(f"Loaded admin chat IDs: {len(admin_chat_ids)} admin(s) configured")
    
    return config

def main():
    """Main entry point of the application."""
    try:
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Load configuration with enhanced admin settings
        config = load_env_config()
        logger.info("Configuration loaded successfully")
        
        # Initialize shared resources
        download_queue, active_downloads, queue_lock, db = create_shared_resources(
            config['max_queue_size'], 
            config['mongodb_uri']
        )
        
        # Create bank details dictionary
        bank_details = {
            "bank_name": config.get('bank_name', "Bank of Ceylon"),
            "branch_name": config.get('branch_name', "Main Branch"),
            "account_name": config.get('account_name', "Your Name"),
            "account_number": config.get('account_number', "1234567890")
        }
        
        # Log bank details for debugging
        logger.info(f"Bank details: {bank_details}")
        
        # Create necessary directories
        # Main download directory
        os.makedirs(config['download_dir'], exist_ok=True)
        
        # Payment receipts directory
        payment_receipts_dir = os.path.join(config['download_dir'], "payment_receipts")
        os.makedirs(payment_receipts_dir, exist_ok=True)
        logger.info(f"Created payment receipts directory: {payment_receipts_dir}")
        
        # Initialize bot with shared resources
        init_bot(
            config['telegram_bot_token'], 
            config['freepik_url_pattern'], 
            config['max_queue_size'],
            download_queue,
            active_downloads,
            queue_lock,
            db,
            bank_details,
            config['admin_chat_ids']  # Pass admin chat IDs to the bot
        )
        
        # Start the queue processor thread
        queue_thread = threading.Thread(
            target=process_download_queue,
            args=(
                download_queue,
                active_downloads,
                queue_lock,
                config['freepik_email'],
                config['freepik_password'],
                config['apikey_2captcha'],
                config['download_dir'],
                db,
                config['headless']
            ),
            daemon=True,
            name="DownloadQueueProcessor"
        )
        queue_thread.start()
        logger.info("Download queue processor thread started")
        
        # Start resource monitoring thread
        monitor_thread = threading.Thread(
            target=monitor_resources,
            daemon=True,
            name="ResourceMonitor"
        )
        monitor_thread.start()
        logger.info("Resource monitoring thread started")
        
        # Log startup complete
        logger.info(f"Freepik Downloader Bot started successfully!")
        logger.info(f"Queue size: {config['max_queue_size']}, Headless mode: {config['headless']}")
        
        # Run the bot (this will block until the bot is stopped)
        run_bot(config['telegram_bot_token'])
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt. Shutting down...")
        shutdown_flag.set()
    except Exception as e:
        logger.critical(f"Critical error in main function: {e}")
        shutdown_flag.set()
        raise

def run_with_restart():
    """Run the bot with automatic restart on failure."""
    max_retries = 5
    retry_count = 0
    retry_delay = 30  # seconds
    
    while retry_count < max_retries:
        try:
            main()
            break  # If main exits normally, break the loop
        except Exception as e:
            retry_count += 1
            logger.error(f"Bot crashed with error: {e}")
            logger.error(f"Attempt {retry_count}/{max_retries} - Restarting in {retry_delay} seconds...")
            time.sleep(retry_delay)
            # Increase delay for next retry
            retry_delay = min(retry_delay * 2, 300)  # Cap at 5 minutes
    
    if retry_count >= max_retries:
        logger.critical("Maximum retry attempts reached. Bot is shutting down.")

if __name__ == "__main__":
    run_with_restart()