"""Database models; importing this package registers every table."""

from app.models.base import Base
from app.models.complaints import Complaint, ComplaintStatusChange
from app.models.email_change import EmailChangeRequest
from app.models.email_verification import EmailVerificationCode
from app.models.login_failure import LoginFailure
from app.models.managers import Manager
from app.models.password_reset import PasswordResetToken
from app.models.properties import ManagerAssignment, Property
from app.models.rent_bills import RentBill, RentBillReceipt, RentBillStatusChange
from app.models.rooms import Room
from app.models.subscriptions import Subscription
from app.models.tenants import EmergencyContact, Invitation, Lease, Tenant
from app.models.users import UsedRefreshToken, UserAccount, UserSession

__all__ = [
    "Base",
    "Complaint",
    "ComplaintStatusChange",
    "EmailChangeRequest",
    "EmailVerificationCode",
    "EmergencyContact",
    "Invitation",
    "Lease",
    "LoginFailure",
    "Manager",
    "ManagerAssignment",
    "PasswordResetToken",
    "Property",
    "RentBill",
    "RentBillReceipt",
    "RentBillStatusChange",
    "Room",
    "Subscription",
    "Tenant",
    "UsedRefreshToken",
    "UserAccount",
    "UserSession",
]
