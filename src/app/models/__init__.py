"""Database models; importing this package registers every table."""

from app.models.base import Base
from app.models.email_verification import EmailVerificationCode
from app.models.login_failure import LoginFailure
from app.models.properties import ManagerAssignment, Property
from app.models.rooms import Room
from app.models.subscriptions import Subscription
from app.models.users import UserAccount, UserSession

__all__ = [
    "Base",
    "EmailVerificationCode",
    "LoginFailure",
    "ManagerAssignment",
    "Property",
    "Room",
    "Subscription",
    "UserAccount",
    "UserSession",
]
