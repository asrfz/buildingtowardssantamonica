import logging
import cloudinary
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import connect_db, close_db
from app.routers import sensor, events, users, zones, alerts

logging.basicConfig(level=logging.INFO)


def _init_cloudinary() -> None:
    if settings.CLOUDINARY_CLOUD_NAME:
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    _init_cloudinary()
    yield
    await close_db()


app = FastAPI(title="HomePulse AI", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sensor.router,  prefix="/sensor",  tags=["sensor"])
app.include_router(events.router,  prefix="/events",  tags=["events"])
app.include_router(users.router,   prefix="/users",   tags=["users"])
app.include_router(zones.router,   prefix="/zones",   tags=["zones"])
app.include_router(alerts.router,  prefix="/alerts",  tags=["alerts"])
