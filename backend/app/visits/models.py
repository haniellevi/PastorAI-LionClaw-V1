"""Typed visit evidence, separate from a person's acquisition origin."""
import datetime as dt
import uuid
from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base


class VisitEvent(Base):
    __tablename__ = 'evento_visita'
    __table_args__ = (
        UniqueConstraint('igreja_id', 'id'),
        UniqueConstraint('igreja_id', 'pessoa_id', 'reuniao_id', name='visit_person_meeting_once'),
        ForeignKeyConstraint(['igreja_id','pessoa_id'], ['pessoas.igreja_id','pessoas.id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['igreja_id','reuniao_id'], ['celula_reuniao.igreja_id','celula_reuniao.id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['igreja_id','reuniao_id','visitante_id'], ['celula_visitante.igreja_id','celula_visitante.reuniao_id','celula_visitante.id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['igreja_id','registrado_por'], ['app_users.igreja_id','app_users.id'], deferrable=True, initially='DEFERRED'),
        CheckConstraint("(tipo='visita_celula' and origem='painel_lider' and reuniao_id is not null and visitante_id is not null) or (tipo='manual_painel' and origem='painel_pipeline' and reuniao_id is null and visitante_id is null)"),
        CheckConstraint('data_ocorrencia <= data_registro'),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    igreja_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    pessoa_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reuniao_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    visitante_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    registrado_por: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(Text, nullable=False)
    origem: Mapped[str] = mapped_column(Text, nullable=False)
    data_ocorrencia: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_registro: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
