import logging
import datetime
from pymongo import MongoClient
from bson.objectid import ObjectId

logger = logging.getLogger(__name__)

class MockDatabase:
    """Mock database for when MongoDB connection fails. Implements in-memory storage."""
    
    def __init__(self):
        """Initialize mock database."""
        logger.warning("Using MockDatabase instead of MongoDB")
        self.users = {}
        self.subscriptions = []
        self.downloads = []
        self.payments = []
        self.download_limits = {}
        self.subscription_plans = [
            {
                "service": "freepik",
                "plan_id": "monthly",
                "name": "Monthly",
                "description": "Freepik Monthly Subscription",
                "price": 1500,
                "currency": "LKR",
                "duration_days": 30,
                "download_limit": 10,
                "is_active": True
            },
            {
                "service": "freepik",
                "plan_id": "yearly",
                "name": "Yearly",
                "description": "Freepik Yearly Subscription",
                "price": 5800,
                "currency": "LKR",
                "duration_days": 365,
                "download_limit": 10,
                "is_active": True
            }
        ]
    
    def get_user(self, user_id):
        """Get user by Telegram user ID."""
        return self.users.get(user_id)
    
    def create_or_update_user(self, user_id, username=None, name=None, first_name=None, last_name=None, telegram_info=None):
        """Create new user or update existing one with enhanced information."""
        now = datetime.datetime.utcnow()
        
        if user_id in self.users:
            self.users[user_id]["last_active"] = now
            if username:
                self.users[user_id]["username"] = username
            if name:
                self.users[user_id]["name"] = name
            if first_name:
                self.users[user_id]["first_name"] = first_name
            if last_name:
                self.users[user_id]["last_name"] = last_name
            if telegram_info:
                self.users[user_id]["telegram_info"] = telegram_info
            return self.users[user_id]
        else:
            user = {
                "user_id": user_id,
                "username": username,
                "name": name,
                "first_name": first_name,
                "last_name": last_name,
                "telegram_info": telegram_info or {},
                "registration_date": now,
                "last_active": now
            }
            self.users[user_id] = user
            return user
    
    def get_active_subscription(self, user_id, service):
        """Get active subscription for a user for a specific service."""
        now = datetime.datetime.utcnow()
        
        for sub in self.subscriptions:
            if (sub["user_id"] == user_id and 
                sub["service"] == service and 
                sub["end_date"] > now and 
                sub["status"] == "active"):
                return sub
        return None
    
    def get_all_user_subscriptions(self, user_id):
        """Get all subscriptions for a user."""
        return [sub for sub in self.subscriptions if sub["user_id"] == user_id]
    
    def create_subscription(self, user_id, service, plan, payment_id=None):
        """Create a new subscription with pending status and status history."""
        now = datetime.datetime.utcnow()
        
        # Get plan details
        plan_details = self.get_subscription_plan(service, plan)
        
        if plan_details:
            # Calculate end date based on plan duration
            duration_days = plan_details.get("duration_days", 30)  # Default to 30 days
            end_date = now + datetime.timedelta(days=duration_days)
        else:
            # Fallback for legacy plans
            if plan == "monthly":
                end_date = now + datetime.timedelta(days=30)
            elif plan == "yearly":
                end_date = now + datetime.timedelta(days=365)
            else:
                raise ValueError(f"Invalid plan: {plan}")
        
        subscription = {
            "_id": str(len(self.subscriptions) + 1),
            "user_id": user_id,
            "service": service,
            "plan": plan,
            "start_date": now,
            "end_date": end_date,
            "status": "pending",
            "payment_id": payment_id,
            "created_at": now,
            "last_status_update": now,
            "status_history": [
                {
                    "status": "pending",
                    "timestamp": now,
                    "notes": "Subscription created, awaiting payment verification"
                }
            ]
        }
        
        self.subscriptions.append(subscription)
        return subscription
    
    def activate_subscription(self, subscription_id):
        """Activate a pending subscription with status history tracking."""
        now = datetime.datetime.utcnow()
        
        for sub in self.subscriptions:
            if str(sub.get("_id")) == str(subscription_id):
                sub["status"] = "active"
                sub["activated_at"] = now
                sub["last_status_update"] = now
                
                # Add status history entry
                if "status_history" not in sub:
                    sub["status_history"] = []
                
                sub["status_history"].append({
                    "status": "active",
                    "timestamp": now,
                    "notes": "Subscription activated"
                })
                
                return True
        return False
    
    def create_payment(self, user_id, amount, service, plan, image_url, image_file_id=None, 
                      image_file_path=None, notes="", payment_date=None, currency="LKR"):
        """Create a new payment record with enhanced image handling and status history."""
        if payment_date is None:
            payment_date = datetime.datetime.utcnow()
            
        payment = {
            "_id": str(len(self.payments) + 1),
            "user_id": user_id,
            "amount": amount,
            "currency": currency,
            "service": service,
            "plan": plan,
            "payment_date": payment_date,
            "image_url": image_url,
            "status": "pending",
            "admin_notes": ""
        }
        
        # Add additional fields if provided
        if image_file_id:
            payment["image_file_id"] = image_file_id
            
        if image_file_path:
            payment["image_file_path"] = image_file_path
            
        if notes:
            payment["user_notes"] = notes
        
        # Add status tracking fields
        payment["status_history"] = [
            {
                "status": "pending",
                "timestamp": payment_date,
                "notes": "Payment proof received"
            }
        ]
        
        self.payments.append(payment)
        return payment
    
    def get_payment(self, payment_id):
        """Get payment by ID."""
        for payment in self.payments:
            if str(payment.get("_id")) == str(payment_id):
                return payment
        return None
    
    def get_pending_payments(self, with_details=False):
        """Get all pending payments for admin review with optional user details."""
        pending_payments = [p for p in self.payments if p["status"] == "pending"]
        
        if with_details:
            # Add user details to each payment
            for payment in pending_payments:
                user_id = payment["user_id"]
                user = self.users.get(user_id)
                if user:
                    payment["user_details"] = user
                    
        return pending_payments
    
    def update_payment_status(self, payment_id, status, admin_notes=None):
        """Update payment status with history tracking."""
        now = datetime.datetime.utcnow()
        
        for payment in self.payments:
            if str(payment.get("_id")) == str(payment_id):
                payment["status"] = status
                
                if admin_notes:
                    payment["admin_notes"] = admin_notes
                
                # Add status history entry
                if "status_history" not in payment:
                    payment["status_history"] = []
                
                payment["status_history"].append({
                    "status": status,
                    "timestamp": now,
                    "notes": admin_notes if admin_notes else f"Status changed to {status}"
                })
                
                return True
        return False
    
    def record_download(self, user_id, service, resource_url, file_name, file_size):
        """Record a download."""
        download = {
            "_id": str(len(self.downloads) + 1),
            "user_id": user_id,
            "service": service,
            "resource_url": resource_url,
            "download_date": datetime.datetime.utcnow(),
            "file_name": file_name,
            "file_size": file_size
        }
        
        self.downloads.append(download)
        return download
    
    def get_user_downloads(self, user_id, service, limit=10):
        """Get recent downloads for a user."""
        user_downloads = [d for d in self.downloads if d["user_id"] == user_id and d["service"] == service]
        user_downloads.sort(key=lambda x: x["download_date"], reverse=True)
        return user_downloads[:limit]
    
    def get_user_downloads_for_date(self, user_id, service, date):
        """Get downloads for a user on a specific date."""
        # Convert date to datetime if needed
        if isinstance(date, datetime.date) and not isinstance(date, datetime.datetime):
            start_of_day = datetime.datetime.combine(date, datetime.time.min)
            end_of_day = datetime.datetime.combine(date, datetime.time.max)
        else:
            # If it's already a datetime, just set hours/mins/secs
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        return [d for d in self.downloads if 
                d["user_id"] == user_id and
                d["service"] == service and
                start_of_day <= d["download_date"] <= end_of_day]
    
    def get_download_count_for_today(self, user_id, service):
        """Get the download count for today."""
        today_dt = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        downloads = self.get_user_downloads_for_date(user_id, service, today_dt)
        return len(downloads)
    
    def get_download_limit(self, user_id, service):
        """Get the download limit for a user."""
        today_dt = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        key = f"{user_id}_{service}_{today_dt}"
        
        if key in self.download_limits:
            return self.download_limits[key]
        
        # If no record, check if user has active subscription
        subscription = self.get_active_subscription(user_id, service)
        
        # Default limit is 0 if no subscription
        limit = 0
        
        if subscription:
            # Get plan details from subscription
            plan_id = subscription.get("plan")
            plan = self.get_subscription_plan(service, plan_id)
            
            if plan:
                limit = plan.get("download_limit", 0)
            else:
                # Fallback for legacy subscriptions
                if service == "freepik":
                    if subscription["plan"] == "monthly" or subscription["plan"] == "yearly":
                        limit = 10  # Default limit
        
        # Create new limit record
        limit_record = {
            "user_id": user_id,
            "service": service,
            "date": today_dt,
            "count": 0,
            "limit": limit
        }
        
        self.download_limits[key] = limit_record
        return limit_record
    
    def increment_download_count(self, user_id, service):
        """Increment the download count for today."""
        today_dt = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        key = f"{user_id}_{service}_{today_dt}"
        
        # First ensure we have a record for today
        if key not in self.download_limits:
            self.get_download_limit(user_id, service)
        
        # Increment count
        self.download_limits[key]["count"] += 1
        return True
    
    def can_download(self, user_id, service):
        """Check if user can download more today."""
        limit_record = self.get_download_limit(user_id, service)
        
        # Allow download if count is less than limit
        return limit_record["count"] < limit_record["limit"]
    
    def get_subscription_plans(self, service=None):
        """Get all active subscription plans, optionally filtered by service."""
        if service:
            return [p for p in self.subscription_plans if p["service"] == service and p.get("is_active", True)]
        return [p for p in self.subscription_plans if p.get("is_active", True)]
    
    def get_subscription_plan(self, service, plan_id):
        """Get a specific subscription plan."""
        for plan in self.subscription_plans:
            if (plan["service"] == service and 
                plan["plan_id"] == plan_id and 
                plan.get("is_active", True)):
                return plan
        return None
    
    def add_subscription_plan(self, service, plan_id, name, description, price, 
                             currency, duration_days, download_limit):
        """Add a new subscription plan."""
        plan = {
            "service": service,
            "plan_id": plan_id,
            "name": name,
            "description": description,
            "price": price,
            "currency": currency,
            "duration_days": duration_days,
            "download_limit": download_limit,
            "is_active": True,
            "created_at": datetime.datetime.utcnow()
        }
        
        self.subscription_plans.append(plan)
        return plan
    
    def update_subscription_plan(self, service, plan_id, **kwargs):
        """Update an existing subscription plan."""
        for plan in self.subscription_plans:
            if plan["service"] == service and plan["plan_id"] == plan_id:
                # Update fields
                for key, value in kwargs.items():
                    if key not in ["service", "plan_id", "_id"]:
                        plan[key] = value
                plan["updated_at"] = datetime.datetime.utcnow()
                return True
        return False
    
    def deactivate_subscription_plan(self, service, plan_id):
        """Deactivate a subscription plan."""
        return self.update_subscription_plan(service, plan_id, is_active=False)
        
    def get_user_payments(self, user_id, limit=10):
        """Get a user's payment history, sorted by date descending."""
        user_payments = [p for p in self.payments if p["user_id"] == user_id]
        user_payments.sort(key=lambda x: x["payment_date"], reverse=True)
        return user_payments[:limit]
        
    def count_payments_by_status(self):
        """Count payments grouped by status."""
        status_counts = {}
        for payment in self.payments:
            status = payment["status"]
            if status not in status_counts:
                status_counts[status] = 0
            status_counts[status] += 1
        return status_counts

