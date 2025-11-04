import discord
from discord import app_commands
import boto3
import datetime
import os
from dotenv import load_dotenv
from botocore.exceptions import ClientError

# === Load env ===
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
INSTANCE_ID = os.getenv("INSTANCE_ID")
REGION_NAME = os.getenv("REGION_NAME")
HOURLY_COST = float(os.getenv("HOURLY_COST", "0.0416"))

# === AWS Clients ===
ec2 = boto3.client("ec2", region_name=REGION_NAME)
cloudwatch = boto3.client("cloudwatch", region_name=REGION_NAME)

# === Intents & Bot ===
intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot connecté en tant que {bot.user}")

@tree.command(name="start", description="Démarre le serveur Minecraft")
async def start_command(interaction: discord.Interaction):
    try:
        ec2.start_instances(InstanceIds=[INSTANCE_ID])
        await interaction.response.send_message("🟢 Le serveur Minecraft est en cours de démarrage...")
    except ClientError as e:
        if e.response['Error']['Code'] == 'IncorrectInstanceState':
            await interaction.response.send_message("⏳ Le serveur est déjà en train de démarrer ou de s'arrêter. Merci de patienter...")
        else:
            await interaction.response.send_message("❌ Une erreur est survenue : " + str(e))
            raise  # Pour que ça reste loggé
        
@tree.command(name="stop", description="Arrête le serveur Minecraft")
async def stop_command(interaction: discord.Interaction):
    ec2.stop_instances(InstanceIds=[INSTANCE_ID])
    await interaction.response.send_message("🔴 Le serveur Minecraft est en cours d’arrêt...")

@tree.command(name="status", description="Vérifie le statut du serveur Minecraft")
async def status_command(interaction: discord.Interaction):
    response = ec2.describe_instance_status(InstanceIds=[INSTANCE_ID])
    statuses = response.get("InstanceStatuses", [])
    if not statuses:
        await interaction.response.send_message("⚪ Le serveur est **arrêté**.")
    else:
        state = statuses[0]["InstanceState"]["Name"]
        await interaction.response.send_message(f"ℹ️ Statut actuel du serveur : **{state}**")

@tree.command(name="uptime", description="Affiche l’uptime depuis le début du mois et le coût estimé")
async def uptime_command(interaction: discord.Interaction):
    now = datetime.datetime.utcnow()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    metrics = cloudwatch.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[{'Name': 'InstanceId', 'Value': INSTANCE_ID}],
        StartTime=start_of_month,
        EndTime=now,
        Period=3600,
        Statistics=['Average']
    )

    datapoints = metrics.get('Datapoints', [])
    hours_up = len(datapoints)
    cost = round(hours_up * HOURLY_COST, 2)

    await interaction.response.send_message(
        f"📊 Uptime depuis le 1er du mois : **{hours_up}h**\n💰 Coût estimé : **${cost}**"
    )

# === Lancer le bot ===
bot.run(DISCORD_TOKEN)
