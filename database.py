import aiomysql
import os
import datetime
import json
import logging
from typing import Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global variable for the connection pool
pool: Any = None

async def init_pool():
    global pool
    try:
        pool = await aiomysql.create_pool(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'), 
            password=os.getenv('DB_PASSWORD'),
            db=os.getenv('DB_NAME'),
            autocommit=True
        )
        logger.info("Database connection pool initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")
        raise

async def get_pool() -> Any:
    global pool
    if pool is None:
        await init_pool()
    return pool

async def close_pool():
    global pool
    if pool:
        pool.close()
        await pool.wait_closed()
        logger.info("Database connection pool closed.")

# Initialize database (create tables)
async def init_db():
    pool = await get_pool()
    
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                server_id BIGINT,
                balance INT DEFAULT 0,
                last_claim DATE
            )
            """)

            await cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id BIGINT,
                item_name VARCHAR(255),
                quantity INT DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """)
            
            # Ensure tables needed for Russian Roulette exist (based on usage in original code)
            # Note: The original init_db didn't create these, assuming they existed or were created manually.
            # Adding them here for completeness if they don't exist is good practice, but I'll stick to the original logic 
            # unless errors arise. The user mentioned using Workbench, so tables likely exist.

# Function to add a user
async def add_user(user_id, username, server_id):
    """Adds a new user to the database, ensuring server_id is recorded."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO users (user_id, username, server_id, balance)
                VALUES (%s, %s, %s, 0)
                ON DUPLICATE KEY UPDATE username = VALUES(username), server_id = VALUES(server_id)
            """, (user_id, username, server_id))

# Function to update balance
async def update_balance(user_id, amount):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))

# Function to retrieve user balance
async def get_balance(user_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0

async def get_last_claim(user_id):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT DATE(last_claim) FROM users WHERE user_id = %s", (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else None  # Returns YYYY-MM-DD or None if never claimed

async def update_last_claim(user_id):
    now = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=-5)))  # Convert to EST
    today = now.date()  # Get YYYY-MM-DD (ignore time)
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("UPDATE users SET last_claim = %s WHERE user_id = %s", (today, user_id))

async def save_game_state(players, chambers, winnings, original_wager, shots_survived, gun, current_turn):
    """Saves the current state of a Russian Roulette game."""
    players_json = json.dumps(players)
    gun_json = json.dumps(gun)  # Convert gun state to JSON

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO russian_roullette_game_sessions (user_id, players, chambers, winnings, original_wager, shots_survived, gun_state, current_turn)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    players = VALUES(players),
                    chambers = VALUES(chambers),
                    winnings = VALUES(winnings),
                    original_wager = VALUES(original_wager),
                    shots_survived = VALUES(shots_survived),
                    gun_state = VALUES(gun_state),
                    current_turn = VALUES(current_turn)
            """, (players[0], players_json, chambers, winnings, original_wager, shots_survived, gun_json, current_turn))

async def get_game_state(user_id):
    """Retrieves the current game state for a given player."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor: # Use DictCursor for dictionary results
            await cursor.execute("SELECT * FROM russian_roullette_game_sessions WHERE JSON_CONTAINS(players, %s)", (json.dumps(user_id),))
            result = await cursor.fetchone()

            if not result:
                return None

            # Convert JSON fields back into Python objects
            # Note: JSON fields might be returned as strings or objects depending on the driver/DB configuration.
            # aiomysql usually returns strings for JSON columns.
            
            try:
                if isinstance(result["players"], str):
                    result["players"] = json.loads(result["players"])
                if isinstance(result["gun_state"], str):
                    result["gun_state"] = json.loads(result["gun_state"])
            except json.JSONDecodeError:
                logger.error(f"Error decoding JSON for game state: {result}")
                return None

            return result

async def delete_game_state(game_owner_id):
    """Deletes a Russian Roulette game session using the game creator's ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("DELETE FROM russian_roullette_game_sessions WHERE players LIKE %s", (f'%{game_owner_id}%',))

async def add_vote(user_id, voter_id):
    """Adds a vote to split the winnings in Russian Roulette."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            # Get current votes, ensure it's a valid list
            await cursor.execute("SELECT votes FROM russian_roullette_game_sessions WHERE user_id = %s", (user_id,))
            result = await cursor.fetchone()
            votes = json.loads(result[0]) if result and result[0] else []

            if voter_id not in votes:
                votes.append(voter_id)  # Add vote if not already present

            # Update votes in SQL
            await cursor.execute("UPDATE russian_roullette_game_sessions SET votes = %s WHERE user_id = %s", (json.dumps(votes), user_id))

