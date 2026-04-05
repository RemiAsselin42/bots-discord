"""
Fonctions utilitaires partagées entre les commandes de type uptime/cost.
"""
import datetime

from bot.aws import get_ec2_client


def get_uptime_and_cost(
    instance_id: str,
    region: str,
    hourly_cost: float,
) -> dict | None:
    """
    Interroge EC2 pour calculer l'uptime et le coût estimé d'une instance running.

    Returns:
        Un dict avec les clés : state, launch_dt, delta, hours, minutes, cost
        ou None si l'instance n'est pas en état 'running'.

    Raises:
        toute exception boto3 en cas d'erreur réseau/accès.
    """
    ec2 = get_ec2_client(region)
    statuses = ec2.describe_instance_status(InstanceIds=[instance_id]).get("InstanceStatuses", [])

    if not statuses:
        return None

    state = statuses[0]["InstanceState"]["Name"]
    if state != "running":
        return {"state": state, "running": False}

    now = datetime.datetime.now(datetime.timezone.utc)
    instance = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
    launch_dt = instance["LaunchTime"].replace(tzinfo=datetime.timezone.utc)

    delta = now - launch_dt
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    cost = hourly_cost * delta.total_seconds() / 3600

    return {
        "running": True,
        "state": state,
        "launch_dt": launch_dt,
        "delta": delta,
        "hours": hours,
        "minutes": minutes,
        "cost": cost,
    }
