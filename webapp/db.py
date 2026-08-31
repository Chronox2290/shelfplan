"""Storage for accounts, plans and price history.

SQLite by default so the app runs with no external service; point DATABASE_URL
at Postgres to share one instance between people.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import os

from sqlalchemy import (
    JSON, DateTime, ForeignKey, Integer, String, Float, Boolean,
    UniqueConstraint, create_engine, func,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker,
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/shelfplan.db")

if DATABASE_URL.startswith("sqlite"):
    path = DATABASE_URL.split("///", 1)[-1]
    if path and path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}, future=True
    )
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Bumped whenever the password changes. The session cookie carries the
    # version it was minted at, so changing a password drops every existing
    # session -- otherwise resetting a stolen account would leave the thief
    # signed in.
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    plans: Mapped[list["Plan"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Plan(Base):
    """A whole meal plan, held as the same JSON shape the page renders from."""

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="My plan")
    data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    owner: Mapped[User] = relationship(back_populates="plans")


class PriceRecord(Base):
    """One observed price for one food.

    Kept separately from the plan so history survives editing or replacing a
    plan, and so the same food's trend is visible across weeks.
    """

    __tablename__ = "price_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    food: Mapped[str] = mapped_column(String(300), index=True)
    price: Mapped[float] = mapped_column(Float)
    pack: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    per_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    basis: Mapped[str] = mapped_column(String(20), default="gross")
    store: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(40), default="manual")
    matched_name: Mapped[str] = mapped_column(String(300), default="")
    stockcode: Mapped[str] = mapped_column(String(40), default="")
    on_special: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_on: Mapped[str] = mapped_column(String(10), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        # One reading per food per day per source keeps refreshes idempotent.
        UniqueConstraint("user_id", "food", "observed_on", "source",
                         name="uq_price_per_day"),
    )


class PasswordReset(Base):
    """A one-time password-reset token.

    Only the SHA-256 of the token is stored, so a leaked database yields
    hashes that cannot be presented to the reset endpoint.
    """

    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    requested_ip: Mapped[str] = mapped_column(String(45), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Recipe(Base):
    """A saved recipe, kept out of the plan JSON so it survives replanning.

    Ratings are what make the builder improve over time: a recipe you liked
    stays in the library and can be dropped into any week, and one you did not
    is deleted rather than regenerated.
    """

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 1-5, or null for "not rated yet" -- which is different from "rated badly".
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(String(2000), default="")
    times_cooked: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class PlanVersion(Base):
    """A snapshot of a plan taken before it was overwritten.

    Plans are edited constantly -- ticking an item saves the whole document --
    so a bug or a mis-click can wipe a week's work with no way back. Keeping
    the last few versions makes that recoverable instead of final.
    """

    __tablename__ = "plan_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PriceCache(Base):
    """Store search results shared by every user of this server.

    Keyed by store and search term rather than by user: the supermarkets see
    one request per term per refresh window no matter how many people are
    looking. Persisting it means a restart does not re-trigger a burst.
    """

    __tablename__ = "price_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store: Mapped[str] = mapped_column(String(32), index=True)
    query_key: Mapped[str] = mapped_column(String(240), index=True)
    products: Mapped[Any] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("store", "query_key", name="uq_price_cache"),
    )


class Product(Base):
    """A product seen at a store, kept permanently.

    The supermarkets have no public bulk export, so this catalogue is built
    from what actually gets looked up: every search writes its results here and
    they stay, whether or not anyone searches for them again. Over a few weeks
    of normal use it becomes a local index that can be searched instantly and
    offline, without asking the store anything.

    Shared across all users of this server -- one household should not have to
    re-fetch what another already found.
    """

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store: Mapped[str] = mapped_column(String(32), index=True)
    stockcode: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    # Lowercased name, so a LIKE search does not depend on collation.
    search_key: Mapped[str] = mapped_column(String(300), index=True)
    brand: Mapped[str] = mapped_column(String(120), default="")
    package_size: Mapped[str] = mapped_column(String(80), default="")
    pack_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pack_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    per_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cup_string: Mapped[str] = mapped_column(String(80), default="")
    on_special: Mapped[bool] = mapped_column(Boolean, default=False)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    url: Mapped[str] = mapped_column(String(400), default="")
    image: Mapped[str] = mapped_column(String(400), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("store", "stockcode", name="uq_product"),
    )


def _migrate(connection) -> None:
    """Add columns that later versions introduced.

    SQLite cannot ALTER a column in, so new nullable-with-default columns are
    added here rather than requiring a rebuild of an existing database.
    """
    from sqlalchemy import text
    rows = connection.execute(text("PRAGMA table_info(users)")).fetchall()
    if rows and not any(r[1] == "session_version" for r in rows):
        connection.execute(text(
            "ALTER TABLE users ADD COLUMN session_version INTEGER DEFAULT 1"))
        connection.commit()


def init_db() -> None:
    Base.metadata.create_all(engine)
    if DATABASE_URL.startswith("sqlite"):
        with engine.connect() as connection:
            _migrate(connection)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
