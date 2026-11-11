import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL
from sqlmodel import Session, create_engine

load_dotenv(Path(__file__).resolve().parent / ".env")

DATABASE_URL = URL.create(
    drivername="mysql+pymysql",
    username=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3306")),
    database=os.getenv("DB_NAME", "sistema_pedidos"),
    query={"charset": "utf8mb4"},
)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=1800,
    isolation_level="READ COMMITTED",
    connect_args={"init_command": "SET time_zone = '+00:00'"},
)

def get_session():
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