class Database:
    def __init__(self, connection_string):
        """Initialize database connection."""
        try:
            # Mask sensitive info for logging
            masked_uri = connection_string
            if '@' in masked_uri:
                parts = masked_uri.split('@')
                credentials = parts[0].split('://')
                masked_uri = f"{credentials[0]}://****:****@{parts[1]}"
            logger.info(f"Connecting to MongoDB: {masked_uri}")
            
            # Create MongoClient with proper timeout and retry settings
            self.client = MongoClient(
                connection_string,
                serverSelectionTimeoutMS=10000,  # Increase timeout to 10 seconds
                connectTimeoutMS=20000,
                socketTimeoutMS=30000,
                retryWrites=True,
                retryReads=True,
                maxPoolSize=50,  # Add connection pool size
                minPoolSize=10,  # Maintain minimum connections
                maxIdleTimeMS=45000  # Close idle connections after 45 seconds
            )
            
            # Set database name explicitly from URI or default
            db_name = "freepik_bot"
            if "/" in connection_string and connection_string.split("/")[-1]:
                db_name = connection_string.split("/")[-1].split("?")[0]
            
            logger.info(f"Using database: {db_name}")
            self.db = self.client[db_name]
            
            # Test connection explicitly
            self.client.admin.command('ping')
            logger.info("MongoDB connection successful! Ping command worked.")
            
            # Try to perform a write operation to verify full functionality
            test_result = self.db.connection_test.insert_one({"test": True, "timestamp": datetime.datetime.utcnow()})
            logger.info(f"MongoDB write test successful! Inserted ID: {test_result.inserted_id}")
            
            # Delete the test document to keep the database clean
            self.db.connection_test.delete_one({"_id": test_result.inserted_id})
            logger.info("MongoDB test document deleted successfully.")
            
            # Set connection status
            self.is_connected = True
            
            # Create indexes and initialize default plans
            self._create_indexes()
            self._init_default_plans()
            
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.warning("Falling back to mock database")
            self.is_connected = False
            self.mock_db = MockDatabase()  # Create a new instance
        
    def _create_indexes(self):
        """Create necessary indexes for performance."""
        # User ID index
        self.db.users.create_index("user_id", unique=True)
        self.db.subscriptions.create_index("user_id")
        self.db.subscriptions.create_index("payment_id")  # Add this index for payment relationship
        self.db.subscriptions.create_index("status")      # Add this index for status queries
        self.db.downloads.create_index([("user_id", 1), ("download_date", -1)])
        self.db.downloadLimits.create_index([("user_id", 1), ("service", 1), ("date", 1)], unique=True)
        # Plan indexes
        self.db.subscriptionPlans.create_index([("service", 1), ("plan_id", 1)], unique=True)
        # Payment indexes
        self.db.payments.create_index("user_id")          # Add payment index for user lookup
        self.db.payments.create_index("status")           # Add payment index for status queries
        self.db.payments.create_index("payment_date")     # Add payment index for date sorting
        
        logger.info("MongoDB indexes created successfully")
    
    def _init_default_plans(self):
        """Initialize default subscription plans if they don't exist."""
        default_plans = [
            {
                "service": "freepik",
                "plan_id": "monthly",
                "name": "Monthly",
                "description": "Freepik Monthly Subscription",
                "price": 1500,
                "currency": "LKR",
                "duration_days": 30,
                "download_limit": 10,
                "is_active": True
            },
            {
                "service": "freepik",
                "plan_id": "yearly",
                "name": "Yearly",
                "description": "Freepik Yearly Subscription",
                "price": 5800,
                "currency": "LKR",
                "duration_days": 365,
                "download_limit": 10,
                "is_active": True
            }
        ]
        
        for plan in default_plans:
            # Use upsert to add or update the plans
            result = self.db.subscriptionPlans.update_one(
                {"service": plan["service"], "plan_id": plan["plan_id"]},
                {"$set": plan},
                upsert=True
            )
            if result.upserted_id:
                logger.info(f"Created default plan: {plan['service']} - {plan['plan_id']}")
            elif result.modified_count:
                logger.info(f"Updated default plan: {plan['service']} - {plan['plan_id']}")
    
    def _call_method(self, method_name, *args, **kwargs):
        """Call a method on either the real DB or mock DB based on connection status."""
        if self.is_connected:
            # Call method on self
            method = getattr(self, f"_real_{method_name}")
            result = method(*args, **kwargs)
            logger.debug(f"Called real database method: {method_name}")
            return result
        else:
            # Call method on mock DB
            mock_method = getattr(self.mock_db, method_name)
            result = mock_method(*args, **kwargs)
            logger.debug(f"Called mock database method: {method_name}")
            return result
    
    # User Management
    def get_user(self, user_id):
        return self._call_method("get_user", user_id)
        
    def _real_get_user(self, user_id):
        result = self.db.users.find_one({"user_id": user_id})
        logger.debug(f"Get user {user_id} result: {'Found' if result else 'Not found'}")
        return result
    
    def create_or_update_user(self, user_id, username=None, name=None, first_name=None, last_name=None, telegram_info=None):
        return self._call_method("create_or_update_user", user_id, username, name, first_name, last_name, telegram_info)
        
    def _real_create_or_update_user(self, user_id, username=None, name=None, first_name=None, last_name=None, telegram_info=None):
        """Create or update a user with enhanced information storage."""
        now = datetime.datetime.utcnow()
        
        user = {
            "last_active": now
        }
        
        if username:
            user["username"] = username
        
        if name:
            user["name"] = name
            
        if first_name:
            user["first_name"] = first_name
            
        if last_name:
            user["last_name"] = last_name
            
        if telegram_info:
            user["telegram_info"] = telegram_info
                
        existing_user = self.get_user(user_id)
        
        if existing_user:
            # Update existing user
            result = self.db.users.update_one(
                {"user_id": user_id},
                {"$set": user}
            )
            logger.info(f"Updated user {user_id} in MongoDB: {result.modified_count} document(s) modified")
            return existing_user
        else:
            # Create new user
            user["user_id"] = user_id
            user["registration_date"] = now
            result = self.db.users.insert_one(user)
            logger.info(f"Created new user {user_id} in MongoDB with ID: {result.inserted_id}")
            return user

    def debug_subscription_status(self, user_id, service):
        """Debug why a subscription isn't being recognized."""
        now = datetime.datetime.utcnow()
        logger.info(f"DEBUG: Checking subscription for user_id={user_id}, service={service}, current time={now}")
        
        # If using MongoDB
        if self.is_connected:
            # Check if the subscription exists
            subscription = self.db.subscriptions.find_one({
                "user_id": user_id,
                "service": service
            })
            
            if not subscription:
                logger.info(f"DEBUG: No subscription found for user_id={user_id}, service={service}")
                return False, "No subscription found"
                
            logger.info(f"DEBUG: Found subscription: {subscription}")
            
            # Check if subscription is active
            if subscription.get("status") != "active":
                logger.info(f"DEBUG: Subscription status is '{subscription.get('status')}', not 'active'")
                return False, f"Status is {subscription.get('status')}"
            
            # Check if subscription is expired
            end_date = subscription.get("end_date")
            if not end_date:
                logger.info("DEBUG: Subscription has no end_date")
                return False, "No end_date"
                
            if end_date <= now:
                logger.info(f"DEBUG: Subscription expired on {end_date}")
                return False, f"Expired on {end_date}"
                
            # If we get here, subscription should be valid
            logger.info(f"DEBUG: Subscription is valid until {end_date}")
            return True, f"Valid until {end_date}"
        else:
            # Check in mock database
            for sub in self.mock_db.subscriptions:
                if sub["user_id"] == user_id and sub["service"] == service:
                    logger.info(f"DEBUG: Found mock subscription: {sub}")
                    
                    if sub.get("status") != "active":
                        logger.info(f"DEBUG: Mock subscription status is '{sub.get('status')}', not 'active'")
                        return False, f"Status is {sub.get('status')}"
                    
                    end_date = sub.get("end_date")
                    if not end_date:
                        logger.info("DEBUG: Mock subscription has no end_date")
                        return False, "No end_date"
                        
                    if end_date <= now:
                        logger.info(f"DEBUG: Mock subscription expired on {end_date}")
                        return False, f"Expired on {end_date}"
                        
                    logger.info(f"DEBUG: Mock subscription is valid until {end_date}")
                    return True, f"Valid until {end_date}"
                    
            logger.info(f"DEBUG: No mock subscription found for user_id={user_id}, service={service}")
            return False, "No subscription found"

    # Add this function to check user_id type consistency
    def ensure_user_id_type_consistency(self, user_id):
        """Make sure user_id is consistently handled as an integer."""
        try:
            # Convert to int if it's not already
            user_id_int = int(user_id)
            logger.info(f"Converted user_id from {type(user_id)} to int: {user_id_int}")
            return user_id_int
        except (ValueError, TypeError):
            logger.error(f"Failed to convert user_id {user_id} to int")
            return user_id
    
    # Subscription Management
    def get_active_subscription(self, user_id, service):
        return self._call_method("get_active_subscription", user_id, service)
        
    def _real_get_active_subscription(self, user_id, service):
        """Get active subscription for a user for a specific service."""
        now = datetime.datetime.utcnow()
        
        # Ensure user_id is an integer
        user_id = self.ensure_user_id_type_consistency(user_id)
        
        # Log debugging information
        logger.info(f"Getting active subscription for user_id={user_id}, service={service}, time={now}")
        
        # First, try with proper query
        result = self.db.subscriptions.find_one({
            "user_id": user_id,
            "service": service,
            "end_date": {"$gt": now},
            "status": "active"
        })
        
        if result:
            logger.info(f"Found active subscription for user {user_id} with ID {result.get('_id')}")
        else:
            # Try finding with looser query to debug the issue
            all_subs = list(self.db.subscriptions.find({"user_id": user_id}))
            if all_subs:
                logger.info(f"User {user_id} has {len(all_subs)} subscriptions, but none match active criteria")
                for i, sub in enumerate(all_subs):
                    logger.info(f"Subscription {i+1}: service={sub.get('service')}, status={sub.get('status')}, end_date={sub.get('end_date')}")
                    if sub.get('service') == service:
                        if sub.get('status') != 'active':
                            logger.info(f"  - Status issue: {sub.get('status')} != 'active'")
                        if 'end_date' in sub and sub['end_date'] <= now:
                            logger.info(f"  - Date issue: {sub['end_date']} <= {now}")
            else:
                logger.info(f"No subscriptions found for user {user_id}")
        
        return result
    
    def get_all_user_subscriptions(self, user_id):
        return self._call_method("get_all_user_subscriptions", user_id)
        
    def _real_get_all_user_subscriptions(self, user_id):
        result = list(self.db.subscriptions.find({"user_id": user_id}).sort("end_date", -1))
        logger.debug(f"Get all subscriptions for user {user_id}: Found {len(result)} subscriptions")
        return result
    
    def create_subscription(self, user_id, service, plan, payment_id=None):
        return self._call_method("create_subscription", user_id, service, plan, payment_id)
        
    def _real_create_subscription(self, user_id, service, plan, payment_id=None):
        """Create a subscription with status history tracking."""
        now = datetime.datetime.utcnow()
        
        # Get plan details from database
        plan_details = self.get_subscription_plan(service, plan)
        
        if plan_details:
            # Calculate end date based on plan duration
            duration_days = plan_details.get("duration_days", 30)  # Default to 30 days
            end_date = now + datetime.timedelta(days=duration_days)
        else:
            # Fallback for legacy plans
            if plan == "monthly":
                end_date = now + datetime.timedelta(days=30)
            elif plan == "yearly":
                end_date = now + datetime.timedelta(days=365)
            else:
                raise ValueError(f"Invalid plan: {plan}")
        
        subscription = {
            "user_id": user_id,
            "service": service,
            "plan": plan,
            "start_date": now,
            "end_date": end_date,
            "status": "pending",
            "payment_id": payment_id,
            "created_at": now,
            "last_status_update": now,
            "status_history": [
                {
                    "status": "pending",
                    "timestamp": now,
                    "notes": "Subscription created, awaiting payment verification"
                }
            ]
        }
        
        result = self.db.subscriptions.insert_one(subscription)
        subscription["_id"] = result.inserted_id
        logger.info(f"Created subscription for user {user_id}, service {service}, plan {plan} with ID: {result.inserted_id}")
        return subscription
    
    def activate_subscription(self, subscription_id):
        return self._call_method("activate_subscription", subscription_id)
        
    def _real_activate_subscription(self, subscription_id):
        """Activate a subscription with additional tracking information."""
        now = datetime.datetime.utcnow()
        
        # Update subscription status and add activation timestamp
        result = self.db.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {
                "$set": {
                    "status": "active",
                    "activated_at": now,
                    "last_status_update": now
                },
                "$push": {
                    "status_history": {
                        "status": "active",
                        "timestamp": now,
                        "notes": "Subscription activated"
                    }
                }
            }
        )
        logger.info(f"Activated subscription {subscription_id}: {result.modified_count} document(s) modified")
        return result.modified_count > 0
    
    # Payment Management
    def create_payment(self, user_id, amount, service, plan, image_url, image_file_id=None, 
                      image_file_path=None, notes="", payment_date=None, currency="LKR"):
        return self._call_method("create_payment", user_id, amount, service, plan, image_url, 
                               image_file_id, image_file_path, notes, payment_date, currency)
        
    def _real_create_payment(self, user_id, amount, service, plan, image_url, image_file_id=None, 
                           image_file_path=None, notes="", payment_date=None, currency="LKR"):
        """Create a payment record with enhanced image and status tracking."""
        if payment_date is None:
            payment_date = datetime.datetime.utcnow()
            
        payment = {
            "user_id": user_id,
            "amount": amount,
            "currency": currency,
            "service": service,
            "plan": plan,
            "payment_date": payment_date,
            "image_url": image_url,
            "status": "pending",
            "admin_notes": ""
        }
        
        # Add additional fields if provided
        if image_file_id:
            payment["image_file_id"] = image_file_id
            
        if image_file_path:
            payment["image_file_path"] = image_file_path
            
        if notes:
            payment["user_notes"] = notes
        
        # Add status tracking fields
        payment["status_history"] = [
            {
                "status": "pending",
                "timestamp": payment_date,
                "notes": "Payment proof received"
            }
        ]
        
        result = self.db.payments.insert_one(payment)
        payment["_id"] = result.inserted_id
        logger.info(f"Created payment record for user {user_id}, service {service}, plan {plan} with ID: {result.inserted_id}")
        return payment
    
    def get_payment(self, payment_id):
        return self._call_method("get_payment", payment_id)
        
    def _real_get_payment(self, payment_id):
        try:
            result = self.db.payments.find_one({"_id": ObjectId(payment_id)})
            logger.debug(f"Get payment {payment_id}: {'Found' if result else 'Not found'}")
            return result
        except Exception as e:
            logger.error(f"Error retrieving payment {payment_id}: {e}")
            return None
    
    def get_pending_payments(self, with_details=False):
        return self._call_method("get_pending_payments", with_details)
        
    def _real_get_pending_payments(self, with_details=False):
        """
        Get pending payments with optional user details.
        
        Args:
            with_details: If True, include user details with each payment
        """
        query = {"status": "pending"}
        
        if with_details:
            # Use aggregation to join with users collection
            pipeline = [
                {"$match": query},
                {"$sort": {"payment_date": 1}},
                {
                    "$lookup": {
                        "from": "users",
                        "localField": "user_id",
                        "foreignField": "user_id",
                        "as": "user_details"
                    }
                },
                {
                    "$addFields": {
                        "user_details": {"$arrayElemAt": ["$user_details", 0]}
                    }
                }
            ]
            result = list(self.db.payments.aggregate(pipeline))
            logger.debug(f"Get pending payments with details: Found {len(result)} payments")
            return result
        else:
            # Simple query
            result = list(self.db.payments.find(query).sort("payment_date", 1))
            logger.debug(f"Get pending payments: Found {len(result)} payments")
            return result
    
    def update_payment_status(self, payment_id, status, admin_notes=None):
        return self._call_method("update_payment_status", payment_id, status, admin_notes)
        
    def _real_update_payment_status(self, payment_id, status, admin_notes=None):
        """Update payment status with history tracking."""
        now = datetime.datetime.utcnow()
        
        # Create status history entry
        status_history_entry = {
            "status": status,
            "timestamp": now,
            "notes": admin_notes if admin_notes else f"Status changed to {status}"
        }
        
        update = {
            "$set": {
                "status": status,
                "last_updated": now
            },
            "$push": {
                "status_history": status_history_entry
            }
        }
        
        if admin_notes:
            update["$set"]["admin_notes"] = admin_notes
            
        try:
            result = self.db.payments.update_one(
                {"_id": ObjectId(payment_id)},
                update
            )
            logger.info(f"Updated payment {payment_id} status to {status}: {result.modified_count} document(s) modified")
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating payment status for {payment_id}: {e}")
            return False
    
    # Download Management
    def record_download(self, user_id, service, resource_url, file_name, file_size):
        return self._call_method("record_download", user_id, service, resource_url, file_name, file_size)
        
    def _real_record_download(self, user_id, service, resource_url, file_name, file_size):
        download = {
            "user_id": user_id,
            "service": service,
            "resource_url": resource_url,
            "download_date": datetime.datetime.utcnow(),
            "file_name": file_name,
            "file_size": file_size
        }
        
        result = self.db.downloads.insert_one(download)
        download["_id"] = result.inserted_id
        logger.info(f"Recorded download in MongoDB for user {user_id}, document ID: {result.inserted_id}")
        return download
    
    def get_user_downloads(self, user_id, service, limit=10):
        return self._call_method("get_user_downloads", user_id, service, limit)
        
    def _real_get_user_downloads(self, user_id, service, limit=10):
        result = list(self.db.downloads.find(
            {"user_id": user_id, "service": service}
        ).sort("download_date", -1).limit(limit))
        logger.debug(f"Get user downloads for {user_id}, service {service}: Found {len(result)} downloads")
        return result
    
    def get_user_downloads_for_date(self, user_id, service, date):
        return self._call_method("get_user_downloads_for_date", user_id, service, date)
        
    def _real_get_user_downloads_for_date(self, user_id, service, date):
        """Get downloads for a user on a specific date with proper datetime handling."""
        # Convert date to datetime if needed
        if isinstance(date, datetime.date) and not isinstance(date, datetime.datetime):
            start_of_day = datetime.datetime.combine(date, datetime.time.min)
            end_of_day = datetime.datetime.combine(date, datetime.time.max)
        else:
            # If it's already a datetime, just set hours/mins/secs
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        result = list(self.db.downloads.find({
            "user_id": user_id,
            "service": service,
            "download_date": {
                "$gte": start_of_day,
                "$lte": end_of_day
            }
        }))
        logger.debug(f"Get user downloads for {user_id}, service {service}, date {date.strftime('%Y-%m-%d')}: Found {len(result)} downloads")
        return result
    
    def get_download_count_for_today(self, user_id, service):
        return self._call_method("get_download_count_for_today", user_id, service)
        
    def _real_get_download_count_for_today(self, user_id, service):
        """Get the download count for today with proper datetime handling."""
        today_dt = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        downloads = self.get_user_downloads_for_date(user_id, service, today_dt)
        return len(downloads)
    
    # Download Limits
    def get_download_limit(self, user_id, service):
        return self._call_method("get_download_limit", user_id, service)
        
    def _real_get_download_limit(self, user_id, service):
        """Get download limit for a user with proper datetime handling and daily reset."""
        # Use datetime object consistently, not date
        today_utc = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Check if we have a record for today
        limit_record = self.db.downloadLimits.find_one({
            "user_id": user_id,
            "service": service,
            "date": today_utc  # Use datetime object, not date
        })
        
        if limit_record:
            logger.debug(f"Found existing download limit record for user {user_id}, service {service}")
            return limit_record
        
        # If no record for today, check if user has active subscription
        subscription = self.get_active_subscription(user_id, service)
        
        # Default limit is 0 if no subscription
        limit = 0
        
        if subscription:
            # Get plan details from subscription
            plan_id = subscription.get("plan")
            plan = self.get_subscription_plan(service, plan_id)
            
            if plan:
                limit = plan.get("download_limit", 0)
            else:
                # Fallback for legacy subscriptions
                if service == "freepik":
                    if subscription["plan"] == "monthly" or subscription["plan"] == "yearly":
                        limit = 10  # Default limit
        
        # Create new limit record for today with count reset to 0
        limit_record = {
            "user_id": user_id,
            "service": service,
            "date": today_utc,  # Use datetime object consistently
            "count": 0,
            "limit": limit,
            "created_at": datetime.datetime.utcnow()
        }
        
        result = self.db.downloadLimits.insert_one(limit_record)
        logger.info(f"Created new download limit record for user {user_id}, service {service} with ID: {result.inserted_id}")
        return limit_record
    
    def increment_download_count(self, user_id, service):
        return self._call_method("increment_download_count", user_id, service)
        
    def _real_increment_download_count(self, user_id, service):
        """Increment download count with proper datetime handling."""
        # Use datetime object consistently, not date
        today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # First ensure we have a record for today
        self.get_download_limit(user_id, service)
        
        # Increment count
        result = self.db.downloadLimits.update_one(
            {
                "user_id": user_id,
                "service": service,
                "date": today  # Use datetime object, not date
            },
            {"$inc": {"count": 1}}
        )
        
        logger.info(f"Incremented download count for user {user_id}, service {service}: {result.modified_count} document(s) modified")
        return result.modified_count > 0
    
    def can_download(self, user_id, service):
        return self._call_method("can_download", user_id, service)
        
    def _real_can_download(self, user_id, service):
        limit_record = self.get_download_limit(user_id, service)
        
        # Allow download if count is less than limit
        can_download = limit_record["count"] < limit_record["limit"]
        logger.debug(f"Can user {user_id} download from {service}? {can_download} ({limit_record['count']}/{limit_record['limit']})")
        return can_download
    
    # Subscription Plan Management
    def get_subscription_plans(self, service=None):
        return self._call_method("get_subscription_plans", service)
        
    def _real_get_subscription_plans(self, service=None):
        filter_query = {"is_active": True}
        if service:
            filter_query["service"] = service
            
        result = list(self.db.subscriptionPlans.find(filter_query))
        logger.debug(f"Get subscription plans for service {service if service else 'all'}: Found {len(result)} plans")
        return result
    
    def get_subscription_plan(self, service, plan_id):
        return self._call_method("get_subscription_plan", service, plan_id)
        
    def _real_get_subscription_plan(self, service, plan_id):
        result = self.db.subscriptionPlans.find_one({
            "service": service,
            "plan_id": plan_id,
            "is_active": True
        })
        logger.debug(f"Get subscription plan {service}/{plan_id}: {'Found' if result else 'Not found'}")
        return result
    
    def add_subscription_plan(self, service, plan_id, name, description, price, 
                             currency, duration_days, download_limit):
        return self._call_method("add_subscription_plan", service, plan_id, name, 
                                description, price, currency, duration_days, download_limit)
        
    def _real_add_subscription_plan(self, service, plan_id, name, description, price, 
                             currency, duration_days, download_limit):
        plan = {
            "service": service,
            "plan_id": plan_id,
            "name": name,
            "description": description,
            "price": price,
            "currency": currency,
            "duration_days": duration_days,
            "download_limit": download_limit,
            "is_active": True,
            "created_at": datetime.datetime.utcnow()
        }
        
        result = self.db.subscriptionPlans.insert_one(plan)
        plan["_id"] = result.inserted_id
        logger.info(f"Added subscription plan {service}/{plan_id} with ID: {result.inserted_id}")
        return plan
    
    def update_subscription_plan(self, service, plan_id, **kwargs):
        return self._call_method("update_subscription_plan", service, plan_id, **kwargs)
        
    def _real_update_subscription_plan(self, service, plan_id, **kwargs):
        # Remove immutable fields from kwargs
        kwargs.pop("service", None)
        kwargs.pop("plan_id", None)
        kwargs.pop("_id", None)
        
        # Add update timestamp
        kwargs["updated_at"] = datetime.datetime.utcnow()
        
        result = self.db.subscriptionPlans.update_one(
            {"service": service, "plan_id": plan_id},
            {"$set": kwargs}
        )
        
        logger.info(f"Updated subscription plan {service}/{plan_id}: {result.modified_count} document(s) modified")
        return result.modified_count > 0
    
    def deactivate_subscription_plan(self, service, plan_id):
        return self._call_method("deactivate_subscription_plan", service, plan_id)
        
    def _real_deactivate_subscription_plan(self, service, plan_id):
        result = self.update_subscription_plan(service, plan_id, is_active=False)
        logger.info(f"Deactivated subscription plan {service}/{plan_id}: {result}")
        return result
        
    # Enhanced payment methods
    def get_user_payments(self, user_id, limit=10):
        return self._call_method("get_user_payments", user_id, limit)
        
    def _real_get_user_payments(self, user_id, limit=10):
        """Get a user's payment history, sorted by date descending."""
        result = list(self.db.payments.find(
            {"user_id": user_id}
        ).sort("payment_date", -1).limit(limit))
        logger.debug(f"Get user payments for {user_id}: Found {len(result)} payments")
        return result
    
    def count_payments_by_status(self):
        return self._call_method("count_payments_by_status")
        
    def _real_count_payments_by_status(self):
        """Count payments grouped by status."""
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        
        result = list(self.db.payments.aggregate(pipeline))
        counts = {item["_id"]: item["count"] for item in result}
        logger.debug(f"Payment counts by status: {counts}")
        return counts