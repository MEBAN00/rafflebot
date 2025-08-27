import asyncio
import logging
import os
from dotenv import load_dotenv  # Load environment variables
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from database import Database
from paystack_handler import PaystackHandler
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# Reduce APScheduler and HTTP noise
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

class RaffleBot:
    def __init__(self):
        self.db = Database()
        self.paystack = PaystackHandler()
        
        self.TICKET_PRICE = int(os.getenv('TICKET_PRICE', 1000))  # Price in kobo (10 NGN)
        self.MAX_TICKETS = int(os.getenv('MAX_TICKETS', 1000))
        self.RAFFLE_TITLE = os.getenv('RAFFLE_TITLE', 'Friends Raffle Draw 2025')

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        
        # Register user in database
        self.db.add_user(user.id, user.username, user.first_name, user.last_name)
        
        welcome_text = f"""
Raffle Draw 2025

Hi {user.first_name}! Ready to try your luck?

Ticket Price: ₦{self.TICKET_PRICE/100:.0f}
Total Tickets Available: {self.MAX_TICKETS}
Sold Tickets: {self.db.get_total_tickets_sold()}

Use the buttons below to get started!
        """
        
        keyboard = [
            [InlineKeyboardButton("Buy Tickets", callback_data="buy_tickets")],
            [InlineKeyboardButton("My Tickets", callback_data="my_tickets")],
            [InlineKeyboardButton("Raffle Info", callback_data="raffle_info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if query.data == "buy_tickets":
            await self.show_buy_tickets(query)
        elif query.data == "my_tickets":
            await self.show_my_tickets(query, user_id)
        elif query.data == "raffle_info":
            await self.show_raffle_info(query)
        elif query.data.startswith("buy_"):
            ticket_count = int(query.data.split("_")[1])
            await self.initiate_payment(query, user_id, ticket_count)
        elif query.data.startswith("confirm_payment_"):
            reference = query.data.replace("confirm_payment_", "")
            await self.confirm_payment(query, user_id, reference)
        elif query.data == "back_to_menu":
            await self.start_from_callback(query)

    async def show_buy_tickets(self, query):
        """Show ticket purchase options"""
        sold_tickets = self.db.get_total_tickets_sold()
        available_tickets = self.MAX_TICKETS - sold_tickets
        
        if available_tickets <= 0:
            await query.edit_message_text("Sorry, all tickets have been sold!")
            return
            
        text = f"""
Buy Raffle Tickets

Available Tickets: {available_tickets}
Price per ticket: ₦{self.TICKET_PRICE/100:.0f}

How many tickets would you like to buy?
        """
        
        keyboard = []
        for count in [1, 2, 5, 10]:
            if count <= available_tickets:
                total_price = (count * self.TICKET_PRICE) / 100
                keyboard.append([InlineKeyboardButton(
                    f"{count} ticket{'s' if count > 1 else ''} - ₦{total_price:.0f}", 
                    callback_data=f"buy_{count}"
                )])
        
        keyboard.append([InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup)

    async def show_my_tickets(self, query, user_id):
        """Show user's purchased tickets"""
        tickets = self.db.get_user_tickets(user_id)
        
        if not tickets:
            text = "You haven't purchased any tickets yet!"
        else:
            ticket_numbers = [str(ticket[2]) for ticket in tickets]  # ticket_number is index 2
            text = f"""
Your Raffle Tickets

Total Tickets: {len(tickets)}
Ticket Numbers: {', '.join(ticket_numbers)}

Good luck!
            """
        
        keyboard = [[InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup)

    async def show_raffle_info(self, query):
        """Show raffle information"""
        sold_tickets = self.db.get_total_tickets_sold()
        
        text = f"""
{self.RAFFLE_TITLE}

Total Tickets: {self.MAX_TICKETS}
Sold Tickets: {sold_tickets}
Ticket Price: ₦{self.TICKET_PRICE/100:.0f}
Prize Pool: ₦{(sold_tickets * self.TICKET_PRICE * 0.8)/100:.0f}

Draw Date: TBA
Winner Selection: Random draw

Good luck to all participants!
        """
        
        keyboard = [[InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup)

    async def initiate_payment(self, query, user_id, ticket_count):
        """Initiate Paystack payment"""
        user = query.from_user
        amount = ticket_count * self.TICKET_PRICE
        
        # Check if enough tickets are available
        sold_tickets = self.db.get_total_tickets_sold()
        if sold_tickets + ticket_count > self.MAX_TICKETS:
            await query.edit_message_text("Not enough tickets available!")
            return
        
        try:
            # Create a proper email format that Paystack will accept
            if user.username:
                email = f"{user.username}.telegram@example.com"
            else:
                email = f"user{user_id}.telegram@example.com"
            
            # Create payment with Paystack
            payment_data = self.paystack.initialize_payment(
                email=email,
                amount=amount,
                reference=f"raffle_{user_id}_{ticket_count}_{int(asyncio.get_event_loop().time())}",
                metadata={
                    "user_id": user_id,
                    "ticket_count": ticket_count,
                    "username": user.username or f"user{user_id}",
                    "telegram_user_id": user_id
                }
            )
            
            if payment_data:
                # Store pending payment
                self.db.add_pending_payment(
                    user_id, 
                    payment_data['reference'], 
                    ticket_count, 
                    amount
                )
                
                text = f"""
Payment Required

Tickets: {ticket_count}
Amount: ₦{amount/100:.0f}

Click "Pay Now" to complete payment, then click "Confirm Payment" after you've paid:
                """
                
                keyboard = [
                    [InlineKeyboardButton("Pay Now", url=payment_data['authorization_url'])],
                    [InlineKeyboardButton("Confirm Payment", callback_data=f"confirm_payment_{payment_data['reference']}")],
                    [InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(text, reply_markup=reply_markup)
            else:
                await query.edit_message_text("Payment initialization failed. Please try again.")
                
        except Exception as e:
            logger.error(f"Payment initialization error: {e}")
            await query.edit_message_text("Something went wrong. Please try again later.")

    async def check_payments(self, context: ContextTypes.DEFAULT_TYPE):
        """Periodically check for completed payments"""
        pending_payments = self.db.get_pending_payments()
        
        for payment in pending_payments:
            user_id, reference, ticket_count, amount = payment
            
            # Verify payment with Paystack
            if self.paystack.verify_payment(reference):
                # Payment successful - assign tickets
                ticket_numbers = self.db.assign_tickets(user_id, ticket_count, reference)
                
                if ticket_numbers:
                    # Notify user
                    try:
                        # Send text summary
                        summary = f"Payment Successful!\nYour tickets: {', '.join(map(str, ticket_numbers))}"
                        await context.bot.send_message(chat_id=user_id, text=summary)
                        # Send ticket images
                        await self._send_ticket_images(context, user_id, ticket_numbers)
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id}: {e}")
                
                # Remove from pending payments
                self.db.remove_pending_payment(reference)

    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command to show statistics"""
        user_id = update.effective_user.id
        
        admin_ids_str = os.getenv('ADMIN_IDS', '')
        ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip().isdigit()]
        
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("Access denied.")
            return
        
        stats = self.db.get_stats()
        
        text = f"""
Raffle Statistics

Total Tickets Sold: {stats['total_tickets']}
Total Participants: {stats['total_users']}
Total Revenue: ₦{stats['total_revenue']/100:.0f}
Pending Payments: {stats['pending_payments']}

Available Tickets: {self.MAX_TICKETS - stats['total_tickets']}
        """
        
        await update.message.reply_text(text)

    async def confirm_payment(self, query, user_id, reference):
        """Handle manual payment confirmation"""
        try:
            # Verify payment with Paystack
            if self.paystack.verify_payment(reference):
                # Get pending payment details
                pending_payment = self.db.get_pending_payment_by_reference(reference)
                
                if pending_payment:
                    _, _, ticket_count, amount = pending_payment
                    
                    # Payment successful - assign tickets
                    ticket_numbers = self.db.assign_tickets(user_id, ticket_count, reference)
                    
                    if ticket_numbers:
                        text = f"""
Payment Confirmed Successfully!

Your tickets have been assigned:
Numbers: {', '.join(map(str, ticket_numbers))}
Amount Paid: ₦{amount/100:.0f}

Good luck in the draw!
                        """
                        
                        # Remove from pending payments
                        self.db.remove_pending_payment(reference)
                        
                        keyboard = [[InlineKeyboardButton("Back to Menu", callback_data="back_to_menu")]]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        await query.edit_message_text(text, reply_markup=reply_markup)
                        # Send ticket images
                        await self._send_ticket_images_from_query(query, ticket_numbers)
                    else:
                        await query.edit_message_text("Error assigning tickets. Please contact admin.")
                else:
                    await query.edit_message_text("Payment reference not found. Please try again.")
            else:
                await query.edit_message_text("""
Payment not yet confirmed by Paystack.

Please ensure you have completed the payment, then try again in a few minutes.
If you've paid and still see this message, please contact admin.
                """)
                
        except Exception as e:
            logger.error(f"Payment confirmation error: {e}")
            await query.edit_message_text("Error confirming payment. Please try again or contact admin.")

    async def start_from_callback(self, query):
        """Handle start command from callback query"""
        user = query.from_user
        
        welcome_text = f"""
{self.RAFFLE_TITLE}

Hi {user.first_name}! Ready to try your luck?

Ticket Price: ₦{self.TICKET_PRICE/100:.0f}
Total Tickets Available: {self.MAX_TICKETS}
Sold Tickets: {self.db.get_total_tickets_sold()}

Use the buttons below to get started!
        """
        
        keyboard = [
            [InlineKeyboardButton("Buy Tickets", callback_data="buy_tickets")],
            [InlineKeyboardButton("My Tickets", callback_data="my_tickets")],
            [InlineKeyboardButton("Raffle Info", callback_data="raffle_info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(welcome_text, reply_markup=reply_markup)

    async def admin_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command to show comprehensive dashboard"""
        user_id = update.effective_user.id
        
        admin_ids_str = os.getenv('ADMIN_IDS', '')
        ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip().isdigit()]
        
        if user_id not in ADMIN_IDS:
            await update.message.reply_text("Access denied.")
            return
        
        stats = self.db.get_stats()
        recent_tickets = self.db.get_recent_tickets(10)  # Get last 10 tickets
        
        text = f"""
🎯 ADMIN DASHBOARD 🎯

📊 STATISTICS:
• Total Tickets Sold: {stats['total_tickets']}
• Total Participants: {stats['total_users']}
• Total Revenue: ₦{stats['total_revenue']/100:.0f}
• Pending Payments: {stats['pending_payments']}
• Available Tickets: {self.MAX_TICKETS - stats['total_tickets']}

📋 RECENT ACTIVITY:
        """
        
        if recent_tickets:
            text += "\nLast 10 tickets sold:\n"
            for ticket in recent_tickets:
                user_id_ticket, ticket_num, purchase_time = ticket
                text += f"• Ticket #{ticket_num} - User {user_id_ticket} - {purchase_time}\n"
        else:
            text += "\nNo tickets sold yet.\n"
        
        text += f"\n💰 Prize Pool: ₦{(stats['total_revenue'] * 0.8)/100:.0f} (80% of revenue)"
        
        await update.message.reply_text(text)

    async def _send_ticket_images(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, ticket_numbers):
        """Generate and send ticket images to a user by chat_id."""
        for number in ticket_numbers:
            try:
                image = self._generate_ticket_image(number)
                with self._pil_image_to_bytes(image) as bio:
                    await context.bot.send_photo(chat_id=chat_id, photo=bio, caption=f"Ticket #{number}")
            except Exception as e:
                logger.error(f"Failed to send ticket image for {number} to {chat_id}: {e}")

    async def _send_ticket_images_from_query(self, query, ticket_numbers):
        """Generate and send ticket images using the callback query context."""
        chat_id = query.from_user.id
        for number in ticket_numbers:
            try:
                image = self._generate_ticket_image(number)
                with self._pil_image_to_bytes(image) as bio:
                    await query.message.reply_photo(photo=bio, caption=f"Ticket #{number}")
            except Exception as e:
                logger.error(f"Failed to send ticket image for {number} to {chat_id}: {e}")

    def _generate_ticket_image(self, ticket_number: int):
        """Overlay the ticket number centered on local template image ticket.png."""
        try:
            template_path = os.path.join(os.path.dirname(__file__), 'ticket.png')
            base = Image.open(template_path)
        except Exception as e:
            logger.error(f"Failed to open ticket.png template, falling back to solid background: {e}")
            base = Image.new('RGB', (800, 450), color=(245, 245, 245))

        # Ensure RGB for JPEG output
        if base.mode not in ('RGB', 'L'):
            base = base.convert('RGB')

        draw = ImageDraw.Draw(base)

        # Scale font relative to image size
        width, height = base.size
        number_font_size = max(48, int(min(width, height) * 0.28))
        try:
            font_number = ImageFont.truetype("arialbd.ttf", number_font_size)
        except Exception:
            try:
                font_number = ImageFont.truetype("arial.ttf", number_font_size)
            except Exception:
                font_number = ImageFont.load_default()

        number_text = f"#{ticket_number}"
        number_bbox = draw.textbbox((0, 0), number_text, font=font_number)
        number_w = number_bbox[2] - number_bbox[0]
        number_h = number_bbox[3] - number_bbox[1]

        # Slight shadow for readability
        center_x = (width - number_w) / 2
        center_y = (height - number_h) / 2
        shadow_offset = max(1, number_font_size // 40)
        try:
            draw.text((center_x + shadow_offset, center_y + shadow_offset), number_text, fill=(0, 0, 0), font=font_number)
        except Exception:
            pass
        draw.text((center_x, center_y), number_text, fill=(20, 20, 20), font=font_number)

        return base

    def _pil_image_to_bytes(self, image: Image.Image):
        """Convert PIL Image to BytesIO (JPEG, optimized) for telegram upload."""
        from io import BytesIO
        bio = BytesIO()
        image.save(bio, format='JPEG', quality=85, optimize=True)
        bio.seek(0)
        return bio

def main():
    """Start the bot"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    if not BOT_TOKEN:
        print("ERROR: Please set your BOT_TOKEN in the .env file!")
        return
    
    bot = RaffleBot()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("stats", bot.admin_stats))
    application.add_handler(CommandHandler("admin", bot.admin_dashboard))
    application.add_handler(CallbackQueryHandler(bot.button_handler))
    
    # Add job to check payments every 30 seconds
    job_queue = application.job_queue
    if job_queue is not None:
        job_queue.run_repeating(bot.check_payments, interval=30, first=10)
        print("SUCCESS: Payment checking job scheduled")
    else:
        print("WARNING: JobQueue not available - install with: pip install 'python-telegram-bot[job-queue]'")
    
    print("STARTING: Raffle bot is starting...")
    print("INFO: Send /start to your bot to begin!")
    
    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
