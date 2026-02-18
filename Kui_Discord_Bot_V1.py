from typing import Final
import os
from dotenv import load_dotenv
import database  # Import database functions
import discord
from discord.ext import commands
from discord import app_commands
import datetime
import casino_games
import asyncio


ADMIN_USERS = {205834382026473472}  # JinxedBread Discord ID for Special Permissions

# Load Discord token from .env
load_dotenv()
TOKEN: Final[str] = os.getenv('DISCORD_TOKEN')

# Bot Setup with Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Required for member lookups in slash commands

bot = commands.Bot(command_prefix=")", intents=intents)

# 🔹 Sync Commands on Bot Startup
@bot.event
async def on_ready():
    print(f'{bot.user} is now running!')
    await database.init_db()  # Initialize database on startup
    try:
        await bot.tree.sync()  # Sync slash commands with Discord
        print("✅ Slash commands synced successfully!")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

# 🔹 Add Users to Database When They Join the Server
@bot.event
async def on_member_join(member):
    user_id = member.id
    username = member.name  # Get Discord username
    server_id = member.guild.id

    # Add user to database
    await database.add_user(user_id, username, server_id)

    print(f"Added {username} ({user_id}) to the database.")




@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return  # Ignore bot messages

    user_id = message.author.id
    username = message.author.name  # Get username
    server_id = message.guild.id

    # Ensure user is in the database
    await database.add_user(user_id, username, server_id)

    await bot.process_commands(message)




@bot.tree.command(name="leaderboard_local", description="View the richest players in this server")
async def leaderboard_local(interaction: discord.Interaction):
    server_id = interaction.guild.id
    leaderboard_data = await database.get_local_leaderboard(server_id)

    if not leaderboard_data:
        await interaction.response.send_message("❌ No data available yet!", ephemeral=True)
        return

    embed = discord.Embed(title=f"🏆 {interaction.guild.name} Leaderboard", color=discord.Color.gold())
    
    for i, entry in enumerate(leaderboard_data, start=1):
        user = interaction.guild.get_member(entry["user_id"]) or f"<@{entry['user_id']}>"
        embed.add_field(name=f"#{i} {user}", value=f"💰 {entry['balance']} coins", inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard_global", description="View the richest players across all servers")
async def leaderboard_global(interaction: discord.Interaction):
    leaderboard_data = await database.get_global_leaderboard()

    if not leaderboard_data:
        await interaction.response.send_message("❌ No data available yet!", ephemeral=True)
        return

    embed = discord.Embed(title="🌍 Global Leaderboard", color=discord.Color.blue())

    trophy_emojis = ["🥇", "🥈", "🥉"]  # Gold, Silver, Bronze for top 3

    for i, entry in enumerate(leaderboard_data, start=1):
        user = bot.get_user(entry["user_id"])  # Fetch user from bot's cache
        username = user.display_name if user else f"<@{entry['user_id']}>"  # Fallback if user not cached

        # Assign trophies for top 3, default to 🏆 for others
        rank_emoji = trophy_emojis[i - 1] if i <= 3 else "🏆"

        embed.add_field(name=f"{rank_emoji} #{i} {username}", value=f"💰 {entry['balance']} coins", inline=False)

    await interaction.response.send_message(embed=embed)








# 🔹 Slash Command: `/balance` (Dropdown Member Selection)
@bot.tree.command(name="balance", description="Check your balance or another user's balance")
@app_commands.describe(member="Select a user (optional)")
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    # If no user is selected, check the sender's balance
    if member is None:
        member = interaction.user

    user_id = member.id
    username = member.display_name

    # Retrieve balance from database
    bal = await database.get_balance(user_id)

    await interaction.response.send_message(f"💰 {username}'s balance is: {bal} coins.")  # Private message


@bot.tree.command(name="send_money", description="Send another person some money from your balance")
@app_commands.describe(member="Select a user", amount="Amount of coins to send")
async def send_money(interaction: discord.Interaction, member: discord.Member, amount: int):

    sender_user_id = interaction.user.id
    receiver_user_id = member.id

    # Prevent self-transfers
    if sender_user_id == receiver_user_id:
        await interaction.response.send_message("❌ You cannot send coins to yourself!", ephemeral=True)
        return

    # Get sender's balance
    sender_balance = await database.get_balance(sender_user_id)

    # Check if the amount is valid
    if amount <= 0 or amount > sender_balance:
        await interaction.response.send_message(f"❌ You don't have enough coins! Your balance is {sender_balance}.", ephemeral=True)
        return

    # Perform transaction
    await database.update_balance(sender_user_id, -amount)
    await database.update_balance(receiver_user_id, amount)

    await interaction.response.send_message(f"🎉 **{interaction.user.mention} sent {amount} coins to {member.mention}!**", ephemeral=False)



# 🔹 Slash Command: `/addcoins` (Admins Can Give Coins)
@bot.tree.command(name="addcoins", description="Admins can add coins to a user's balance")
@app_commands.describe(member="Select a user", amount="Amount of coins to add")
async def addcoins(interaction: discord.Interaction, member: discord.Member, amount: int):
    # Check if user is an admin
    if interaction.user.id not in ADMIN_USERS:
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return

    user_id = member.id  # Get Discord ID

    # Add coins
    await database.update_balance(user_id, amount)

    await interaction.response.send_message(f"✅ {member.display_name} has received {amount} coins!")



#Daily rewards
@bot.tree.command(name="daily", description="Claim your daily reward. Resets at midnight EST.")
async def daily(interaction: discord.Interaction):
    user_id = interaction.user.id
    username = interaction.user.display_name

    # Get last claim date from database
    last_claim_date = await database.get_last_claim(user_id)

    # Get today's date in EST
    now = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=-5)))  # Convert to EST
    today = now.date()  # Get YYYY-MM-DD

    # Check if user already claimed today
    if last_claim_date == today:
        await interaction.response.send_message("⏳ You have already claimed your daily reward today! Try again tomorrow.")
        return

    # Give user coins and update last claim date
    reward_amount = 100
    await database.update_balance(user_id, reward_amount)
    await database.update_last_claim(user_id)  # Save today's date

    await interaction.response.send_message(f"✅ {username}, you have claimed your daily reward of {reward_amount} coins!")








