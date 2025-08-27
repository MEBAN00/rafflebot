import pymongo
import random
import logging
import os
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        """
        Initialize MongoDB connection using environment variables
        For production, use: mongodb+srv://username:password@cluster.mongodb.net/
        For local development: mongodb://localhost:27017/
        """
        connection_string = os.getenv('MONGODB_URL')
        db_name = os.getenv('MONGODB_DB_NAME')
        
        self.client = MongoClient(connection_string)
        self.db = self.client[db_name]
        self.users = self.db.users
        self.tickets = self.db.tickets
        self.pending_payments = self.db.pending_payments
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required indexes"""
        try:
            # Create indexes for better performance
            self.users.create_index("user_id", unique=True)
            self.tickets.create_index("ticket_number", unique=True)
            self.tickets.create_index("user_id")
            self.pending_payments.create_index("reference", unique=True)
            
            logger.info("MongoDB database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
    
    def add_user(self, user_id, username, first_name, last_name):
        """Add or update user in database"""
        try:
            user_data = {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "created_at": datetime.utcnow()
            }
            
            # Use upsert to insert or update
            self.users.update_one(
                {"user_id": user_id},
                {"$set": user_data},
                upsert=True
            )
            logger.info(f"User {user_id} added/updated successfully")
        except Exception as e:
            logger.error(f"Error adding user: {e}")
    
    def get_total_tickets_sold(self):
        """Get total number of tickets sold"""
        try:
            count = self.tickets.count_documents({})
            return count
        except Exception as e:
            logger.error(f"Error getting total tickets: {e}")
            return 0
    
    def get_user_tickets(self, user_id):
        """Get all tickets for a specific user"""
        try:
            tickets = list(self.tickets.find(
                {"user_id": user_id},
                {"_id": 0, "user_id": 1, "ticket_number": 1, "payment_reference": 1, "created_at": 1}
            ).sort("ticket_number", 1))
            
            return tickets
        except Exception as e:
            logger.error(f"Error getting user tickets: {e}")
            return []
    
    def add_pending_payment(self, user_id, reference, ticket_count, amount):
        """Add a pending payment"""
        try:
            payment_data = {
                "user_id": user_id,
                "reference": reference,
                "ticket_count": ticket_count,
                "amount": amount,
                "created_at": datetime.utcnow()
            }
            
            self.pending_payments.insert_one(payment_data)
            logger.info(f"Pending payment added: {reference}")
        except pymongo.errors.DuplicateKeyError:
            logger.warning(f"Pending payment already exists: {reference}")
        except Exception as e:
            logger.error(f"Error adding pending payment: {e}")
    
    def get_pending_payments(self):
        """Get all pending payments"""
        try:
            payments = list(self.pending_payments.find(
                {},
                {"_id": 0, "user_id": 1, "reference": 1, "ticket_count": 1, "amount": 1}
            ))
            return payments
        except Exception as e:
            logger.error(f"Error getting pending payments: {e}")
            return []

    def get_pending_payment_by_reference(self, reference):
        """Get a single pending payment by its reference.

        Returns tuple (user_id, reference, ticket_count, amount) or None
        """
        try:
            doc = self.pending_payments.find_one(
                {"reference": reference},
                {"_id": 0, "user_id": 1, "reference": 1, "ticket_count": 1, "amount": 1}
            )
            if not doc:
                return None
            return (
                doc.get("user_id"),
                doc.get("reference"),
                doc.get("ticket_count"),
                doc.get("amount"),
            )
        except Exception as e:
            logger.error(f"Error getting pending payment by reference: {e}")
            return None
    
    def remove_pending_payment(self, reference):
        """Remove a pending payment"""
        try:
            result = self.pending_payments.delete_one({"reference": reference})
            if result.deleted_count > 0:
                logger.info(f"Pending payment removed: {reference}")
            else:
                logger.warning(f"Pending payment not found: {reference}")
        except Exception as e:
            logger.error(f"Error removing pending payment: {e}")
    
    def assign_tickets(self, user_id, ticket_count, payment_reference):
        """Assign random ticket numbers to a user"""
        try:
            # Get existing ticket numbers
            existing_tickets = self.tickets.find({}, {"ticket_number": 1, "_id": 0})
            existing_numbers = {ticket["ticket_number"] for ticket in existing_tickets}
            
            # Generate available numbers (1-1000)
            available_numbers = list(set(range(1, 1001)) - existing_numbers)
            
            if len(available_numbers) < ticket_count:
                logger.error(f"Not enough tickets available. Requested: {ticket_count}, Available: {len(available_numbers)}")
                return None
            
            # Select random ticket numbers
            selected_numbers = random.sample(available_numbers, ticket_count)
            
            # Prepare ticket documents
            ticket_documents = []
            for number in selected_numbers:
                ticket_documents.append({
                    "user_id": user_id,
                    "ticket_number": number,
                    "payment_reference": payment_reference,
                    "created_at": datetime.utcnow()
                })
            
            # Insert tickets
            self.tickets.insert_many(ticket_documents)
            
            logger.info(f"Assigned {ticket_count} tickets to user {user_id}: {selected_numbers}")
            return selected_numbers
            
        except Exception as e:
            logger.error(f"Error assigning tickets: {e}")
            return None
    
    def get_stats(self):
        """Get raffle statistics"""
        try:
            # Total tickets sold
            total_tickets = self.tickets.count_documents({})
            
            # Total unique users
            total_users = len(self.tickets.distinct("user_id"))
            
            ticket_price = int(os.getenv('TICKET_PRICE', 1000))
            total_revenue = total_tickets * ticket_price
            
            # Pending payments
            pending_payments = self.pending_payments.count_documents({})
            
            return {
                "total_tickets": total_tickets,
                "total_users": total_users,
                "total_revenue": total_revenue,
                "pending_payments": pending_payments
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "total_tickets": 0,
                "total_users": 0,
                "total_revenue": 0,
                "pending_payments": 0
            }
    
    def get_recent_tickets(self, limit=10):
        """Get the most recently sold tickets.

        Returns list of tuples: (user_id, ticket_number, created_at)
        """
        try:
            cursor = self.tickets.find(
                {},
                {"_id": 0, "user_id": 1, "ticket_number": 1, "created_at": 1}
            ).sort("created_at", -1).limit(int(limit))

            recent = []
            for doc in cursor:
                recent.append((doc.get("user_id"), doc.get("ticket_number"), doc.get("created_at")))
            return recent
        except Exception as e:
            logger.error(f"Error getting recent tickets: {e}")
            return []

    def get_all_tickets(self):
        """Get all sold tickets (for draw purposes)"""
        try:
            # Use aggregation to join tickets with users
            pipeline = [
                {
                    "$lookup": {
                        "from": "users",
                        "localField": "user_id",
                        "foreignField": "user_id",
                        "as": "user_info"
                    }
                },
                {
                    "$unwind": "$user_info"
                },
                {
                    "$project": {
                        "_id": 0,
                        "ticket_number": 1,
                        "user_id": 1,
                        "username": "$user_info.username",
                        "first_name": "$user_info.first_name"
                    }
                },
                {
                    "$sort": {"ticket_number": 1}
                }
            ]
            
            tickets = list(self.tickets.aggregate(pipeline))
            return tickets
            
        except Exception as e:
            logger.error(f"Error getting all tickets: {e}")
            return []
    
    def close_connection(self):
        """Close MongoDB connection"""
        try:
            self.client.close()
            logger.info("MongoDB connection closed")
        except Exception as e:
            logger.error(f"Error closing connection: {e}")
