"""FastAPI application. Its generated OpenAPI document is the API contract."""

from fastapi import Depends, FastAPI

from app.routers import (
    account,
    auth,
    complaints,
    dashboard,
    invitations,
    managers,
    me,
    notifications,
    properties,
    reauthentication,
    rent_bills,
    rooms,
    sessions,
    subscriptions,
    tenants,
    user_accounts,
)
from app.security import bearer_scheme

app = FastAPI(
    title="Niscala API",
    generate_unique_id_function=lambda route: route.name,
)
# Routers whose operations all need a session. The auth and invitations routers
# declare the requirement per operation because some of their operations are public.
session = [Depends(bearer_scheme)]
app.include_router(auth.router)
app.include_router(invitations.router)
app.include_router(account.router, dependencies=session)
app.include_router(sessions.router, dependencies=session)
app.include_router(reauthentication.router, dependencies=session)
app.include_router(properties.router, dependencies=session)
app.include_router(rooms.router, dependencies=session)
app.include_router(tenants.router, dependencies=session)
app.include_router(managers.router, dependencies=session)
app.include_router(complaints.router, dependencies=session)
app.include_router(complaints.categories_router, dependencies=session)
app.include_router(rent_bills.router, dependencies=session)
app.include_router(me.router, dependencies=session)
app.include_router(dashboard.router, dependencies=session)
app.include_router(notifications.router, dependencies=session)
app.include_router(notifications.me_router, dependencies=session)
app.include_router(user_accounts.router, dependencies=session)
app.include_router(subscriptions.router, dependencies=session)
app.include_router(subscriptions.plans_router, dependencies=session)
