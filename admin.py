import os
import logging
import argparse
import webbrowser
import subprocess
import datetime
from dotenv import load_dotenv
from tabulate import tabulate
from database import Database

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def load_database():
    """Load environment variables and initialize the database."""
    load_dotenv()
    
    mongodb_uri = os.getenv("MONGODB_URI")
    if not mongodb_uri:
        raise EnvironmentError("MONGODB_URI environment variable is not set.")
    
    return Database(mongodb_uri)

def list_pending_payments(db):
    """List all pending payments with enhanced details."""
    try:
        payments = db.get_pending_payments(with_details=True)
        
        if not payments:
            print("No pending payments found.")
            return
        
        # Format payment data for display
        table_data = []
        for payment in payments:
            payment_id = str(payment["_id"])
            user_id = payment["user_id"]
            amount = payment["amount"]
            currency = payment.get("currency", "LKR")
            service = payment["service"].capitalize()
            plan = payment["plan"].capitalize()
            payment_date = payment["payment_date"].strftime("%Y-%m-%d %H:%M:%S")
            
            # Add username if available from joined user_details
            username = "Unknown"
            name = "Unknown"
            if "user_details" in payment and payment["user_details"]:
                username = payment["user_details"].get("username", "Unknown")
                name = payment["user_details"].get("name", "Unknown")
            
            table_data.append([
                payment_id[:8] + "...",  # Truncate ID for display
                user_id,
                username,
                name[:15] + "..." if len(name) > 15 else name,  # Limit name length
                f"{amount} {currency}",
                f"{service} {plan}",
                payment_date
            ])
        
        # Print table
        print("\nPending Payments:")
        print(tabulate(
            table_data,
            headers=["ID", "User ID", "Username", "Name", "Amount", "Plan", "Date"],
            tablefmt="grid"
        ))
        
        # Show command hint
        print("\nUse the following commands to manage payments:")
        print("  view-payment <payment_id> - View payment details")
        print("  view-image <payment_id> - View payment receipt image")
        print("  approve <payment_id> - Approve payment and activate subscription")
        print("  reject <payment_id> - Reject payment")
    except Exception as e:
        print(f"Error listing pending payments: {e}")

