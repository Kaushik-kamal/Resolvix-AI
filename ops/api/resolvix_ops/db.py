"""Database session management."""
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings


def configure_sqlite(dbapi_conn, connection_record):
    """Configure SQLite with WAL mode, busy timeout, and foreign keys."""
    # Set isolation_level to None for manual transaction control
    dbapi_conn.isolation_level = None
    
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def begin_immediate(connection):
    """Start transaction with BEGIN IMMEDIATE for concurrency-safe writes."""
    # This ensures exclusive write lock immediately, preventing conflicts
    # Use the raw DBAPI connection
    connection.exec_driver_sql("BEGIN IMMEDIATE")


def create_db_engine(settings: Settings):
    """Create and configure database engine."""
    # SQLite-specific: check_same_thread=False for FastAPI threadpool
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    
    engine = create_engine(
        settings.database_url,
        connect_args=connect_args,
        echo=False
    )
    
    # Configure SQLite if using SQLite
    if settings.database_url.startswith("sqlite"):
        event.listen(engine, "connect", configure_sqlite)
        event.listen(engine, "begin", begin_immediate)
    
    return engine


def get_session_factory(engine):
    """Create session factory."""
    return sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def get_db(session_factory) -> Session:
    """FastAPI dependency for database sessions."""
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
