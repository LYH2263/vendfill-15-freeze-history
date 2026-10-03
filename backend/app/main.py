from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import seed_if_empty


def _ensure_columns() -> None:
    """轻量幂等迁移：为已存在的 refill_orders 补冻结世代/签名列。

    create_all 不会改已有表；线上若用旧 schema 建过表，这里补列，
    历史行 generation 取默认 1。
    """
    insp = inspect(engine)
    if "refill_orders" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("refill_orders")}
    additions = {
        "generation": "ALTER TABLE refill_orders ADD COLUMN generation INTEGER DEFAULT 1",
        "line_sigs_json": "ALTER TABLE refill_orders ADD COLUMN line_sigs_json TEXT DEFAULT '{}'",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(text(ddl))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="VendFill", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
