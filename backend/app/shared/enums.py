from enum import Enum


class UserRole(str, Enum):
    OWNER = "owner"
    MANAGER = "manager"
    AGENT = "agent"


class SubscriptionPlan(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class ClientType(str, Enum):
    BUYER = "buyer"
    RENTER = "renter"
    INVESTOR = "investor"


class OpportunityStatus(str, Enum):
    NEW = "new"
    REVIEWED = "reviewed"
    CONTACTED = "contacted"
    DISMISSED = "dismissed"


class OrganizationPropertyStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    VIEWING_SCHEDULED = "viewing_scheduled"
    NEGOTIATING = "negotiating"
    WON = "won"
    LOST = "lost"
    IGNORED = "ignored"


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class ScrapeJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    # Legacy aliases kept for backwards compat with old DB rows
    SUCCESS = "success"
