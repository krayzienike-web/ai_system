from enum import StrEnum

from app.tenancy.models import Role


class Permission(StrEnum):
    RESTAURANTS_READ = "restaurants.read"
    RESTAURANTS_MANAGE = "restaurants.manage"
    USERS_MANAGE = "users.manage"
    NETWORK_COMPARE = "network.compare"  # see other restaurants by name
    DATA_UPLOAD = "data.upload"
    CATALOG_MANAGE = "catalog.manage"
    EXPERIMENTS_APPROVE = "experiments.approve"
    TASKS_EXECUTE = "tasks.execute"
    AI_CHAT = "ai.chat"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.HQ_ADMIN: frozenset(Permission) - {Permission.TASKS_EXECUTE},
    Role.HQ_ANALYST: frozenset(
        {
            Permission.RESTAURANTS_READ,
            Permission.NETWORK_COMPARE,
            Permission.DATA_UPLOAD,
            Permission.AI_CHAT,
        }
    ),
    Role.RESTAURANT_DIRECTOR: frozenset(
        {
            Permission.RESTAURANTS_READ,
            Permission.DATA_UPLOAD,
            Permission.TASKS_EXECUTE,
            Permission.AI_CHAT,
        }
    ),
}
