"""
database.py

SQLAlchemy engine, session factory, and database initialisation for the
Jarvis AI Operating System.

Responsibilities:
    - Create the SQLAlchemy engine from the configured DATABASE_PATH.
    - Provide a session factory for opening database sessions.
    - Provide a context manager that yields a session and handles
      commit, rollback, and cleanup correctly.
    - Initialise the database by creating all tables if they do not exist.

Does NOT:
    - Implement Memory Manager logic.
    - Implement Observability logic.
    - Implement AI logic.
    - Define table structure (see models.py).

This module owns the connection and lifecycle concerns of the database only.
The shape of the data lives in models.py, and the behaviour that uses the
data lives in the subsystems that own each table.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from config.settings import Settings, load_settings
from storage.models import Base


def _build_sqlite_url(database_path: Path) -> str:
    """Build a SQLite connection URL from a filesystem path.

    Args:
        database_path: Path to the SQLite database file.

    Returns:
        A SQLAlchemy SQLite connection URL pointing at the resolved path.
    """
    resolved = database_path.expanduser().resolve()
    return f"sqlite:///{resolved}"


def _ensure_parent_directory(database_path: Path) -> None:
    """Create the parent directory of the database file if it is missing.

    SQLite will create the database file itself, but it will not create the
    directory that contains it. This ensures the directory exists before the
    engine attempts to open the file.

    Args:
        database_path: Path to the SQLite database file.
    """
    parent = database_path.expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(
    dbapi_connection: object, connection_record: object
) -> None:
    """Enable foreign key enforcement on every new SQLite connection.

    SQLite does not enforce foreign key constraints by default. This listener
    issues the required pragma on each new connection so that the ondelete
    behaviour declared on the models is actually applied.

    Args:
        dbapi_connection: The raw DBAPI connection object.
        connection_record: The connection pool's record for this connection.
    """
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


#: Milliseconds SQLite will wait for a lock before raising "database is
#: locked", instead of failing immediately. See _configure_sqlite_concurrency.
_SQLITE_BUSY_TIMEOUT_MS = 2000


@event.listens_for(Engine, "connect")
def _configure_sqlite_concurrency(
    dbapi_connection: object, connection_record: object
) -> None:
    """Configure SQLite for a second, independent reader process (Phase 19).

    Phase 19 introduces a real second process (the local dashboard) that
    opens this same database file for reads while the Jarvis CLI process
    may be writing to it. Under SQLite's default rollback-journal mode,
    with no busy timeout configured, a reader that overlaps a writer's
    commit window can receive an immediate "database is locked" error.

    This listener sets two connection-level pragmas to make that safe:

    - journal_mode=WAL: SQLite's own standard mechanism for letting one
      writer and any number of concurrent readers proceed without
      blocking each other. This is a durable, per-database-file setting
      (persisted in the file itself once set), not merely a per-session
      one - but it has no effect on a ":memory:" database, which has no
      file and always behaves as if in "memory" journal mode regardless
      of what is requested here.
    - busy_timeout=2000: for the small remaining set of cases WAL alone
      does not eliminate (for example two simultaneous writers), a
      connection waits up to 2 seconds for a lock to clear before raising,
      rather than failing immediately.

    This does not eliminate every possible SQLite lock/contention
    scenario, and it does not change SQLAlchemy's own commit/rollback/
    session semantics, transaction boundaries, or the append-only
    behaviour of any existing table - it only changes how a connection
    waits for a lock at the SQLite level.

    Args:
        dbapi_connection: The raw DBAPI connection object.
        connection_record: The connection pool's record for this connection.
    """
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    cursor.close()


def create_database_engine(settings: Settings | None = None) -> Engine:
    """Create and return a SQLAlchemy engine for the configured database.

    The engine is the central source of database connectivity. A single engine
    should be created once and shared for the lifetime of the application.

    Args:
        settings: Application settings to read DATABASE_PATH from. When None,
            settings are loaded via load_settings().

    Returns:
        A configured SQLAlchemy Engine connected to the SQLite database.
    """
    if settings is None:
        settings = load_settings()

    _ensure_parent_directory(settings.database_path)
    url = _build_sqlite_url(settings.database_path)

    return create_engine(
        url,
        echo=settings.debug,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[OrmSession]:
    """Create a session factory bound to the given engine.

    The returned factory produces new Session objects on demand. Callers
    should generally use the session_scope context manager rather than the
    factory directly, so that commit, rollback, and cleanup are handled.

    Args:
        engine: The engine the produced sessions will be bound to.

    Returns:
        A configured sessionmaker that produces ORM sessions.
    """
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


def initialize_database(engine: Engine) -> None:
    """Create all defined tables if they do not already exist.

    This reads the metadata of every model that inherits from Base and creates
    the corresponding tables. Existing tables are left untouched, so this is
    safe to call on every startup.

    After creating tables, a small, idempotent backward-compatibility step
    ensures older databases (created before the memory "category" column
    existed) gain that column with a safe default. This lets memory rows from
    earlier phases keep working.

    Args:
        engine: The engine to create the tables against.
    """
    Base.metadata.create_all(bind=engine)
    _ensure_memory_category_column(engine)


def _ensure_memory_category_column(engine: Engine) -> None:
    """Add the episodic_memories.category column if an old database lacks it.

    On a fresh database, create_all already builds the column, so this does
    nothing. On a database created before Phase 5, the column is missing;
    create_all does not alter existing tables, so this step adds it via a
    single ALTER TABLE with a default of "general", backfilling every existing
    row. The operation is guarded by a column check, so it is idempotent and
    safe to run on every startup.

    Args:
        engine: The engine whose database should be checked and, if needed,
            updated.
    """
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "episodic_memories" not in table_names:
        return  # No table yet (unexpected here), nothing to migrate.

    columns = {col["name"] for col in inspector.get_columns("episodic_memories")}
    if "category" in columns:
        return  # Already present: fresh DB or already migrated.

    # Add the column with a safe default so existing rows become "general".
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE episodic_memories "
                "ADD COLUMN category VARCHAR(32) NOT NULL DEFAULT 'general'"
            )
        )


@contextmanager
def session_scope(
    session_factory: sessionmaker[OrmSession],
) -> Iterator[OrmSession]:
    """Provide a transactional scope around a series of database operations.

    Yields a session, commits it on successful completion, rolls it back if an
    exception occurs, and always closes it afterwards. This is the preferred
    way to interact with the database from other subsystems.

    Args:
        session_factory: The factory used to create the session.

    Yields:
        An open ORM session that is committed or rolled back automatically.

    Raises:
        Exception: Re-raises any exception that occurs within the scope, after
            rolling back the transaction.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()