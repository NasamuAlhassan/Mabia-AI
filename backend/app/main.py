"""Mabia AI — application entry point."""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import Base, engine

app = FastAPI(title="Mabia AI", version="2.0.0",
              description="CHPS emergency response, voice outreach and "
                          "nutrition coordination for Northern Ghana.")

# allow_credentials must stay False while allow_origins can be "*": browsers
# reject that combination outright, and the web app would fail every request
# with an opaque CORS error. Nothing here uses cookies -- auth is a Bearer
# token -- so credentials are not needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    # Vercel gives every preview deployment its own hostname, so the named
    # production origin alone would break every preview build.
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Recorded local-language prompts are served publicly: Africa's Talking fetches
# them over HTTPS during a call, so they cannot sit behind authentication.
AUDIO_DIR = Path(__file__).resolve().parents[1] / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

from .api import (auth, circle, contacts, emergencies, facility,  # noqa: E402
                  language, metrics, nutrition, patients, setup, simulator,
                  sync, telephony, worklist)

app.include_router(auth.router)
app.include_router(setup.router)
app.include_router(patients.router)
app.include_router(contacts.router)
app.include_router(circle.router)
app.include_router(worklist.router)
app.include_router(emergencies.router)
app.include_router(telephony.router)
app.include_router(simulator.router)
app.include_router(nutrition.router)
app.include_router(language.router)
app.include_router(sync.router)
app.include_router(facility.router)
app.include_router(metrics.router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    if settings.seed_on_start:
        from .db import SessionLocal
        from .seed import seed
        db = SessionLocal()
        try:
            seed(db)
            db.commit()
        finally:
            db.close()


@app.get("/api/health", tags=["health"])
def health():
    return {"ok": True, "app": settings.app_name, "version": app.version}


@app.get("/", include_in_schema=False)
def root():
    return {"service": "Mabia AI", "docs": "/docs", "health": "/api/health"}
