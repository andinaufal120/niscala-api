"""FastAPI application. Its generated OpenAPI document is the API contract."""

from fastapi import FastAPI

from app.routers import complaints, me, properties, rent_bills, rooms, tenants

app = FastAPI(
    title="Niscala API",
    generate_unique_id_function=lambda route: route.name,
)
app.include_router(properties.router)
app.include_router(rooms.router)
app.include_router(tenants.router)
app.include_router(complaints.router)
app.include_router(complaints.categories_router)
app.include_router(rent_bills.router)
app.include_router(me.router)
