import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)


def get_ec2_client(region: str):
    return boto3.client("ec2", region_name=region)


def get_cloudwatch_client(region: str):
    return boto3.client("cloudwatch", region_name=region)


def format_boto_error(
    e: Exception,
    *,
    action: str,
    instance_id: str | None = None,
    region: str | None = None,
) -> str:
    """Retourne un message utilisateur clair pour les erreurs AWS/boto3."""
    prefix = f"❌ Impossible de {action}."

    if isinstance(e, NoCredentialsError):
        return (
            f"{prefix} Identifiants AWS introuvables dans l'environnement d'exécution. "
            "Contactez un administrateur pour configurer les credentials (profil AWS ou rôle IAM)."
        )
    if isinstance(e, EndpointConnectionError):
        return (
            f"{prefix} Endpoint AWS injoignable pour la région '{region}'. "
            "Vérifiez la région configurée et la connectivité réseau."
        )
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "ClientError")
        msg = e.response.get("Error", {}).get("Message", str(e))
        if code == "InvalidInstanceID.Malformed":
            suffix = f" ('{instance_id}')" if instance_id else ""
            return f"{prefix} L'ID d'instance fourni est invalide{suffix}. Vérifiez la configuration du serveur."
        if code == "InvalidInstanceID.NotFound":
            suffix = f" dans la région '{region}'" if region else ""
            return f"{prefix} L'instance n'a pas été trouvée{suffix}. Vérifiez l'ID et la région."
        if code in ("UnauthorizedOperation", "AccessDenied", "AccessDeniedException"):
            return (
                f"{prefix} Permissions AWS insuffisantes pour exécuter cette action. "
                "Un administrateur doit ajuster les politiques IAM."
            )
        if code == "IncorrectInstanceState":
            return (
                f"{prefix} L'instance est dans un état qui ne permet pas l'opération (en cours de transition). "
                "Réessayez dans quelques secondes."
            )
        return f"{prefix} Erreur AWS: {code} - {msg}"

    if isinstance(e, BotoCoreError):
        return f"{prefix} Erreur du SDK AWS: {e}"

    return f"{prefix} Erreur inattendue: {e}"
