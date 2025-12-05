from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from config import (
        DATABASE_HOST,
        DATABASE_PASSWORD,
        DATABASE_PORT,
        DATABASE_USER
        )

DATABASE_URL = f"postgresql+psycopg2://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/ai_dapp"

engine = create_engine(
        DATABASE_URL,
        future=True,
        echo=False
        )

SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
        )

Base = declarative_base()

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
