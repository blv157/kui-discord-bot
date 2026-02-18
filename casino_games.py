import random
import database
import discord
from discord import app_commands
import json
import asyncio
import math
import time

async def coinflip(interaction: discord.Interaction, amount: int, choice: str):
    user_id = interaction.user.id

    choice = choice.lower()
    if choice not in ["heads", "tails"]:
        await interaction.response.send_message("❌ Invalid choice! Please pick `Heads` or `Tails`.", ephemeral=True)
        return


    # Get user's balance
    balance = await database.get_balance(user_id)

    if amount <= 0 or amount > balance:
        await interaction.response.send_message(f"❌ You don't have enough coins! Your balance is {balance}.")
        return

    # Perform coin flip
    outcome = random.choice(["heads", "tails"])
    win = choice == outcome

    if win:
        await database.update_balance(user_id, amount)  # Double the bet
        await interaction.response.send_message(f"🎉 The coin landed on **{outcome}**! You won {amount} coins!", ephemeral=False)
    else:
        await database.update_balance(user_id, -amount)  # Deduct the bet
        await interaction.response.send_message(f"💀 The coin landed on **{outcome}**. You lost {amount} coins!", ephemeral=False)




class RussianRouletteSoloView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.user_id = user_id

    @discord.ui.button(label="Shoot 🔫", style=discord.ButtonStyle.danger)
    async def shoot_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return
        await shoot_solo(interaction)

    @discord.ui.button(label="Cash Out 💰", style=discord.ButtonStyle.success)
    async def cashout_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your game!", ephemeral=True)
            return
        await cashout(interaction)


