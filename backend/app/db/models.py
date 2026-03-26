import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JobKind(str, enum.Enum):
    sync = "sync"
    recategorize = "recategorize"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class LlmOperation(str, enum.Enum):
    initial_classify = "initial_classify"
    recategorize = "recategorize"
    after_new_categories = "after_new_categories"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sync_state: Mapped["UserSyncState | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    categories: Mapped[list["Category"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    threads: Mapped[list["Thread"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSyncState(Base):
    __tablename__ = "user_sync_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    newest_thread_internal_date_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    user: Mapped["User"] = relationship(back_populates="sync_state")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "normalized_name", name="uq_category_user_norm"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="categories")
    thread_links: Mapped[list["ThreadCategory"]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_thread_id", name="uq_thread_user_gmail"),
        Index("ix_threads_user_internal_date", "user_id", "internal_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    snippet: Mapped[str] = mapped_column(Text, nullable=False, default="")
    internal_date: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_addr: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="threads")
    category_links: Mapped[list["ThreadCategory"]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )


class ThreadCategory(Base):
    __tablename__ = "thread_categories"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )

    thread: Mapped["Thread"] = relationship(back_populates="category_links")
    category: Mapped["Category"] = relationship(back_populates="thread_links")


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (Index("ix_sync_jobs_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.pending.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_labels_snapshot: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    batches_total: Mapped[int | None] = mapped_column(nullable=True)
    batches_done: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LlmRun(Base):
    __tablename__ = "llm_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sync_jobs.id", ondelete="SET NULL"), nullable=True
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="SET NULL"), nullable=True
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
