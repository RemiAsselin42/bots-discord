import discord
from discord import app_commands
import boto3
import datetime
import os
import json
from dotenv import load_dotenv
from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError, BotoCoreError
from typing import Dict, List

# === Load env ===
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# === Load servers config ===
def load_config():
    with open("servers_config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config_data):
    """Sauvegarde la configuration dans le fichier JSON"""
    with open("servers_config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

config = load_config()

# === Helper functions ===
def get_guild_servers(guild_id: int) -> Dict:
    """Récupère les serveurs Minecraft pour une guilde Discord donnée"""
    guild_str = str(guild_id)
    if guild_str not in config["guilds"]:
        return {}
    return config["guilds"][guild_str]["servers"]

def get_server_config(guild_id: int, server_key: str) -> Dict:
    """Récupère la configuration d'un serveur Minecraft spécifique"""
    servers = get_guild_servers(guild_id)
    return servers.get(server_key)

def get_ec2_client(region: str):
    """Crée un client EC2 pour une région spécifique"""
    return boto3.client("ec2", region_name=region)

def get_cloudwatch_client(region: str):
    """Crée un client CloudWatch pour une région spécifique"""
    return boto3.client("cloudwatch", region_name=region)

# === Error formatting helper ===
def format_boto_error(e: Exception, *, action: str, instance_id: str | None = None, region: str | None = None) -> str:
    """Retourne un message utilisateur clair pour les erreurs AWS/boto3."""
    prefix = f"❌ Impossible de {action}."

    if isinstance(e, NoCredentialsError):
        return (
            f"{prefix} Identifiants AWS introuvables dans l'environnement d'exécution. "
            f"Contactez un administrateur pour configurer les credentials (profil AWS ou rôle IAM)."
        )
    if isinstance(e, EndpointConnectionError):
        return (
            f"{prefix} Endpoint AWS injoignable pour la région '{region}'. "
            f"Vérifiez la région configurée et la connectivité réseau."
        )
    if isinstance(e, ClientError):
        code = e.response.get('Error', {}).get('Code', 'ClientError')
        msg = e.response.get('Error', {}).get('Message', str(e))
        if code in ("InvalidInstanceID.Malformed",):
            return (
                f"{prefix} L'ID d'instance fourni est invalide"
                + (f" ('{instance_id}')" if instance_id else "")
                + ". Vérifiez la configuration du serveur."
            )
        if code in ("InvalidInstanceID.NotFound",):
            return (
                f"{prefix} L'instance n'a pas été trouvée"
                + (f" dans la région '{region}'" if region else "")
                + ". Vérifiez l'ID et la région."
            )
        if code in ("UnauthorizedOperation", "AccessDenied", "AccessDeniedException"):
            return (
                f"{prefix} Permissions AWS insuffisantes pour exécuter cette action. "
                f"Un administrateur doit ajuster les politiques IAM."
            )
        if code in ("IncorrectInstanceState",):
            return (
                f"{prefix} L'instance est dans un état qui ne permet pas l'opération (en cours de transition). "
                f"Réessayez dans quelques secondes."
            )
        # Générique mais sans stacktrace
        return f"{prefix} Erreur AWS: {code} - {msg}"

    if isinstance(e, BotoCoreError):
        return f"{prefix} Erreur du SDK AWS: {str(e)}"

    return f"{prefix} Erreur inattendue: {str(e)}"

# === Intents & Bot ===
intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# === Autocomplete pour les serveurs ===
async def server_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> List[app_commands.Choice[str]]:
    """Autocomplétion qui montre uniquement les serveurs de la guilde actuelle"""
    if not interaction.guild:
        return []
    
    servers = get_guild_servers(interaction.guild.id)
    choices = []
    
    for key, server_data in servers.items():
        name = server_data.get("name", key)
        
        # Filtrer par la saisie de l'utilisateur
        if current.lower() in name.lower() or current.lower() in key.lower():
            choices.append(app_commands.Choice(name=name, value=key))
    
    return choices[:25]  # Discord limite à 25 choix

@bot.event
async def on_ready():
    print("DEBUG: Entrée dans on_ready")
    try:
        synced = await tree.sync()
        print(f"✅ Bot connecté en tant que {bot.user}")
        print(f"📋 {len(synced)} commande(s) synchronisée(s)")
        print(f"📋 {len(config['guilds'])} guilde(s) configurée(s)")
    except Exception as e:
        print(f"❌ Erreur lors de la synchronisation: {e}")
        import traceback
        traceback.print_exc()

@tree.command(name="start", description="Démarre le serveur Minecraft")
@app_commands.describe(server="Sélectionnez le serveur à démarrer")
@app_commands.autocomplete(server=server_autocomplete)
async def start_command(interaction: discord.Interaction, server: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True)
        return
    
    server_config = get_server_config(interaction.guild.id, server)
    if not server_config:
        await interaction.response.send_message("❌ Serveur introuvable dans la configuration.", ephemeral=True)
        return
    
    # Validation rapide de l'ID pour éviter des erreurs évidentes
    instance_id = server_config.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
        await interaction.response.send_message(
            "❌ L'ID d'instance configuré est invalide. Corrigez la configuration du serveur.", ephemeral=True
        )
        return

    name = server_config.get("name", server)
    try:
        ec2 = get_ec2_client(server_config["region"])
        ec2.start_instances(InstanceIds=[instance_id])
        await interaction.response.send_message(f"🟢 Le serveur **{name}** est en cours de démarrage...")
    except (ClientError, NoCredentialsError, EndpointConnectionError, BotoCoreError, Exception) as e:
        await interaction.response.send_message(
            format_boto_error(e, action="démarrer le serveur", instance_id=instance_id, region=server_config.get("region")),
            ephemeral=True,
        )
        
@tree.command(name="stop", description="Arrête le serveur Minecraft")
@app_commands.describe(server="Sélectionnez le serveur à arrêter")
@app_commands.autocomplete(server=server_autocomplete)
async def stop_command(interaction: discord.Interaction, server: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True)
        return
    
    server_config = get_server_config(interaction.guild.id, server)
    if not server_config:
        await interaction.response.send_message("❌ Serveur introuvable dans la configuration.", ephemeral=True)
        return
    
    instance_id = server_config.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
        await interaction.response.send_message(
            "❌ L'ID d'instance configuré est invalide. Corrigez la configuration du serveur.", ephemeral=True
        )
        return

    name = server_config.get("name", server)
    try:
        ec2 = get_ec2_client(server_config["region"])
        ec2.stop_instances(InstanceIds=[instance_id])
        await interaction.response.send_message(f"🔴 Le serveur **{name}** est en cours d'arrêt...")
    except (ClientError, NoCredentialsError, EndpointConnectionError, BotoCoreError, Exception) as e:
        await interaction.response.send_message(
            format_boto_error(e, action="arrêter le serveur", instance_id=instance_id, region=server_config.get("region")),
            ephemeral=True,
        )

@tree.command(name="status", description="Vérifie le statut du serveur Minecraft")
@app_commands.describe(server="Sélectionnez le serveur à vérifier")
@app_commands.autocomplete(server=server_autocomplete)
async def status_command(interaction: discord.Interaction, server: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True)
        return
    
    server_config = get_server_config(interaction.guild.id, server)
    if not server_config:
        await interaction.response.send_message("❌ Serveur introuvable dans la configuration.", ephemeral=True)
        return
    
    instance_id = server_config.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.startswith("i-"):
        await interaction.response.send_message(
            "❌ L'ID d'instance configuré est invalide. Corrigez la configuration du serveur.", ephemeral=True
        )
        return

    name = server_config.get("name", server)
    try:
        ec2 = get_ec2_client(server_config["region"])
        response = ec2.describe_instance_status(InstanceIds=[instance_id])
        statuses = response.get("InstanceStatuses", [])
        if not statuses:
            await interaction.response.send_message(f"⚪ Le serveur **{name}** est **arrêté**.")
        else:
            state = statuses[0]["InstanceState"]["Name"]
            await interaction.response.send_message(f"ℹ️ Statut du serveur **{name}** : **{state}**")
    except (ClientError, NoCredentialsError, EndpointConnectionError, BotoCoreError, Exception) as e:
        await interaction.response.send_message(
            format_boto_error(e, action="vérifier le statut", instance_id=instance_id, region=server_config.get("region")),
            ephemeral=True,
        )

@tree.command(name="list", description="Liste tous les serveurs Minecraft disponibles")
async def list_command(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True)
        return
    
    servers = get_guild_servers(interaction.guild.id)
    
    if not servers:
        await interaction.response.send_message("❌ Aucun serveur Minecraft configuré pour ce serveur Discord.", ephemeral=True)
        return
    
    message = "🖥️ **Serveurs Minecraft disponibles :**\n\n"
    for key, server_data in servers.items():
        name = server_data.get("name", key)
        message += f"• **{name}** (`{key}`)\n"
    
    await interaction.response.send_message(message)

@tree.command(name="addserver", description="Ajoute un nouveau serveur Minecraft à la configuration")
@app_commands.describe(
    key="Identifiant unique du serveur (ex: survival, creative, modded)",
    name="Nom affiché du serveur",
    instance_id="ID de l'instance EC2 AWS (ex: i-xxxxxxxxxxxxx)",
    region="Région AWS (ex: eu-north-1, us-east-1)"
)
async def addserver_command(
    interaction: discord.Interaction,
    key: str,
    name: str,
    instance_id: str,
    region: str
):
    if not interaction.guild:
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True)
        return
    
    # Vérifier les permissions (optionnel - vous pouvez limiter aux admins)
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent ajouter des serveurs.", ephemeral=True)
        return
    
    guild_str = str(interaction.guild.id)
    
    # Valider le format de l'instance_id
    if not instance_id.startswith("i-") or len(instance_id) != 19:
        await interaction.response.send_message("❌ Format d'instance_id invalide. Exemple: `i-0123456789abcdef0`", ephemeral=True)
        return
    
    # Valider la key (pas d'espaces, caractères spéciaux limités)
    if not key.replace("_", "").replace("-", "").isalnum():
        await interaction.response.send_message("❌ La clé doit contenir uniquement des lettres, chiffres, tirets et underscores.", ephemeral=True)
        return
    
    # Charger la config actuelle
    global config
    config = load_config()
    
    # Créer la guilde si elle n'existe pas
    if guild_str not in config["guilds"]:
        config["guilds"][guild_str] = {
            "name": interaction.guild.name,
            "servers": {}
        }
    
    # Vérifier si le serveur existe déjà
    if key in config["guilds"][guild_str]["servers"]:
        await interaction.response.send_message(f"❌ Un serveur avec la clé `{key}` existe déjà. Utilisez une clé différente ou supprimez l'ancien serveur d'abord.", ephemeral=True)
        return
    
    # Ajouter le nouveau serveur
    config["guilds"][guild_str]["servers"][key] = {
        "name": name,
        "instance_id": instance_id,
        "region": region
    }
    
    # Sauvegarder la configuration
    try:
        save_config(config)
        await interaction.response.send_message(
            f"✅ Serveur **{name}** (`{key}`) ajouté avec succès !\n\n"
            f"📋 **Détails :**\n"
            f"• Instance: `{instance_id}`\n"
            f"• Région: `{region}`\n\n"
            f"Utilisez `/start {key}` pour le démarrer."
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur lors de la sauvegarde : {str(e)}", ephemeral=True)

@tree.command(name="removeserver", description="Supprime un serveur Minecraft de la configuration")
@app_commands.describe(server="Sélectionnez le serveur à supprimer")
@app_commands.autocomplete(server=server_autocomplete)
async def removeserver_command(interaction: discord.Interaction, server: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ Cette commande ne peut être utilisée que dans un serveur Discord.", ephemeral=True)
        return
    
    # Vérifier les permissions
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Seuls les administrateurs peuvent supprimer des serveurs.", ephemeral=True)
        return
    
    guild_str = str(interaction.guild.id)
    
    # Charger la config actuelle
    global config
    config = load_config()
    
    # Vérifier si le serveur existe
    if guild_str not in config["guilds"] or server not in config["guilds"][guild_str]["servers"]:
        await interaction.response.send_message("❌ Serveur introuvable dans la configuration.", ephemeral=True)
        return
    
    # Récupérer les infos du serveur avant suppression
    server_info = config["guilds"][guild_str]["servers"][server]
    name = server_info.get("name", server)
    
    # Supprimer le serveur
    del config["guilds"][guild_str]["servers"][server]
    
    # Sauvegarder la configuration
    try:
        save_config(config)
        await interaction.response.send_message(f"✅ Serveur **{name}** (`{server}`) supprimé avec succès.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur lors de la sauvegarde : {str(e)}", ephemeral=True)

# === Lancer le bot ===
bot.run(DISCORD_TOKEN)