class RussianRouletteMultiView(discord.ui.View):
    def __init__(self, game_data):
        super().__init__(timeout=300)  # Extend timeout to avoid buttons disappearing
        self.game_data = game_data

    @discord.ui.button(label="Shoot 🔫", style=discord.ButtonStyle.danger)
    async def shoot_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handles shooting logic, ensuring the correct player takes the turn."""
        user_id = interaction.user.id

        # ✅ Check if it's the player's turn before allowing the shot
        if user_id != self.game_data["players"][self.game_data["current_turn"]]:
            await interaction.response.send_message("❌ It's not your turn!", ephemeral=True)
            return

        # ✅ Call the shoot function
        await shoot_multi(interaction)


    @discord.ui.button(label="Vote to Split Pot 🗳️", style=discord.ButtonStyle.secondary)
    async def split_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await vote_split(interaction)  # ✅ This already handles the response






async def russianroulette_solo(interaction: discord.Interaction, amount: int, chambers: int, user_id: int):
    balance = await database.get_balance(user_id)
    if amount <= 0 or amount > balance:
        await interaction.response.send_message(f"❌ You don't have enough coins! Your balance is {balance}.", ephemeral=True)
        return

    await database.update_balance(user_id, -amount)  # Deduct wager

    gun = [0] * chambers
    bullet_index = random.randint(0, chambers - 1)
    gun[bullet_index] = 1

    await database.save_game_state([user_id], chambers, amount, amount, 0, gun, 0)

    view = RussianRouletteSoloView(user_id)
    await interaction.response.send_message(
        f"🔫 **Solo Russian Roulette Started!**\nYou chose {chambers} chambers.\nClick **Shoot 🔫** or **Cash Out 💰**.",
        view=view
    )

async def russianroulette_multi(interaction: discord.Interaction, amount: int, chambers: int, user_ids: list):
    # ✅ First, check if all players have enough balance and ensure atomicity
    # Note: iterating through async generator or list comprehension with async functions inside 'any' is tricky.
    # 'any' does not support async. We must loop explicitly or use gather.
    
    for user_id in user_ids:
        bal = await database.get_balance(user_id)
        if bal < amount:
            await interaction.followup.send("❌ One or more players do not have enough coins!", ephemeral=True)
            return

    # ✅ Deduct the wager **only if all players have enough balance**
    for user_id in user_ids:
        await database.update_balance(user_id, -amount)

    # ✅ Randomize turn order and initialize game state
    random.shuffle(user_ids)
    current_turn = 0

    # ✅ Set up the gun
    gun = [0] * chambers
    bullet_index = random.randint(0, chambers - 1)
    gun[bullet_index] = 1  # Assign a bullet to a random chamber

    winnings = amount * len(user_ids)  # Total pot value

    # ✅ Save game state in the database
    await database.save_game_state(user_ids, chambers, winnings, amount, 0, gun, current_turn)

    # ✅ Pass complete game state to `RussianRouletteMultiView`
    game_data = {
        "players": user_ids,
        "chambers": chambers,
        "winnings": winnings,
        "original_wager": amount,
        "shots_survived": 0,
        "gun": gun,
        "current_turn": current_turn
    }
    view = RussianRouletteMultiView(game_data)  # Ensure game state is passed to View

    # ✅ Start the game and announce turn order
    await interaction.followup.send(
        f"🔫 **Multiplayer Russian Roulette Started!**\n"
        f"Players: {', '.join(f'<@{uid}>' for uid in user_ids)}\n"
        f"Chambers: {chambers}\n"
        f"First player: <@{user_ids[0]}>\n"
        f"Click **Shoot 🔫** when it's your turn!",
        view=view
    )



async def shoot_solo(interaction: discord.Interaction):
    user_id = interaction.user.id
    game_data = await database.get_game_state(user_id)

    if not game_data:
        await interaction.response.send_message("❌ You're not playing Russian Roulette!", ephemeral=True)
        return

    gun = game_data["gun_state"]
    fired_index = random.randint(0, len(gun) - 1)
    shot_result = gun.pop(fired_index)

    if shot_result == 1:
        # Player lost, end the game
        await database.delete_game_state(user_id)
        await interaction.response.send_message(f"💀 **Bang!** {interaction.user.display_name} lost {game_data['original_wager']} coins!", ephemeral=False)
        return

    # Apply multiplier for winnings
    multipliers = {2: 2.0, 3: 1.5, 4: 1.333, 5: 1.25, 6: 1.2, 7: 1.166, 8: 1.125}
    game_data["winnings"] = round(game_data["winnings"] * multipliers[game_data["chambers"]])
    game_data["shots_survived"] += 1

    # Save progress
    await database.save_game_state([user_id], game_data["chambers"], game_data["winnings"], game_data["original_wager"], game_data["shots_survived"], gun, 0)

    view = RussianRouletteSoloView(user_id)
    await interaction.response.send_message(
        f"✅ **Click!** You survived! **Potential winnings: {game_data['winnings']} coins.**\n"
        f"Click **Shoot 🔫** or **Cash Out 💰**!",
        view=view
    )


async def shoot_multi(interaction: discord.Interaction):
    await interaction.response.defer()  # Prevent timeout

    user_id = interaction.user.id
    game_data = await database.get_game_state(user_id)

    if not game_data:
        await interaction.followup.send("❌ You're not playing Russian Roulette!", ephemeral=True)
        return

    if user_id != game_data["players"][game_data["current_turn"]]:
        await interaction.followup.send("❌ It's not your turn!", ephemeral=True)
        return

    gun = game_data["gun_state"]
    fired_index = random.randint(0, len(gun) - 1)
    shot_result = gun.pop(fired_index)

    if shot_result == 1:
        game_data["players"].remove(user_id)

        # 🔹 Ensure the user is removed from SQL as well where necessary
        await database.update_game_players(user_id, game_data["players"])

        await interaction.followup.send(f"💀 <@{user_id}> **was eliminated!**", ephemeral=False)

        if len(game_data["players"]) == 1:
            # 🔹 Last player standing wins
            winner_id = game_data["players"][0]
            await database.update_balance(winner_id, game_data["winnings"])
            await database.delete_game_state(game_data["players"][0])  # Delete using the game creator's ID

            await interaction.followup.send(
                f"🎉 <@{winner_id}> is the last player standing and won {game_data['winnings']} coins!",
                ephemeral=False
            )
            return

        # 🔹 **Reset the gun** for the remaining players
        new_gun = [0] * game_data["chambers"]
        bullet_index = random.randint(0, game_data["chambers"] - 1)
        new_gun[bullet_index] = 1
        game_data["gun_state"] = new_gun

    else:
        # 🔹 Player survived, so increment shots survived
        game_data["shots_survived"] += 1
        await interaction.followup.send("✅ **Click! No Bullet.** ")

    # 🔹 **Ensure turn moves to the next valid player**
    game_data["current_turn"] = (game_data["current_turn"] + 1) % len(game_data["players"])

    # 🔹 **Force the update into SQL**
    await database.save_game_state(
        game_data["players"], game_data["chambers"], game_data["winnings"],
        game_data["original_wager"], game_data["shots_survived"], game_data["gun_state"], game_data["current_turn"]
    )

    await asyncio.sleep(0.2)
    # 🔹 **Retrieve updated game state to ensure sync**
    updated_game_data = await database.get_game_state(game_data["players"][0])

    view = RussianRouletteMultiView(updated_game_data)  # ✅ Pass latest game state

    # ✅ **Notify the next player even if someone was eliminated**
    next_player = updated_game_data["players"][updated_game_data["current_turn"]]
    await interaction.followup.send(
        f"🔫 **Next player:** <@{next_player}>, it's your turn!",
        view=view,
        ephemeral=False
    )








async def cashout(interaction: discord.Interaction):
    user_id = interaction.user.id
    game_data = await database.get_game_state(user_id)
    
    if not game_data:
        await interaction.response.send_message("❌ You're not playing Russian Roulette!", ephemeral=True)
        return

    await database.update_balance(user_id, game_data["winnings"])
    await database.delete_game_state(user_id)

    await interaction.response.send_message(f"💰 **{interaction.user.display_name} cashed out early and won {game_data['winnings']} coins!**", ephemeral=False)


async def vote_split(interaction: discord.Interaction):
    user_id = interaction.user.id
    game_data = await database.get_game_state(user_id)

    if not game_data or "players" not in game_data:
        await interaction.response.send_message("❌ Game data not found. Try again later!", ephemeral=True)
        return

    players_list = json.loads(game_data["players"]) if isinstance(game_data["players"], str) else game_data["players"]
    if user_id not in players_list:
        await interaction.response.send_message("❌ You're not in this game!", ephemeral=True)
        return

    votes = await database.get_votes(game_data["players"][0]) or []

    if user_id not in votes:
        await database.add_vote(game_data["players"][0], user_id)

    votes = await database.get_votes(game_data["players"][0])

    if len(votes) > len(game_data["players"]) // 2:
        split_amount = game_data["winnings"] // len(game_data["players"])
        for player in game_data["players"]:
            await database.update_balance(player, split_amount)
        await database.delete_game_state(game_data["players"][0])

        await interaction.response.send_message(
            f"✅ **Majority voted to split the pot!** Each player receives {split_amount} coins.", ephemeral=False
        )
        return

    # ✅ Only sends one response now
    await interaction.response.send_message(
        f"🗳️ {len(votes)}/{len(game_data['players'])} players voted to split. Need majority!",
        ephemeral=True
    )

def get_crash_multiplier() -> float:
    # 5% chance for instant crash (multiplier exactly 1.0)
    if random.random() < 0.05:
        return 1.0
    # Otherwise, sample from a Gamma distribution
    # Gamma(2.5, 1) has a mode near 1.5 and mean = 2.5.
    multiplier = random.gammavariate(2.5, 1)
    # Ensure the multiplier is at least 1.1 (to avoid overlap with the instant crash case)
    multiplier = max(1.1, multiplier)
    # Clamp the multiplier to a maximum of 25
    multiplier = min(25.0, multiplier)
    return multiplier

class CrashGameView(discord.ui.View):
    def __init__(self, bet: int, rate: float, crash_multiplier: float, start_time: float, interaction: discord.Interaction):
        # We set no timeout here because we want to control the game loop
        super().__init__(timeout=None)
        self.bet = bet
        self.rate = rate
        self.crash_multiplier = crash_multiplier
        self.start_time = start_time
        self.cashed_out = False
        self.interaction = interaction

    @discord.ui.button(label="Withdraw 💰", style=discord.ButtonStyle.success)
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ensure only the original player can withdraw
        if interaction.user.id != self.interaction.user.id:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return

        if self.cashed_out:
            await interaction.response.send_message("You have already cashed out!", ephemeral=True)
            return

        elapsed = time.time() - self.start_time
        current_multiplier = math.exp(self.rate * elapsed)
        if current_multiplier >= self.crash_multiplier:
            await interaction.response.send_message("Too late! The game has crashed.", ephemeral=True)
            return

        self.cashed_out = True
        winnings = int(self.bet * current_multiplier)
        await database.update_balance(interaction.user.id, winnings)
        embed = discord.Embed(
            title="Crash Game Result",
            description=f"You withdrew at **{current_multiplier:.2f}×** and won **{winnings} coins**! ... The crash point was **{self.crash_multiplier:.2f}×**.",
            color=discord.Color.green()
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)



async def crash(interaction: discord.Interaction, amount: int):
    user_id = interaction.user.id
    balance = await database.get_balance(user_id)
    if amount <= 0 or amount > balance:
        await interaction.response.send_message(
            f"❌ You don't have enough coins! Your balance is {balance}.", ephemeral=True
        )
        return

    # Deduct the bet immediately.
    await database.update_balance(user_id, -amount)
    
    # Set parameters for the game.
    rate = 0.1  # Growth rate; adjust as needed.
    crash_multiplier = get_crash_multiplier()  # Use your weighted distribution function.
    start_time = time.time()  # Make sure this line is present!
    
    # Create the game view.
    view = CrashGameView(amount, rate, crash_multiplier, start_time, interaction)
    embed = discord.Embed(
        title="Crash Game Started!",
        description=(
            f"Bet: {amount} coins\n"
            "Current Multiplier: 1.00×\n"
            "Click **Withdraw 💰** before the game crashes!"
        ),
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, view=view)
    
    # Update loop for multiplier display.
    update_interval = 0.5  # Adjust as needed.
    while not view.cashed_out:
        elapsed = time.time() - start_time
        current_multiplier = math.exp(rate * elapsed)
        if current_multiplier >= crash_multiplier:
            embed = discord.Embed(
                title="Crash!",
                description=f"The multiplier reached **{crash_multiplier:.2f}×**. You lost your bet of {amount} coins.",
                color=discord.Color.red()
            )
            for child in view.children:
                child.disabled = True
            try:
                await interaction.followup.edit_message(
                    message_id=(await interaction.original_response()).id,
                    embed=embed,
                    view=view
                )
            except Exception as e:
                print(f"Error editing message on crash: {e}")
            return
        embed = discord.Embed(
            title="Crash Game In Progress",
            description=f"Bet: {amount} coins\nCurrent Multiplier: {current_multiplier:.2f}×\nWithdraw before it crashes!",
            color=discord.Color.orange()
        )
        try:
            await interaction.followup.edit_message(
                message_id=(await interaction.original_response()).id,
                embed=embed,
                view=view
            )
        except Exception as e:
            print(f"Error editing message during update: {e}")
        await asyncio.sleep(update_interval)






#Loans? Message 
#RPS, Blackjack, Crash, Roullette, Poker, Jackpot (money = percent chance), Lottery tickets, type racer (maybe), hide and seek (bot sends meesage in random text channel ppl must find)
#Gacha Machine

async def roulette(interaction: discord.Interaction, amount: int, choice: str):
    user_id = interaction.user.id
    
    # 1. Validate Input
    choice = choice.lower().strip()
    valid_colors = ["red", "black", "green"]
    valid_numbers = [str(i) for i in range(37)] + ["00"] # "0" to "36" and "00"
    
    bet_type = None # "color" or "number"
    
    if choice in valid_colors:
        bet_type = "color"
    elif choice in valid_numbers:
        bet_type = "number"
    else:
        await interaction.response.send_message(
            "❌ Invalid choice! Please bet on a color (`red`, `black`, `green`) or a number (`0`-`36`, `00`).", 
            ephemeral=True
        )
        return

    # 2. Check Balance
    balance = await database.get_balance(user_id)
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0!", ephemeral=True)
        return
    if amount > balance:
        await interaction.response.send_message(f"❌ You don't have enough coins! Your balance is {balance}.", ephemeral=True)
        return

    # 3. Deduct Bet
    await database.update_balance(user_id, -amount)

    # 4. Define Wheel
    wheel_numbers = [str(i) for i in range(37)] + ["00"]
    
    # Helper to determine color
    def get_color(num_str):
        if num_str in ["0", "00"]:
            return "green"
        n = int(num_str)
        # Red numbers: 1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36
        red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
        if n in red_numbers:
            return "red"
        else:
            return "black"

    # 5. Spin
    result_number = random.choice(wheel_numbers)
    result_color = get_color(result_number)

    # 6. Determine Win
    won = False
    payout = 0
    
    if bet_type == "color":
        if choice == result_color:
            won = True
            # Payout for Red/Black is 1:1 (Amount * 2)
            # Payout for Green (0 or 00) is treated as a color bet here? 
            # If they bet "green", and it hits 0 or 00 (which are green), they win.
            # Green covers 2 spots (2/38). Fair payout is 18x. 
            if choice == "green":
                 payout = amount * 18 # 17:1 odds
            else:
                 payout = amount * 2 # 1:1 odds
            
    elif bet_type == "number":
        if choice == result_number:
            won = True
            payout = amount * 36 # 35:1 payout (36x total)

    # 7. Update Balance & Send Result
    
    # Color mapping for Embed
    embed_color = discord.Color.red() if result_color == "red" else discord.Color.default()
    if result_color == "green":
        embed_color = discord.Color.green()

    message = f"You bet **{amount}** on **{choice.upper()}**.\n"
    message += f"The ball landed on **{result_number} ({result_color.upper()})**!\n"

    if won:
        profit = payout - amount
        await database.update_balance(user_id, payout) # Add payout (which includes original bet)
        message += f"🎉 **YOU WON!** You received **{payout}** coins (Profit: {profit})."
        title = "Roulette Result: WIN! 🤑"
    else:
        message += f"💀 **You lost.** Better luck next time!"
        title = "Roulette Result: LOST 💸"

    embed = discord.Embed(title=title, description=message, color=embed_color)

    await interaction.response.send_message(embed=embed)