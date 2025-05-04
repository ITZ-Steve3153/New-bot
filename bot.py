import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import asyncio
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

CONFIG_FILE = "config.json"
PUNISH_FILE = "punishment_data.json"

# Load config
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "trigger_roles": [],
            "roles_to_remove": [],
            "check_interval": 5
        }

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Load punishment config
def load_punish_data():
    try:
        with open(PUNISH_FILE, "r") as f:
            return json.load(f)
    except:
        return {"punishment_roles": {}}

def save_punish_data(data):
    with open(PUNISH_FILE, "w") as f:
        json.dump(data, f, indent=2)

config = load_config()
punish_data = load_punish_data()

# --- Utilities ---

def parse_delay_string(s):
    unit = s[-1]
    num = int(s[:-1])
    if unit == "m":
        return timedelta(minutes=num)
    elif unit == "h":
        return timedelta(hours=num)
    elif unit == "d":
        return timedelta(days=num)
    else:
        return timedelta(seconds=int(s))  # fallback

async def get_guild(interaction):
    return interaction.guild

# --- MAIN FUNCTIONALITY ---

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await tree.sync()
    check_roles.start()
    check_punishments.start()

@bot.event
async def on_member_update(before, after):
    added = [role for role in after.roles if role not in before.roles]
    for role in added:
        if role.id in config["trigger_roles"]:
            for r_id in config["roles_to_remove"]:
                role_to_remove = discord.utils.get(after.guild.roles, id=r_id)
                if role_to_remove in after.roles:
                    await after.remove_roles(role_to_remove)

        if role.id in punish_data["punishment_roles"]:
            punish_data["punishment_roles"][str(role.id)]["assigned_users"][str(after.id)] = datetime.utcnow().isoformat()
            save_punish_data(punish_data)

# --- COMMAND GROUP: ROLE CLEANUP ---

@tree.command(name="set_trigger_role", description="Add a role that triggers removal of others")
@app_commands.describe(role="The trigger role")
async def set_trigger_role(interaction: discord.Interaction, role: discord.Role):
    if role.id not in config["trigger_roles"]:
        config["trigger_roles"].append(role.id)
        save_config(config)
    await interaction.response.send_message(f"✅ Trigger role set: {role.name}", ephemeral=True)

@tree.command(name="remove_trigger_role", description="Remove a trigger role")
@app_commands.describe(role="The role to remove from trigger list")
async def remove_trigger_role(interaction: discord.Interaction, role: discord.Role):
    if role.id in config["trigger_roles"]:
        config["trigger_roles"].remove(role.id)
        save_config(config)
    await interaction.response.send_message(f"🗑️ Removed trigger role: {role.name}", ephemeral=True)

@tree.command(name="add_remove_role", description="Add a role to be removed when trigger is applied")
@app_commands.describe(role="The role to remove from members")
async def add_remove_role(interaction: discord.Interaction, role: discord.Role):
    if role.id not in config["roles_to_remove"]:
        config["roles_to_remove"].append(role.id)
        save_config(config)
    await interaction.response.send_message(f"✅ Role set to be removed: {role.name}", ephemeral=True)

@tree.command(name="remove_remove_role", description="Remove a role from the removal list")
@app_commands.describe(role="The role to stop removing")
async def remove_remove_role(interaction: discord.Interaction, role: discord.Role):
    if role.id in config["roles_to_remove"]:
        config["roles_to_remove"].remove(role.id)
        save_config(config)
    await interaction.response.send_message(f"🗑️ Removed from removal list: {role.name}", ephemeral=True)

@tree.command(name="list_roles", description="List current trigger and removal roles")
async def list_roles(interaction: discord.Interaction):
    guild = interaction.guild
    trigger_names = [discord.utils.get(guild.roles, id=r).name for r in config["trigger_roles"]]
    remove_names = [discord.utils.get(guild.roles, id=r).name for r in config["roles_to_remove"]]
    await interaction.response.send_message(
        f"🧠 **Trigger Roles**: {', '.join(trigger_names) or 'None'}\n"
        f"🧹 **Roles to Remove**: {', '.join(remove_names) or 'None'}", ephemeral=True)