async def get_votes(user_id):
    """Retrieves the list of votes for a game session."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT votes FROM russian_roullette_game_sessions WHERE user_id = %s", (user_id,))
            result = await cursor.fetchone()

            if result is None or result[0] is None:
                return []  # Ensure we return a valid empty list if NULL

            return json.loads(result[0])

async def clear_votes(user_id):
    """Clears votes when a game session ends."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("UPDATE russian_roullete_game_sessions SET votes = '[]' WHERE user_id = %s", (user_id,))

async def create_invitation(creator_id, server_id, invited_users):
    """Creates a game invitation and returns the game_id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("""
                INSERT INTO russian_roulette_invitations (creator_id, server_id, invited_users, accepted_users, declined_users)
                VALUES (%s, %s, %s, %s, %s)
            """, (creator_id, server_id, json.dumps(invited_users), json.dumps([]), json.dumps([])))  # ✅ Explicit empty lists
            
            game_id = cursor.lastrowid  # Get the game ID
            return game_id

async def accept_invitation(game_id, user_id):
    """Marks a user as having accepted the game invitation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT accepted_users FROM russian_roulette_invitations WHERE game_id = %s", (game_id,))
            result = await cursor.fetchone()
            
            if result:
                accepted_users = json.loads(result[0])
                if user_id not in accepted_users:
                    accepted_users.append(user_id)
                    await cursor.execute("UPDATE russian_roulette_invitations SET accepted_users = %s WHERE game_id = %s",
                                   (json.dumps(accepted_users), game_id))

async def decline_invitation(game_id, user_id):
    """Marks a user as having declined the game invitation."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT declined_users FROM russian_roulette_invitations WHERE game_id = %s", (game_id,))
            result = await cursor.fetchone()
            
            if result:
                declined_users = json.loads(result[0])
                if user_id not in declined_users:
                    declined_users.append(user_id)
                    await cursor.execute("UPDATE russian_roulette_invitations SET declined_users = %s WHERE game_id = %s",
                                   (json.dumps(declined_users), game_id))

async def get_accepted_players(game_id):
    """Returns the list of users who accepted the game."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT accepted_users FROM russian_roulette_invitations WHERE game_id = %s", (game_id,))
            result = await cursor.fetchone()
            return json.loads(result[0]) if result else []

async def delete_invitation(game_id):
    """Deletes a game invitation after the game starts or is canceled."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("DELETE FROM russian_roulette_invitations WHERE game_id = %s", (game_id,))

async def is_already_in_game(game_id, user_id):
    """Checks if a user has already joined an ongoing game."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT COUNT(*) FROM russian_roulette_invitations WHERE game_id = %s AND JSON_CONTAINS(accepted_users, %s)", 
                           (game_id, json.dumps(user_id)))
            result = await cursor.fetchone()
            return result[0] > 0

async def add_player_to_game(game_id, user_id):
    """Adds a player to an ongoing game session."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("SELECT accepted_users FROM russian_roulette_invitations WHERE game_id = %s", (game_id,))
            result = await cursor.fetchone()
            
            if result:
                players = json.loads(result[0]) if result[0] else []
                if user_id not in players:
                    players.append(user_id)
                    await cursor.execute("UPDATE russian_roulette_invitations SET accepted_users = %s WHERE game_id = %s", 
                                   (json.dumps(players), game_id))

async def update_game_players(user_id, new_players):
    """Updates the players list for a game where the user is present."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute("UPDATE russian_roullette_game_sessions SET players = %s WHERE players LIKE %s", 
                        (json.dumps(new_players), f'%{user_id}%'))


async def get_local_leaderboard(server_id, limit=10):
    """Fetches the top users by balance in a specific server."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                SELECT user_id, balance FROM users 
                WHERE server_id = %s 
                ORDER BY balance DESC 
                LIMIT %s
            """, (server_id, limit))
            result = await cursor.fetchall()
            return result

async def get_global_leaderboard(limit=10):
    """Fetches the top users by balance across all servers."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute("""
                SELECT user_id, balance FROM users 
                ORDER BY balance DESC 
                LIMIT %s
            """, (limit,))
            result = await cursor.fetchall()
            return result
