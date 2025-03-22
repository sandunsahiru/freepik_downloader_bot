import os
import sys
import logging
import threading
import queue
from dotenv import load_dotenv
from database import Database
import urllib.parse  # Add this import for URL encoding
import traceback  # Add this import for full error tracebacks

# Configure logging
def setup_logging(log_level=logging.INFO):
    """Configure logging for the application."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=log_level,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("freepik_bot.log")
        ]
    )
    
    # Set specific loggers to a different level if needed
    # For example, to reduce noise from some libraries:
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    logger = logging.getLogger(__name__)
    logger.info("Logging configured successfully")
    return logger

def load_config():
    """Load environment variables and return configuration."""
    # Load environment variables from .env file
    load_dotenv()
    
    # Required environment variables
    required_vars = [
        "FREEPIK_EMAIL", 
        "FREEPIK_PASSWORD", 
        "TELEGRAM_BOT_TOKEN", 
        "APIKEY_2CAPTCHA",
        "MONGODB_URI"
    ]
    config = {}
    
    # Check for required environment variables
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            missing_vars.append(var)
        config[var.lower()] = value
    
    if missing_vars:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Optional environment variables with defaults
    config['download_dir'] = os.getenv("DOWNLOAD_DIR", "downloads")
    config['max_queue_size'] = int(os.getenv("MAX_QUEUE_SIZE", "10"))
    config['headless'] = os.getenv("HEADLESS", "true").lower() == "true"
    
    # Bank details for payments
    config['bank_name'] = os.getenv("BANK_NAME", "Bank of Ceylon")
    config['branch_name'] = os.getenv("BRANCH_NAME", "Main Branch")
    config['account_name'] = os.getenv("ACCOUNT_NAME", "Your Name")
    config['account_number'] = os.getenv("ACCOUNT_NUMBER", "1234567890")
    
    # Create download directory if it doesn't exist
    os.makedirs(config['download_dir'], exist_ok=True)
    
    # URL regex pattern
    config['freepik_url_pattern'] = r"https?://(?:www\.)?freepik\.com/(?:[a-zA-Z0-9_-]+/)+[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9]+)*(?:#[^#\s]*)?(?:\?[^\s]*)?"
    
    return config

def create_shared_resources(max_queue_size, mongodb_uri):
    """Create and return shared resources for thread communication."""
    # Get a logger instance for this function
    logger = logging.getLogger(__name__)
    
    download_queue = queue.Queue(maxsize=max_queue_size)
    active_downloads = {}  # userid -> status
    queue_lock = threading.Lock()
    
    # Fix MongoDB URI by properly encoding username and password
    try:
        # Log the original (masked) URI for debugging
        masked_uri = mongodb_uri
        if '@' in masked_uri:
            parts = masked_uri.split('@')
            credentials = parts[0].split('://')
            masked_uri = f"{credentials[0]}://****:****@{parts[1]}"
        logger.info(f"Original MongoDB URI format: {masked_uri}")
        
        # Fix MongoDB URI by properly encoding username and password
        if '@' in mongodb_uri:
            # Parse the URI to encode credentials
            parts = mongodb_uri.split("://")
            protocol = parts[0]
            rest = parts[1]
            
            # Handle case where @ might appear in password
            if rest.count('@') > 1:
                # Find the last @ which separates credentials from host
                last_at_index = rest.rindex('@')
                credentials = rest[:last_at_index]
                host_part = rest[last_at_index+1:]
            else:
                credentials, host_part = rest.split('@', 1)
            
            # Make sure credentials contain a colon for username:password
            if ':' in credentials:
                username, password = credentials.split(':', 1)
                
                # URL encode the username and password
                encoded_username = urllib.parse.quote_plus(username)
                encoded_password = urllib.parse.quote_plus(password)
                
                # Reconstruct the URI
                fixed_uri = f"{protocol}://{encoded_username}:{encoded_password}@{host_part}"
                mongodb_uri = fixed_uri
                logger.info("MongoDB URI credentials encoded successfully")
            else:
                logger.warning("MongoDB URI has @ but no username:password format detected")
        
        # Initialize database connection
        logger.info("Initializing database connection...")
        db = Database(mongodb_uri)
        
        # Verify connection is successful
        if db.is_connected:
            logger.info("MongoDB connection successful!")
            
            # Test a real write operation
            try:
                test_user = db.create_or_update_user(
                    user_id=999999,  # Test user ID
                    username="test_user",
                    name="Test User",
                    first_name="Test",
                    last_name="User"
                )
                logger.info(f"MongoDB test write successful! Test user registered/updated")
                
                # Get collections for debugging
                collections = db.db.list_collection_names()
                logger.info(f"MongoDB collections: {collections}")
            except Exception as e:
                logger.error(f"MongoDB test write failed: {e}")
                logger.error(traceback.format_exc())
                
        else:
            logger.error("Database initialized but is_connected=False! Using mock database.")
        
    except Exception as e:
        logger.error(f"Error connecting to MongoDB: {e}")
        logger.error(traceback.format_exc())
        db = None
    
    return download_queue, active_downloads, queue_lock, db