#COINFLIP IMPLEMENTATION
@bot.tree.command(name="coinflip", description="Bet coins on a coin flip!")
@app_commands.describe(amount="The amount to wager", choice="Heads or Tails")
async def coinflip(interaction: discord.Interaction, amount: int, choice: str):
    await casino_games.coinflip(interaction, amount, choice)





#RUSSIAN ROULLETTE IMPLEMENTATION
@bot.tree.command(name="russianroulette_solo", description="Play Russian Roulette solo.")
@app_commands.describe(amount="Amount to wager", chambers="Number of chambers (2-8)")
async def russianroulette_solo(interaction: discord.Interaction, amount: int, chambers: int):
    if chambers not in range(2, 9):
        await interaction.response.send_message("❌ Please choose a number of chambers between 2 and 8.", ephemeral=True)
        return

    user_id = interaction.user.id
    await casino_games.russianroulette_solo(interaction, amount, chambers, user_id)


@bot.tree.command(name="russianroulette_multi", description="Start an open Russian Roulette game where anyone can join.")
@app_commands.describe(amount="Amount to wager")
async def russianroulette_multi(interaction: discord.Interaction, amount: int):
    await interaction.response.defer()

    user_id = interaction.user.id
    server_id = interaction.guild.id
    user_ids = [user_id]  # The host is automatically included

    # **Save the game session as OPEN JOIN in SQL**
    game_id = await database.create_invitation(user_id, server_id, user_ids)

    # **Send the join prompt**
    class AcceptDeclineView(discord.ui.View):
        def __init__(self, game_id):
            super().__init__(timeout=30)
            self.game_id = game_id

        @discord.ui.button(label="Join ✅", style=discord.ButtonStyle.success, custom_id="join_button")
        async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):

            user_id = interaction.user.id
            if await database.is_already_in_game(self.game_id, user_id):
                await interaction.response.send_message("❌ You already joined!", ephemeral=True)
                return
            await database.add_player_to_game(self.game_id, user_id)
            await interaction.response.send_message(f"✅ {interaction.user.display_name} joined the game!", ephemeral=False)

    view = AcceptDeclineView(game_id)

    await interaction.followup.send(
        "🔫 **Russian Roulette Open Game Started!**\n"
        "Anyone in the server can join by clicking **Join ✅**.\n"
        "Game will start in 10 seconds.",
        view=view,
        ephemeral=False
    )

    await asyncio.sleep(10)  # Wait for players to join

    # **Retrieve final players from SQL**
    final_players: list = await database.get_accepted_players(game_id)

    if len(final_players) < 2:
        await interaction.followup.send("❌ Not enough players joined. Game canceled.", ephemeral=False)
        await database.delete_invitation(game_id)  # Clean up
        return

    # **Start the game with joined players**
    # 🔹 Disable the join button to prevent spam after the game starts
    for child in view.children:
        if isinstance(child, discord.ui.Button) and child.custom_id == "join_button":
            child.disabled = True

    await interaction.edit_original_response(view=view)  # ✅ Updates the message to disable the button

    # 🔹 Start the game
    await casino_games.russianroulette_multi(interaction, amount, 8, final_players)


    await interaction.followup.send(
        f"🔫 **Multiplayer Russian Roulette Started!**\n"
        f"Players: {', '.join(f'<@{uid}>' for uid in final_players)}\n"
        f"First player: <@{final_players[0]}>",
        ephemeral=False
    )

    # **Delete the invitation data from SQL**
    await database.delete_invitation(game_id)



@bot.tree.command(name="crash", description="Play the Crash game: withdraw before the multiplier crashes!")
@app_commands.describe(amount="Bet amount")
async def crash_game(interaction: discord.Interaction, amount: int):
    await casino_games.crash(interaction, amount)



# 🔹 Main Entry Point
def main():
    bot.run(TOKEN)

if __name__ == '__main__':
    main()


#MMO levels system for making coins, higher levels allow for more income
#Coins found randomly by being active
#Timer based Fishing
#custom roles based on performance
#Stat tracker