def list_recent_payments(db, limit=20):
    """List all recent payments, regardless of status."""
    try:
        # Use aggregation to get payments with user details
        pipeline = [
            {"$sort": {"payment_date": -1}},
            {"$limit": limit},
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
        
        payments = list(db.db.payments.aggregate(pipeline))
        
        if not payments:
            print("No payment records found.")
            return
        
        # Format payment data for display
        table_data = []
        for payment in payments:
            payment_id = str(payment["_id"])
            user_id = payment["user_id"]
            amount = payment["amount"]
            currency = payment.get("currency", "LKR")
            service = payment["service"].capitalize()
            plan = payment["plan"].capitalize()
            payment_date = payment["payment_date"].strftime("%Y-%m-%d %H:%M:%S")
            status = payment["status"].upper()
            
            # Add username if available from joined user_details
            username = "Unknown"
            if "user_details" in payment and payment["user_details"]:
                username = payment["user_details"].get("username", "Unknown")
            
            table_data.append([
                payment_id[:8] + "...",  # Truncate ID for display
                user_id,
                username,
                f"{amount} {currency}",
                f"{service} {plan}",
                status,
                payment_date
            ])
        
        # Print table
        print(f"\nRecent Payments (Latest {len(payments)}):")
        print(tabulate(
            table_data,
            headers=["ID", "User ID", "Username", "Amount", "Plan", "Status", "Date"],
            tablefmt="grid"
        ))
    except Exception as e:
        print(f"Error listing recent payments: {e}")

def payment_statistics(db):
    """Show payment statistics."""
    try:
        # Get payment counts by status
        status_counts = db.count_payments_by_status()
        
        # Get payment counts by service
        pipeline = [
            {"$group": {"_id": "$service", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        service_counts = list(db.db.payments.aggregate(pipeline))
        service_data = {item["_id"]: item["count"] for item in service_counts}
        
        # Get payment totals by month
        pipeline = [
            {
                "$project": {
                    "yearMonth": {"$dateToString": {"format": "%Y-%m", "date": "$payment_date"}},
                    "amount": 1,
                    "currency": 1
                }
            },
            {
                "$group": {
                    "_id": {
                        "yearMonth": "$yearMonth",
                        "currency": "$currency"
                    },
                    "count": {"$sum": 1},
                    "totalAmount": {"$sum": "$amount"}
                }
            },
            {"$sort": {"_id.yearMonth": -1}}
        ]
        monthly_data = list(db.db.payments.aggregate(pipeline))
        
        # Print status statistics
        print("\nPayment Status Statistics:")
        status_table = []
        for status, count in status_counts.items():
            status_table.append([status.upper(), count])
        print(tabulate(status_table, headers=["Status", "Count"], tablefmt="grid"))
        
        # Print service statistics
        if service_data:
            print("\nPayment Service Statistics:")
            service_table = []
            for service, count in service_data.items():
                service_table.append([service.capitalize(), count])
            print(tabulate(service_table, headers=["Service", "Count"], tablefmt="grid"))
        
        # Print monthly statistics
        if monthly_data:
            print("\nMonthly Payment Statistics:")
            monthly_table = []
            for data in monthly_data:
                year_month = data["_id"]["yearMonth"]
                currency = data["_id"]["currency"]
                count = data["count"]
                total = data["totalAmount"]
                monthly_table.append([year_month, count, f"{total:,.2f} {currency}"])
            print(tabulate(monthly_table, headers=["Month", "Count", "Total Amount"], tablefmt="grid"))
        
    except Exception as e:
        print(f"Error generating payment statistics: {e}")

def view_payment(db, payment_id):
    """View payment details."""
    # Get payment
    payment = db.get_payment(payment_id)
    if not payment:
        print(f"Payment with ID {payment_id} not found.")
        return
    
    # Get user info
    user_id = payment["user_id"]
    user = db.get_user(user_id)
    
    # Get subscription info
    subscriptions = db.get_all_user_subscriptions(user_id)
    linked_subscription = None
    for sub in subscriptions:
        if "payment_id" in sub and str(sub["payment_id"]) == str(payment_id):
            linked_subscription = sub
            break
    
    # Print payment details
    print("\nPayment Details:")
    print(f"ID: {payment_id}")
    print(f"User ID: {user_id}")
    print(f"Username: {user.get('username') if user else 'Unknown'}")
    print(f"Name: {user.get('name') if user else 'Unknown'}")
    print(f"Amount: {payment['amount']} {payment.get('currency', 'LKR')}")
    print(f"Service: {payment['service'].capitalize()}")
    print(f"Plan: {payment['plan'].capitalize()}")
    print(f"Payment Date: {payment['payment_date'].strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Status: {payment['status'].capitalize()}")
    
    # Print payment image info
    if "image_url" in payment:
        print(f"Image URL: {payment['image_url']}")
    if "image_file_path" in payment and payment["image_file_path"]:
        print(f"Local Image Path: {payment['image_file_path']}")
    if "image_file_id" in payment:
        print(f"Telegram File ID: {payment['image_file_id']}")
    
    # Print user notes if available
    if "user_notes" in payment and payment["user_notes"]:
        print(f"User Notes: {payment['user_notes']}")
    
    # Print admin notes if available
    if payment.get("admin_notes"):
        print(f"Admin Notes: {payment['admin_notes']}")
    
    # Print status history if available
    if "status_history" in payment and payment["status_history"]:
        print("\nStatus History:")
        for i, history in enumerate(payment["status_history"], 1):
            status = history["status"].capitalize()
            timestamp = history["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            notes = history.get("notes", "")
            print(f"  {i}. {status} - {timestamp}")
            if notes:
                print(f"     Notes: {notes}")
    
    # Print linked subscription details
    if linked_subscription:
        sub_status = linked_subscription["status"].capitalize()
        sub_start = linked_subscription["start_date"].strftime("%Y-%m-%d")
        sub_end = linked_subscription["end_date"].strftime("%Y-%m-%d")
        
        print("\nLinked Subscription:")
        print(f"ID: {linked_subscription['_id']}")
        print(f"Status: {sub_status}")
        print(f"Start Date: {sub_start}")
        print(f"End Date: {sub_end}")
        
        if "activated_at" in linked_subscription:
            print(f"Activated At: {linked_subscription['activated_at'].strftime('%Y-%m-%d %H:%M:%S')}")

def view_payment_image(db, payment_id):
    """Open the payment receipt image if available."""
    payment = db.get_payment(payment_id)
    if not payment:
        print(f"Payment with ID {payment_id} not found.")
        return
    
    # Check if there's a local file path
    if "image_file_path" in payment and payment["image_file_path"]:
        file_path = payment["image_file_path"]
        if os.path.exists(file_path):
            print(f"Opening payment receipt image: {file_path}")
            # Try to open the image with the default viewer
            try:
                # Try using webbrowser module first
                webbrowser.open(file_path)
                print("Image opened in default viewer.")
            except Exception as e:
                print(f"Failed to open image with webbrowser: {e}")
                
                # Try platform-specific methods
                try:
                    # For Windows
                    if os.name == 'nt':
                        os.startfile(file_path)
                    # For macOS
                    elif os.name == 'posix' and os.uname().sysname == 'Darwin':
                        subprocess.call(['open', file_path])
                    # For Linux
                    elif os.name == 'posix':
                        subprocess.call(['xdg-open', file_path])
                    print("Image opened in default viewer using system command.")
                except Exception as e2:
                    print(f"Failed to open image using system commands: {e2}")
                    print(f"Image path: {file_path}")
        else:
            print(f"Image file not found at: {file_path}")
    elif "image_url" in payment:
        print(f"Image URL: {payment['image_url']}")
        try:
            webbrowser.open(payment['image_url'])
            print("Opening image URL in browser...")
        except Exception as e:
            print(f"Failed to open URL: {e}")
            print("You can copy and paste the URL into your browser.")
    else:
        print("No image associated with this payment.")

def approve_payment(db, payment_id, admin_notes=""):
    """Approve a payment and activate the subscription."""
    # Get payment
    payment = db.get_payment(payment_id)
    if not payment:
        print(f"Payment with ID {payment_id} not found.")
        return
    
    # Check if payment is already approved
    if payment["status"] == "approved":
        print(f"Payment {payment_id} is already approved.")
        return
    
    # Update payment status
    db.update_payment_status(payment_id, "approved", admin_notes or "Approved via admin tool")
    
    # Find and activate subscription associated with this payment
    user_id = payment["user_id"]
    service = payment["service"]
    plan = payment["plan"]
    
    subscriptions = db.get_all_user_subscriptions(user_id)
    subscription_activated = False
    
    for sub in subscriptions:
        if "payment_id" in sub and str(sub["payment_id"]) == str(payment_id):
            db.activate_subscription(sub["_id"])
            subscription_activated = True
            break
    
    if subscription_activated:
        print(f"✅ Payment {payment_id} approved and subscription activated for user {user_id}.")
        print(f"Service: {service}, Plan: {plan}")
    else:
        print(f"✅ Payment {payment_id} approved but no linked subscription found.")
        print("Please check the database directly to activate the subscription.")
    
    # Notification would typically be sent via the Telegram bot
    print("NOTE: User will be notified via Telegram when the bot is running.")

def reject_payment(db, payment_id, admin_notes="Rejected payment"):
    """Reject a payment."""
    # Get payment
    payment = db.get_payment(payment_id)
    if not payment:
        print(f"Payment with ID {payment_id} not found.")
        return
    
    # Check if payment is already rejected
    if payment["status"] == "rejected":
        print(f"Payment {payment_id} is already rejected.")
        return
    
    # Update payment status
    db.update_payment_status(payment_id, "rejected", admin_notes)
    
    print(f"❌ Payment {payment_id} rejected.")
    print("NOTE: User will be notified via Telegram when the bot is running.")

def list_subscription_plans(db, service=None):
    """List all subscription plans, optionally filtered by service."""
    plans = db.get_subscription_plans(service)
    
    if not plans:
        print(f"No subscription plans found{' for ' + service if service else ''}.")
        return
    
    # Format plan data for display
    table_data = []
    for plan in plans:
        service = plan["service"].capitalize()
        plan_id = plan["plan_id"]
        name = plan["name"]
        price = f"{plan['price']} {plan['currency']}"
        download_limit = plan["download_limit"]
        duration = f"{plan['duration_days']} days"
        status = "Active" if plan.get("is_active", True) else "Inactive"
        
        table_data.append([
            service,
            plan_id,
            name,
            price,
            download_limit,
            duration,
            status
        ])
    
    # Print table
    print("\nSubscription Plans:")
    print(tabulate(
        table_data,
        headers=["Service", "ID", "Name", "Price", "Daily Limit", "Duration", "Status"],
        tablefmt="grid"
    ))

def add_subscription_plan(db, service, plan_id, name, description, price, currency, duration_days, download_limit):
    """Add a new subscription plan."""
    try:
        plan = db.add_subscription_plan(
            service, plan_id, name, description, 
            float(price), currency, int(duration_days), int(download_limit)
        )
        print(f"✅ Subscription plan '{plan_id}' for {service} added successfully.")
    except Exception as e:
        print(f"❌ Error adding subscription plan: {e}")

def update_subscription_plan(db, service, plan_id, **kwargs):
    """Update an existing subscription plan."""
    try:
        # Convert numeric values
        if "price" in kwargs:
            kwargs["price"] = float(kwargs["price"])
        if "download_limit" in kwargs:
            kwargs["download_limit"] = int(kwargs["download_limit"])
        if "duration_days" in kwargs:
            kwargs["duration_days"] = int(kwargs["duration_days"])
        
        success = db.update_subscription_plan(service, plan_id, **kwargs)
        if success:
            print(f"✅ Subscription plan '{plan_id}' for {service} updated successfully.")
        else:
            print(f"❌ Plan not found or no changes were made.")
    except Exception as e:
        print(f"❌ Error updating subscription plan: {e}")

def deactivate_subscription_plan(db, service, plan_id):
    """Deactivate a subscription plan."""
    success = db.deactivate_subscription_plan(service, plan_id)
    if success:
        print(f"✅ Subscription plan '{plan_id}' for {service} deactivated successfully.")
    else:
        print(f"❌ Plan not found or already inactive.")

def list_user_subscriptions(db, user_id):
    """List all subscriptions for a specific user."""
    try:
        # Get user information
        user = db.get_user(user_id)
        if not user:
            print(f"User with ID {user_id} not found.")
            return
        
        # Get all subscriptions
        subscriptions = db.get_all_user_subscriptions(user_id)
        
        # Print user information
        print(f"\nUser Information:")
        print(f"ID: {user_id}")
        print(f"Username: {user.get('username', 'Unknown')}")
        print(f"Name: {user.get('name', 'Unknown')}")
        
        if not subscriptions:
            print("\nNo subscriptions found for this user.")
            return
        
        # Format subscription data for display
        table_data = []
        for sub in subscriptions:
            service = sub["service"].capitalize()
            plan = sub["plan"].capitalize()
            status = sub["status"].capitalize()
            start_date = sub["start_date"].strftime("%Y-%m-%d")
            end_date = sub["end_date"].strftime("%Y-%m-%d")
            
            # Calculate days left for active subscriptions
            days_left = ""
            if status.lower() == "active":
                now = datetime.datetime.utcnow()
                if sub["end_date"] > now:
                    days_left = (sub["end_date"] - now).days
            
            subscription_id = str(sub["_id"])
            
            table_data.append([
                subscription_id[:8] + "...",  # Truncate ID for display
                service,
                plan,
                status,
                start_date,
                end_date,
                days_left
            ])
        
        # Print table
        print("\nUser's Subscriptions:")
        print(tabulate(
            table_data,
            headers=["ID", "Service", "Plan", "Status", "Start Date", "End Date", "Days Left"],
            tablefmt="grid"
        ))
        
    except Exception as e:
        print(f"Error listing user subscriptions: {e}")

def get_user_info(db, user_id=None, username=None):
    """Get detailed information about a user by ID or username."""
    try:
        user = None
        if user_id:
            user = db.get_user(user_id)
        elif username:
            # Search for user by username (case-insensitive)
            pipeline = [
                {"$match": {"username": {"$regex": f"^{username}$", "$options": "i"}}},
                {"$limit": 1}
            ]
            users = list(db.db.users.aggregate(pipeline))
            if users:
                user = users[0]
        
        if not user:
            print(f"User not found{'.' if user_id else ' with username ' + username + '.'}")
            return
        
        # Print basic user information
        print("\nUser Information:")
        print(f"ID: {user['user_id']}")
        print(f"Username: {user.get('username', 'Not set')}")
        print(f"Name: {user.get('name', 'Not set')}")
        print(f"First Name: {user.get('first_name', 'Not set')}")
        print(f"Last Name: {user.get('last_name', 'Not set')}")
        
        # Print registration and activity info
        if "registration_date" in user:
            print(f"Registered: {user['registration_date'].strftime('%Y-%m-%d %H:%M:%S')}")
        if "last_active" in user:
            print(f"Last Active: {user['last_active'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Print Telegram info if available
        if "telegram_info" in user and user["telegram_info"]:
            print("\nTelegram Information:")
            for key, value in user["telegram_info"].items():
                print(f"  {key.capitalize()}: {value}")
        
        # Get user's active subscriptions
        subscriptions = db.get_all_user_subscriptions(user["user_id"])
        active_subs = [s for s in subscriptions if s["status"] == "active"]
        
        if active_subs:
            print("\nActive Subscriptions:")
            for sub in active_subs:
                service = sub["service"].capitalize()
                plan = sub["plan"].capitalize()
                end_date = sub["end_date"].strftime("%Y-%m-%d")
                days_left = (sub["end_date"] - datetime.datetime.utcnow()).days
                
                print(f"  {service} {plan}")
                print(f"    Expires: {end_date} ({days_left} days left)")
        else:
            print("\nNo active subscriptions found.")
        
        # Get user's download limits
        try:
            today = datetime.datetime.utcnow().date()
            limit_info = db.get_download_limit(user["user_id"], "freepik")
            
            if limit_info:
                print("\nDownload Limits (Today):")
                print(f"  Freepik: {limit_info['count']}/{limit_info['limit']} downloads used")
        except Exception as e:
            print(f"Error getting download limits: {e}")
        
        # Get recent user payments
        try:
            payments = db.get_user_payments(user["user_id"], limit=5)
            
            if payments:
                print("\nRecent Payments:")
                for payment in payments:
                    service = payment["service"].capitalize()
                    plan = payment["plan"].capitalize()
                    amount = payment["amount"]
                    currency = payment.get("currency", "LKR")
                    status = payment["status"].capitalize()
                    date = payment["payment_date"].strftime("%Y-%m-%d")
                    
                    print(f"  {service} {plan}: {amount} {currency} - {status} ({date})")
            else:
                print("\nNo payment history found.")
        except Exception as e:
            print(f"Error getting payment history: {e}")
        
    except Exception as e:
        print(f"Error retrieving user information: {e}")

def main():
    """Main entry point for the admin CLI."""
    parser = argparse.ArgumentParser(description="Admin panel for Freepik Downloader Bot")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # List pending payments
    list_parser = subparsers.add_parser("list-payments", help="List pending payments")
    
    # List recent payments
    recent_parser = subparsers.add_parser("recent-payments", help="List recent payments")
    recent_parser.add_argument("--limit", type=int, default=20, help="Number of payments to show")
    
    # Payment statistics
    stats_parser = subparsers.add_parser("payment-stats", help="Show payment statistics")
    
    # View payment details
    view_parser = subparsers.add_parser("view-payment", help="View payment details")
    view_parser.add_argument("payment_id", help="Payment ID to view")
    
    # View payment image
    view_image_parser = subparsers.add_parser("view-image", help="View payment receipt image")
    view_image_parser.add_argument("payment_id", help="Payment ID")
    
    # Approve payment
    approve_parser = subparsers.add_parser("approve", help="Approve a payment")
    approve_parser.add_argument("payment_id", help="Payment ID to approve")
    approve_parser.add_argument("--notes", help="Admin notes", default="")
    
    # Reject payment
    reject_parser = subparsers.add_parser("reject", help="Reject a payment")
    reject_parser.add_argument("payment_id", help="Payment ID to reject")
    reject_parser.add_argument("--notes", help="Admin notes", default="Rejected payment")
    
    # Subscription plan management
    plans_parser = subparsers.add_parser("list-plans", help="List subscription plans")
    plans_parser.add_argument("--service", help="Filter by service", default=None)
    
    add_plan_parser = subparsers.add_parser("add-plan", help="Add a subscription plan")
    add_plan_parser.add_argument("service", help="Service (e.g., freepik)")
    add_plan_parser.add_argument("plan_id", help="Plan ID (e.g., premium)")
    add_plan_parser.add_argument("name", help="Plan name (e.g., Premium)")
    add_plan_parser.add_argument("description", help="Plan description")
    add_plan_parser.add_argument("price", help="Price (numeric)")
    add_plan_parser.add_argument("currency", help="Currency code (e.g., LKR)")
    add_plan_parser.add_argument("duration_days", help="Duration in days")
    add_plan_parser.add_argument("download_limit", help="Daily download limit")
    
    update_plan_parser = subparsers.add_parser("update-plan", help="Update a subscription plan")
    update_plan_parser.add_argument("service", help="Service (e.g., freepik)")
    update_plan_parser.add_argument("plan_id", help="Plan ID (e.g., premium)")
    update_plan_parser.add_argument("--name", help="Plan name")
    update_plan_parser.add_argument("--description", help="Plan description")
    update_plan_parser.add_argument("--price", help="Price")
    update_plan_parser.add_argument("--currency", help="Currency code")
    update_plan_parser.add_argument("--duration_days", help="Duration in days")
    update_plan_parser.add_argument("--download_limit", help="Daily download limit")
    
    deactivate_plan_parser = subparsers.add_parser("deactivate-plan", help="Deactivate a subscription plan")
    deactivate_plan_parser.add_argument("service", help="Service (e.g., freepik)")
    deactivate_plan_parser.add_argument("plan_id", help="Plan ID (e.g., premium)")
    
    # User management
    user_subs_parser = subparsers.add_parser("user-subscriptions", help="List a user's subscriptions")
    user_subs_parser.add_argument("user_id", type=int, help="User ID")
    
    user_info_parser = subparsers.add_parser("user-info", help="Get detailed user information")
    user_info_group = user_info_parser.add_mutually_exclusive_group(required=True)
    user_info_group.add_argument("--id", type=int, help="User ID")
    user_info_group.add_argument("--username", help="Username")
    
    args = parser.parse_args()
    
    # Load database
    try:
        db = load_database()
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        return
    
    # Execute command
    if args.command == "list-payments":
        list_pending_payments(db)
    elif args.command == "recent-payments":
        list_recent_payments(db, args.limit)
    elif args.command == "payment-stats":
        payment_statistics(db)
    elif args.command == "view-payment":
        view_payment(db, args.payment_id)
    elif args.command == "view-image":
        view_payment_image(db, args.payment_id)
    elif args.command == "approve":
        approve_payment(db, args.payment_id, args.notes)
    elif args.command == "reject":
        reject_payment(db, args.payment_id, args.notes)
    elif args.command == "list-plans":
        list_subscription_plans(db, args.service)
    elif args.command == "add-plan":
        add_subscription_plan(
            db, args.service, args.plan_id, args.name, args.description,
            args.price, args.currency, args.duration_days, args.download_limit
        )
    elif args.command == "update-plan":
        kwargs = {k: v for k, v in vars(args).items() 
                 if k not in ["command", "service", "plan_id"] and v is not None}
        update_subscription_plan(db, args.service, args.plan_id, **kwargs)
    elif args.command == "deactivate-plan":
        deactivate_subscription_plan(db, args.service, args.plan_id)
    elif args.command == "user-subscriptions":
        list_user_subscriptions(db, args.user_id)
    elif args.command == "user-info":
        get_user_info(db, args.id, args.username)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()