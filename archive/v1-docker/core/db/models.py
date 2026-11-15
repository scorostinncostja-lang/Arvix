import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    Text,
    Time,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --- Event Log ---------------------------------------------------------


class Event(Base):
    """Append-only. Единственный источник истины — см. 03-DATA-MODEL.md §1."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    source: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("kind <> ''", name="events_kind_check"),
        Index("ix_events_local_date", "local_date"),
        Index("ix_events_kind_at", "kind", "at"),
        Index("ix_events_payload_gin", "payload", postgresql_using="gin"),
    )


# --- Профиль и цели ------------------------------------------------------


class Profile(Base):
    """Одна строка — single-user."""

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    name: Mapped[str | None] = mapped_column(Text)
    birth_date: Mapped[date | None] = mapped_column(Date)
    city: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    institution: Mapped[str | None] = mapped_column(Text)
    height_cm: Mapped[int | None] = mapped_column()
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    timezone: Mapped[str] = mapped_column(Text, default="Europe/Moscow", server_default="Europe/Moscow")
    sleep_target_min: Mapped[int] = mapped_column(default=465, server_default=sql_text("465"))
    bedtime_target: Mapped[time] = mapped_column(Time, default=time(23, 30), server_default=sql_text("'23:30:00'"))
    wake_target: Mapped[time] = mapped_column(Time, default=time(7, 15), server_default=sql_text("'07:15:00'"))
    mentor_enabled: Mapped[bool] = mapped_column(default=True, server_default=sql_text("true"))
    onboarding_stage: Mapped[str] = mapped_column(Text, default="core", server_default="core")
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("id = 1", name="profile_singleton_check"),)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goals.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str | None] = mapped_column(Text)  # dream | main | yearly | quarterly | milestone
    sphere: Mapped[str | None] = mapped_column(Text)
    why: Mapped[str | None] = mapped_column(Text)
    metric: Mapped[str | None] = mapped_column(Text)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric)
    deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Trait(Base):
    """Страхи, слабости, привычки — собираются интервью (05-BOT-TWA.md §2)."""

    __tablename__ = "traits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # fear|weakness|bad_habit|good_habit|trigger
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[int | None] = mapped_column(SmallInteger)
    counter_strategy: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", server_default="active")
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Расписание -----------------------------------------------------------


class DayTemplate(Base):
    __tablename__ = "day_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str | None] = mapped_column(Text)  # study|work|deep|recovery|silent
    weekday: Mapped[int | None] = mapped_column(SmallInteger)  # 0..6, null = не привязан
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    sphere: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_duration_min: Mapped[int | None] = mapped_column()
    deep_work: Mapped[bool] = mapped_column(default=False, server_default=sql_text("false"))
    proof: Mapped[str] = mapped_column(Text, default="confirm", server_default="confirm")
    status: Mapped[str] = mapped_column(Text, default="planned", server_default="planned")
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality: Mapped[int | None] = mapped_column(SmallInteger)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goals.id"))
    source: Mapped[str] = mapped_column(Text, default="user", server_default="user")
    recurrence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    debt_since: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_tasks_planned_start", "planned_start"),
        Index(
            "ix_tasks_status_active",
            "status",
            postgresql_where=sql_text("status IN ('planned','active','debt')"),
        ),
    )


# --- Совет директоров: директивы ------------------------------------------


class Directive(Base):
    __tablename__ = "directives"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    voice_hint: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(SmallInteger, default=3, server_default=sql_text("3"))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    valid_until: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Тело и железо ----------------------------------------------------------


class Biometrics(Base):
    __tablename__ = "biometrics"

    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    sleep_min: Mapped[int | None] = mapped_column()
    deep_sleep_min: Mapped[int | None] = mapped_column()
    bedtime: Mapped[time | None] = mapped_column(Time)
    wake_time: Mapped[time | None] = mapped_column(Time)
    sleep_quality: Mapped[int | None] = mapped_column(SmallInteger)
    hr_rest: Mapped[int | None] = mapped_column()
    hr_avg: Mapped[int | None] = mapped_column()
    spo2: Mapped[int | None] = mapped_column(SmallInteger)
    stress_avg: Mapped[int | None] = mapped_column(SmallInteger)
    steps: Mapped[int | None] = mapped_column()
    active_min: Mapped[int | None] = mapped_column()
    source: Mapped[str] = mapped_column(Text, nullable=False)  # manual|healthconnect|export
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str | None] = mapped_column(Text)  # esp32|android_bridge
    name: Mapped[str | None] = mapped_column(Text)
    token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmware: Mapped[str | None] = mapped_column(Text)


# --- Сезоны -------------------------------------------------------------


class Season(Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    start_rank: Mapped[str | None] = mapped_column(Text)
    final_rank: Mapped[str | None] = mapped_column(Text)
    sp_avg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


# --- Проекции (пересчитываются из events, см. core/events/projections.py) -


class StateDaily(Base):
    __tablename__ = "state_daily"

    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    completion_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    deep_minutes: Mapped[int] = mapped_column(default=0, server_default=sql_text("0"))
    sleep_min: Mapped[int | None] = mapped_column()
    xp: Mapped[int] = mapped_column(default=0, server_default=sql_text("0"))
    hp_end: Mapped[int | None] = mapped_column(SmallInteger)
    sp: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    mode: Mapped[str | None] = mapped_column(Text)


class StateCurrent(Base):
    """Одна строка — текущий агрегат по всей истории."""

    __tablename__ = "state_current"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    xp_total: Mapped[int] = mapped_column(default=0, server_default=sql_text("0"))
    level: Mapped[int] = mapped_column(default=1, server_default=sql_text("1"))
    hp: Mapped[int] = mapped_column(SmallInteger, default=100, server_default=sql_text("100"))
    streak_days: Mapped[int] = mapped_column(default=0, server_default=sql_text("0"))
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"))
    sp_avg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    mode: Mapped[str] = mapped_column(Text, default="normal", server_default="normal")
    autonomy_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    __table_args__ = (
        CheckConstraint("id = 1", name="state_current_singleton_check"),
        CheckConstraint("hp >= 0 AND hp <= 100", name="state_current_hp_range_check"),
    )


class StateWeekly(Base):
    __tablename__ = "state_weekly"

    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    budget_used_min: Mapped[int] = mapped_column(default=0, server_default=sql_text("0"))
    deep_min: Mapped[int] = mapped_column(default=0, server_default=sql_text("0"))
    quotas: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    expenses: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
