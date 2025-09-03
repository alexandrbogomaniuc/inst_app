from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from igw.app.routes.auth import router as auth_router
from igw.app.routes.oauth_instagram import router as ig_oauth_router

app = FastAPI(title="IGW API", version="0.1.0")

# CORS (tweak for your front-end)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["root"])
def root():
    return {"ok": True, "service": "IGW API"}


# Mount routers
app.include_router(auth_router)
app.include_router(ig_oauth_router)
