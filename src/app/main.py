"""FastAPI application. Its generated OpenAPI document is the API contract."""

from fastapi import FastAPI

from app.routers import properties, rooms

app = FastAPI(
    title="Niscala API",
    generate_unique_id_function=lambda route: route.name,
)
app.include_router(properties.router)
app.include_router(rooms.router)
