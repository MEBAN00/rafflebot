"""
🎯 Raffle Draw Script

Run this script when you're ready to conduct the draw.
It will randomly select a winner from all sold tickets.
"""

import random
from database import Database

def conduct_draw():
    """Conduct the raffle draw"""
    db = Database()
    
    # Get all tickets
    tickets = db.get_all_tickets()
    
    if not tickets:
        print("❌ No tickets have been sold yet!")
        return
    
    print(f"🎟️ Total tickets sold: {len(tickets)}")
    print("🎯 Conducting draw...")
    print("." * 20)
    
    # Random selection
    winner_ticket = random.choice(tickets)
    ticket_number, user_id, username, first_name = winner_ticket
    
    print(f"""
🎉 WINNER SELECTED! 🎉

🎟️ Winning Ticket: #{ticket_number}
👤 Winner: {first_name} (@{username if username else f'user{user_id}'})
🆔 User ID: {user_id}

Congratulations! 🎊
    """)
    
    # Show some statistics
    stats = db.get_stats()
    prize_pool = stats['total_revenue'] * 0.8  # 80% of revenue as prize
    
    print(f"""
📊 Draw Statistics:
💰 Total Revenue: ₦{stats['total_revenue']/100:.0f}
🏆 Prize Pool (80%): ₦{prize_pool/100:.0f}
👥 Total Participants: {stats['total_users']}
    """)

if __name__ == "__main__":
    conduct_draw()
