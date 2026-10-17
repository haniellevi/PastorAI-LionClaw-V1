"""Private V4 storage, isolated from institutional knowledge and cell reports."""

import datetime as dt
import uuid
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base


class PrayerProposal(Base):
    __tablename__ = "pedido_oracao_proposta"
    __table_args__ = (
        UniqueConstraint("igreja_id", "id"),
        UniqueConstraint("igreja_id", "source_message_id"),
        ForeignKeyConstraint(
            ["igreja_id", "pessoa_id"],
            ["pessoas.igreja_id", "pessoas.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "conversation_id"],
            ["conversations.igreja_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "conversation_id", "source_message_id"],
            ["messages.igreja_id", "messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "conversation_id", "summary_message_id"],
            ["messages.igreja_id", "messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "cell_id"],
            ["celulas.igreja_id", "celulas.id"],
            ondelete="SET NULL (cell_id)",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "leader_id"],
            ["pessoas.igreja_id", "pessoas.id"],
            ondelete="SET NULL (leader_id)",
        ),
        CheckConstraint(
            "state in ('collecting','pending','executed','cancelled','expired')"
        ),
        CheckConstraint(
            "audience is null or audience in ('pastoral','pastoral_lider')"
        ),
        Index(
            "prayer_one_active_proposal",
            "igreja_id",
            "conversation_id",
            unique=True,
            postgresql_where=text("state in ('collecting','pending')"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("igrejas.id", ondelete="CASCADE"), nullable=False
    )
    pessoa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    source_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    summary_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    delivered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str | None] = mapped_column(Text)
    cell_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    leader_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    authorization_text: Mapped[str | None] = mapped_column(Text)
    term_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(
        Text, nullable=False, default="collecting", server_default=text("'collecting'")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class PrayerRequest(Base):
    __tablename__ = "pedido_oracao"
    __table_args__ = (
        UniqueConstraint("igreja_id", "id"),
        UniqueConstraint("igreja_id", "proposal_id"),
        UniqueConstraint("igreja_id", "confirmation_message_id"),
        ForeignKeyConstraint(
            ["igreja_id", "proposal_id"],
            ["pedido_oracao_proposta.igreja_id", "pedido_oracao_proposta.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "pessoa_id"],
            ["pessoas.igreja_id", "pessoas.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "conversation_id"],
            ["conversations.igreja_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "conversation_id", "confirmation_message_id"],
            ["messages.igreja_id", "messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "cell_id"],
            ["celulas.igreja_id", "celulas.id"],
            ondelete="SET NULL (cell_id)",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "leader_id"],
            ["pessoas.igreja_id", "pessoas.id"],
            ondelete="SET NULL (leader_id)",
        ),
        ForeignKeyConstraint(
            ["igreja_id", "responsavel_id"],
            ["app_users.igreja_id", "app_users.id"],
            ondelete="SET NULL (responsavel_id)",
        ),
        CheckConstraint("audience in ('pastoral','pastoral_lider')"),
        CheckConstraint("state in ('open','assigned','closed')"),
        CheckConstraint("length(summary) between 1 and 1000"),
        CheckConstraint("length(authorization_hash) = 64"),
        Index("prayer_recipient_idx", "igreja_id", "state", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    igreja_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("igrejas.id", ondelete="CASCADE"), nullable=False
    )
    pessoa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    confirmation_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(Text, nullable=False)
    cell_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    leader_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    authorization_text: Mapped[str] = mapped_column(Text, nullable=False)
    authorization_hash: Mapped[str] = mapped_column(Text, nullable=False)
    authorization_version: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    responsavel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    state: Mapped[str] = mapped_column(
        Text, nullable=False, default="open", server_default=text("'open'")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