@tree.command(name="set_check_interval", description="Set the interval (in minutes) for checking trigger roles")
@app_commands.describe(minutes="Interval in minutes")
async def set_check_interval(interaction: discord.Interaction, minutes: int):
    config["check_interval"] = minutes
    save_config(config)
    check_roles.change_interval(minutes=minutes)
    await interaction.response.send_message(f"🔁 Interval set to {minutes} minutes.", ephemeral=True)

# --- COMMAND GROUP: PUNISHMENT SYSTEM ---

@tree.command(name="punish_add_trigger", description="Add a punishment trigger role with delay and action")
@app_commands.describe(role="The trigger role", action="mute/kick/ban", delay="e.g., 30d, 12h")
async def punish_add_trigger(interaction: discord.Interaction, role: discord.Role, action: str, delay: str):
    if action not in ["mute", "kick", "ban"]:
        await interaction.response.send_message("❌ Invalid action. Choose mute, kick, or ban.", ephemeral=True)
        return
    punish_data["punishment_roles"][str(role.id)] = {
        "action": action,
        "delay": delay,
        "assigned_users": {}
    }
    save_punish_data(punish_data)
    await interaction.response.send_message(f"⚠️ Set punishment: {action} after {delay} if {role.name} is kept.", ephemeral=True)

@tree.command(name="punish_remove_trigger", description="Remove a punishment trigger role")
@app_commands.describe(role="The punishment trigger role to remove")
async def punish_remove_trigger(interaction: discord.Interaction, role: discord.Role):
    if str(role.id) in punish_data["punishment_roles"]:
        del punish_data["punishment_roles"][str(role.id)]
        save_punish_data(punish_data)
    await interaction.response.send_message(f"🗑️ Removed punishment trigger: {role.name}", ephemeral=True)

@tree.command(name="punish_list", description="List all active punishment roles")
async def punish_list(interaction: discord.Interaction):
    guild = interaction.guild
    lines = []
    for role_id, data in punish_data["punishment_roles"].items():
        role = discord.utils.get(guild.roles, id=int(role_id))
        lines.append(f"🔸 {role.name}: {data['action']} after {data['delay']}")
    await interaction.response.send_message("\n".join(lines) or "No punishments set.", ephemeral=True)

# --- BACKGROUND TASKS ---

@tasks.loop(minutes=config["check_interval"])
async def check_roles():
    for guild in bot.guilds:
        for member in guild.members:
            for trigger_id in config["trigger_roles"]:
                if discord.utils.get(member.roles, id=trigger_id):
                    for r_id in config["roles_to_remove"]:
                        role = discord.utils.get(guild.roles, id=r_id)
                        if role and role in member.roles:
                            await member.remove_roles(role)

@tasks.loop(minutes=5)
async def check_punishments():
    now = datetime.utcnow()
    for guild in bot.guilds:
        for role_id, data in punish_data["punishment_roles"].items():
            role = discord.utils.get(guild.roles, id=int(role_id))
            delay = parse_delay_string(data["delay"])
            to_remove = []

            for user_id, start_time in data["assigned_users"].items():
                member = guild.get_member(int(user_id))
                if not member:
                    continue
                start_dt = datetime.fromisoformat(start_time)
                if now - start_dt >= delay and role in member.roles:
                    action = data["action"]
                    try:
                        if action == "kick":
                            await member.kick(reason="Punishment timer elapsed")
                        elif action == "ban":
                            await member.ban(reason="Punishment timer elapsed")
                        elif action == "mute":
                            mute_role = discord.utils.get(guild.roles, name="Muted")
                            if mute_role:
                                await member.add_roles(mute_role)
                    except Exception as e:
                        print(f"Error punishing {member}: {e}")
                    to_remove.append(user_id)

            for uid in to_remove:
                del data["assigned_users"][uid]

    save_punish_data(punish_data)

# --- RUN BOT ---
import os
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
