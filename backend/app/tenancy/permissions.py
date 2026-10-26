from enum import StrEnum

from app.tenancy.models import Role


class Permission(StrEnum):
    RESTAURANTS_READ = "restaurants.read"
    RESTAURANTS_MANAGE = "restaurants.manage"
    USERS_MANAGE = "users.manage"
    NETWORK_COMPARE = "network.compare"  # see other restaurants by name
    DATA_UPLOAD = "data.upload"
    CATALOG_MANAGE = "catalog.manage"
    EXPERIMENTS_PROPOSE = "experiments.propose"  # draft a check of a finding for HQ admin to launch
    EXPERIMENTS_LAUNCH = "experiments.launch"  # launch or reject a proposed check, roll a result out
    ANALYTICS_RUN = "analytics.run"  # recompute findings for the whole network
    FINDINGS_REVIEW = "findings.review"  # check engine findings against the data, confirm or reject
    NORMS_MANAGE = "norms.manage"  # food-cost targets, loss allowances, write-off reasons
    TASKS_ASSIGN = "tasks.assign"  # set tasks for any restaurant of the network
    TASKS_EXECUTE = "tasks.execute"  # take tasks for one's own restaurant and report on them
    AI_CHAT = "ai.chat"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.HQ_ADMIN: frozenset(Permission) - {Permission.TASKS_EXECUTE},
    Role.HQ_ANALYST: frozenset(
        {
            Permission.RESTAURANTS_READ,
            Permission.NETWORK_COMPARE,
            Permission.DATA_UPLOAD,
            Permission.FINDINGS_REVIEW,
            Permission.EXPERIMENTS_PROPOSE,
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
