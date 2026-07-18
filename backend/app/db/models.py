from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Restaurant(Base):
    __tablename__ = "restaurants"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="currency_iso3"),
        CheckConstraint("status in ('ACTIVE','INACTIVE')", name="status_valid"),
        Index("ix_restaurants_status_simulation", "status", "is_simulation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    default_locale: Mapped[str] = mapped_column(String(32), nullable=False, default="zh-CN")
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_simulation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MenuVersion(Base):
    __tablename__ = "menu_versions"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "version_number", name="uq_menu_versions_restaurant_number"),
        UniqueConstraint("id", "restaurant_id", name="uq_menu_versions_id_restaurant"),
        CheckConstraint("version_number > 0", name="version_positive"),
        CheckConstraint("status in ('DRAFT','PUBLISHED','ARCHIVED')", name="status_valid"),
        Index("ix_menu_versions_restaurant_status", "restaurant_id", "status"),
        Index(
            "uq_menu_versions_one_published_per_restaurant",
            "restaurant_id",
            unique=True,
            sqlite_where=text("status = 'PUBLISHED'"),
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class Branch(Base):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "code", name="uq_branches_restaurant_code"),
        UniqueConstraint("id", "restaurant_id", name="uq_branches_id_restaurant"),
        ForeignKeyConstraint(
            ["active_menu_version_id", "restaurant_id"],
            ["menu_versions.id", "menu_versions.restaurant_id"],
            name="fk_branches_active_menu_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status in ('ACTIVE','INACTIVE')", name="status_valid"),
        Index("ix_branches_restaurant_status", "restaurant_id", "status"),
        Index("ix_branches_active_menu", "restaurant_id", "active_menu_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    active_menu_version_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MenuCategory(Base):
    __tablename__ = "menu_categories"
    __table_args__ = (
        UniqueConstraint("menu_version_id", "code", name="uq_menu_categories_version_code"),
        UniqueConstraint("id", "menu_version_id", name="uq_menu_categories_id_version"),
        Index("ix_menu_categories_version_sort", "menu_version_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_version_id: Mapped[int] = mapped_column(ForeignKey("menu_versions.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MenuCategoryTranslation(Base):
    __tablename__ = "menu_category_translations"
    __table_args__ = (UniqueConstraint("category_id", "locale", name="uq_category_translations_locale"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("menu_categories.id", ondelete="CASCADE"), nullable=False)
    locale: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        UniqueConstraint("menu_version_id", "code", name="uq_menu_items_version_code"),
        UniqueConstraint("id", "menu_version_id", name="uq_menu_items_id_version"),
        ForeignKeyConstraint(
            ["category_id", "menu_version_id"],
            ["menu_categories.id", "menu_categories.menu_version_id"],
            name="fk_menu_items_category_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint("base_price_minor >= 0", name="price_nonnegative"),
        CheckConstraint("length(currency) = 3", name="currency_iso3"),
        Index("ix_menu_items_version_category", "menu_version_id", "category_id"),
        Index("ix_menu_items_version_active", "menu_version_id", "active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_version_id: Mapped[int] = mapped_column(ForeignKey("menu_versions.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    base_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class MenuItemTranslation(Base):
    __tablename__ = "menu_item_translations"
    __table_args__ = (UniqueConstraint("menu_item_id", "locale", name="uq_item_translations_locale"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False)
    locale: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MenuItemAlias(Base):
    __tablename__ = "menu_item_aliases"
    __table_args__ = (
        UniqueConstraint("menu_version_id", "locale", "normalized_alias", name="uq_item_aliases_version_locale_norm"),
        ForeignKeyConstraint(
            ["menu_item_id", "menu_version_id"],
            ["menu_items.id", "menu_items.menu_version_id"],
            name="fk_item_aliases_item_version",
            ondelete="CASCADE",
        ),
        Index("ix_item_aliases_lookup", "menu_version_id", "locale", "normalized_alias"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_version_id: Mapped[int] = mapped_column(ForeignKey("menu_versions.id", ondelete="CASCADE"), nullable=False)
    locale: Mapped[str] = mapped_column(String(32), nullable=False)
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(200), nullable=False)


class ModifierGroup(Base):
    __tablename__ = "modifier_groups"
    __table_args__ = (
        UniqueConstraint("menu_version_id", "code", name="uq_modifier_groups_version_code"),
        UniqueConstraint("id", "menu_version_id", name="uq_modifier_groups_id_version"),
        CheckConstraint("min_selections >= 0", name="min_nonnegative"),
        CheckConstraint("max_selections >= min_selections", name="max_gte_min"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_version_id: Mapped[int] = mapped_column(ForeignKey("menu_versions.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_selections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_selections: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ModifierGroupTranslation(Base):
    __tablename__ = "modifier_group_translations"
    __table_args__ = (
        UniqueConstraint("modifier_group_id", "locale", name="uq_modifier_group_translations_locale"),
        ForeignKeyConstraint(
            ["modifier_group_id", "menu_version_id"],
            ["modifier_groups.id", "modifier_groups.menu_version_id"],
            name="fk_modifier_group_translations_group_version",
            ondelete="CASCADE",
        ),
        Index("ix_modifier_group_translations_version_locale", "menu_version_id", "locale"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    modifier_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class ModifierOption(Base):
    __tablename__ = "modifier_options"
    __table_args__ = (
        UniqueConstraint("modifier_group_id", "code", name="uq_modifier_options_group_code"),
        UniqueConstraint("id", "modifier_group_id", name="uq_modifier_options_id_group"),
        CheckConstraint("price_delta_minor >= 0", name="price_delta_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    modifier_group_id: Mapped[int] = mapped_column(ForeignKey("modifier_groups.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    price_delta_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ModifierOptionTranslation(Base):
    __tablename__ = "modifier_option_translations"
    __table_args__ = (
        UniqueConstraint("modifier_option_id", "locale", name="uq_modifier_option_translations_locale"),
        ForeignKeyConstraint(
            ["modifier_option_id", "modifier_group_id"],
            ["modifier_options.id", "modifier_options.modifier_group_id"],
            name="fk_modifier_option_translations_option_group",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["modifier_group_id", "menu_version_id"],
            ["modifier_groups.id", "modifier_groups.menu_version_id"],
            name="fk_modifier_option_translations_group_version",
            ondelete="CASCADE",
        ),
        Index("ix_modifier_option_translations_version_locale", "menu_version_id", "locale"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    modifier_option_id: Mapped[int] = mapped_column(Integer, nullable=False)
    modifier_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class MenuItemModifierGroup(Base):
    __tablename__ = "menu_item_modifier_groups"
    __table_args__ = (
        UniqueConstraint("menu_item_id", "modifier_group_id", name="uq_item_modifier_group_pair"),
        ForeignKeyConstraint(
            ["menu_item_id", "menu_version_id"],
            ["menu_items.id", "menu_items.menu_version_id"],
            name="fk_item_modifier_groups_item_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["modifier_group_id", "menu_version_id"],
            ["modifier_groups.id", "modifier_groups.menu_version_id"],
            name="fk_item_modifier_groups_group_version",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    modifier_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Allergen(Base):
    __tablename__ = "allergens"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "code", name="uq_allergens_restaurant_code"),
        UniqueConstraint("id", "restaurant_id", name="uq_allergens_id_restaurant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class MenuItemAllergen(Base):
    __tablename__ = "menu_item_allergens"
    __table_args__ = (
        UniqueConstraint("menu_item_id", "allergen_id", name="uq_item_allergens_pair"),
        ForeignKeyConstraint(
            ["menu_item_id", "menu_version_id"],
            ["menu_items.id", "menu_items.menu_version_id"],
            name="fk_item_allergens_item_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["allergen_id", "restaurant_id"],
            ["allergens.id", "allergens.restaurant_id"],
            name="fk_item_allergens_allergen_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["menu_version_id", "restaurant_id"],
            ["menu_versions.id", "menu_versions.restaurant_id"],
            name="fk_item_allergens_version_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint("declaration in ('CONTAINS','MAY_CONTAIN','UNKNOWN')", name="declaration_valid"),
        Index("ix_item_allergens_version", "menu_version_id", "menu_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    menu_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    allergen_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    declaration: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    menu_version_id: Mapped[int] = mapped_column(Integer, nullable=False)


class OpeningHours(Base):
    __tablename__ = "opening_hours"
    __table_args__ = (
        UniqueConstraint("branch_id", "weekday", "start_time", "end_time", "effective_date", name="uq_opening_hours_slot"),
        CheckConstraint("weekday >= 0 and weekday <= 6", name="weekday_range"),
        Index("ix_opening_hours_branch_weekday", "branch_id", "weekday"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_date: Mapped[date | None] = mapped_column(Date)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class DeliveryZone(Base):
    __tablename__ = "delivery_zones"
    __table_args__ = (
        UniqueConstraint("branch_id", "code", name="uq_delivery_zones_branch_code"),
        UniqueConstraint("id", "branch_id", name="uq_delivery_zones_id_branch"),
        CheckConstraint("fee_minor >= 0", name="fee_nonnegative"),
        CheckConstraint("minimum_order_minor >= 0", name="minimum_nonnegative"),
        Index("ix_delivery_zones_branch_active", "branch_id", "active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fee_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_order_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class BranchItemAvailability(Base):
    __tablename__ = "branch_item_availability"
    __table_args__ = (
        UniqueConstraint("branch_id", "menu_item_id", name="uq_branch_item_availability_pair"),
        ForeignKeyConstraint(
            ["branch_id", "restaurant_id"],
            ["branches.id", "branches.restaurant_id"],
            name="fk_branch_item_availability_branch_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["menu_item_id", "menu_version_id"],
            ["menu_items.id", "menu_items.menu_version_id"],
            name="fk_branch_item_availability_item_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["menu_version_id", "restaurant_id"],
            ["menu_versions.id", "menu_versions.restaurant_id"],
            name="fk_branch_item_availability_version_tenant",
            ondelete="CASCADE",
        ),
        Index("ix_branch_item_availability_lookup", "branch_id", "menu_item_id", "available"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sold_out_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        UniqueConstraint("session_key", name="uq_sessions_global_key"),
        UniqueConstraint("id", "restaurant_id", "branch_id", name="uq_sessions_id_tenant"),
        ForeignKeyConstraint(
            ["branch_id", "restaurant_id"],
            ["branches.id", "branches.restaurant_id"],
            name="fk_sessions_branch_tenant",
            ondelete="RESTRICT",
        ),
        Index("ix_sessions_key", "session_key"),
        Index("ix_sessions_tenant_status", "restaurant_id", "branch_id", "status"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("status in ('ACTIVE','CLOSED')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_key: Mapped[str] = mapped_column(String(160), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    locale: Mapped[str] = mapped_column(String(32), nullable=False, default="zh-CN")
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationContactSnapshot(Base):
    __tablename__ = "conversation_contact_snapshots"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_contact_snapshots_session"),
        Index("ix_contact_snapshots_synthetic", "is_synthetic"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"), nullable=False
    )
    official_delivery_address: Mapped[str | None] = mapped_column(String(500))
    pending_delivery_address_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    phone: Mapped[str | None] = mapped_column(String(80))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "external_reference", name="uq_customers_restaurant_external"),
        UniqueConstraint("id", "restaurant_id", name="uq_customers_id_restaurant"),
        Index("ix_customers_restaurant_synthetic", "restaurant_id", "is_synthetic"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="RESTRICT"), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_orders_public_id"),
        UniqueConstraint("id", "restaurant_id", name="uq_orders_id_restaurant"),
        UniqueConstraint("id", "restaurant_id", "branch_id", name="uq_orders_id_tenant"),
        ForeignKeyConstraint(
            ["branch_id", "restaurant_id"],
            ["branches.id", "branches.restaurant_id"],
            name="fk_orders_branch_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["customer_id", "restaurant_id"],
            ["customers.id", "customers.restaurant_id"],
            name="fk_orders_customer_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["delivery_zone_id", "branch_id"],
            ["delivery_zones.id", "delivery_zones.branch_id"],
            name="fk_orders_delivery_zone_branch",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["session_id", "restaurant_id", "branch_id"],
            ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"],
            name="fk_orders_session_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("subtotal_minor >= 0", name="subtotal_nonnegative"),
        CheckConstraint("delivery_fee_minor >= 0", name="delivery_fee_nonnegative"),
        CheckConstraint("total_minor = subtotal_minor + delivery_fee_minor", name="total_matches"),
        CheckConstraint("length(currency) = 3", name="currency_iso3"),
        CheckConstraint("draft_version > 0", name="draft_version_positive"),
        CheckConstraint("fulfillment_type in ('delivery','pickup')", name="fulfillment_valid"),
        CheckConstraint(
            "status in ('DRAFT','CUSTOMER_CONFIRMED','SUBMISSION_STARTED','MERCHANT_PENDING',"
            "'MERCHANT_ACCEPTED','MERCHANT_REJECTED','SUBMISSION_FAILED','CANCELLED','COMPLETED')",
            name="status_valid",
        ),
        Index("ix_orders_tenant_status", "restaurant_id", "branch_id", "status"),
        Index("ix_orders_session_created", "session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="RESTRICT"), nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_fee_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fulfillment_type: Mapped[str] = mapped_column(String(24), nullable=False)
    delivery_zone_id: Mapped[int | None] = mapped_column(Integer)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    safety_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safety_hold_reason: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "restaurant_id"],
            ["orders.id", "orders.restaurant_id"],
            name="fk_order_items_order_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["menu_item_id", "menu_version_id"],
            ["menu_items.id", "menu_items.menu_version_id"],
            name="fk_order_items_item_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["menu_version_id", "restaurant_id"],
            ["menu_versions.id", "menu_versions.restaurant_id"],
            name="fk_order_items_version_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("unit_price_minor >= 0", name="unit_price_nonnegative"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("line_total_minor = unit_price_minor * quantity", name="line_total_matches"),
        Index("ix_order_items_order", "order_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    menu_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    modifier_snapshot_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    allergen_snapshot_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    line_total_minor: Mapped[int] = mapped_column(Integer, nullable=False)


class OrderConfirmation(Base):
    __tablename__ = "order_confirmations"
    __table_args__ = (
        UniqueConstraint("order_id", "draft_version", name="uq_confirmations_order_version"),
        UniqueConstraint("confirmation_fingerprint", name="uq_confirmations_fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(80), nullable=False)


class OrderEvent(Base):
    __tablename__ = "order_events"
    __table_args__ = (
        UniqueConstraint("order_id", "sequence_number", name="uq_order_events_sequence"),
        CheckConstraint("sequence_number > 0", name="sequence_positive"),
        Index("ix_order_events_order_occurred", "order_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "branch_id", "scope", "idempotency_key", name="uq_idempotency_tenant_scope_key"),
        ForeignKeyConstraint(
            ["branch_id", "restaurant_id"],
            ["branches.id", "branches.restaurant_id"],
            name="fk_idempotency_branch_tenant",
            ondelete="CASCADE",
        ),
        Index("ix_idempotency_resource", "resource_type", "resource_id"),
        Index("ix_idempotency_expiry", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SafetySessionCounter(Base):
    __tablename__ = "safety_session_counters"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_safety_counters_session"),
        ForeignKeyConstraint(
            ["session_id", "restaurant_id", "branch_id"],
            ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"],
            name="fk_safety_counters_session_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint("consecutive_low_confidence >= 0", name="low_confidence_nonnegative"),
        CheckConstraint("consecutive_misunderstandings >= 0", name="misunderstandings_nonnegative"),
        CheckConstraint("consecutive_corrections >= 0", name="corrections_nonnegative"),
        CheckConstraint("confirmation_failures >= 0", name="confirmation_failures_nonnegative"),
        CheckConstraint("is_synthetic = true", name="synthetic_only"),
        Index("ix_safety_counters_tenant", "restaurant_id", "branch_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    consecutive_low_confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_misunderstandings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_corrections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmation_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class SafetyDecisionRecord(Base):
    __tablename__ = "safety_decision_records"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_safety_decisions_public_id"),
        ForeignKeyConstraint(
            ["session_id", "restaurant_id", "branch_id"],
            ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"],
            name="fk_safety_decisions_session_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["order_id", "restaurant_id", "branch_id"],
            ["orders.id", "orders.restaurant_id", "orders.branch_id"],
            name="fk_safety_decisions_order_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("classification in ('AUTO_DRAFT','CONFIRM','HANDOFF','REFUSE')", name="classification_valid"),
        CheckConstraint(
            "reason_code is null or reason_code in ('EXPLICIT_HUMAN_REQUEST','SEVERE_ALLERGY',"
            "'CROSS_CONTAMINATION','REPEATED_MISUNDERSTANDING','AMBIGUOUS_ITEM','AMBIGUOUS_QUANTITY',"
            "'UNVERIFIED_ADDRESS','PRICE_UNAVAILABLE','MENU_DATA_MISSING','COMPLAINT','REFUND_REQUEST',"
            "'PAYMENT_DISPUTE','MERCHANT_REJECTED','MERCHANT_TIMEOUT','SYSTEM_FAILURE','LANGUAGE_UNSUPPORTED',"
            "'ABUSE_OR_SECURITY','REGULATED_ITEM','CROSS_TENANT_ACCESS','UNAUTHORIZED_ORDER_ACCESS',"
            "'FORGE_MERCHANT_ACCEPTANCE','BYPASS_CONFIRMATION','CARD_DATA_STORAGE',"
            "'UNSUPPORTED_SAFETY_GUARANTEE','INTERNAL_SECRET_EXTRACTION','SECURITY_ATTACK')",
            name="reason_valid",
        ),
        CheckConstraint(
            "(classification in ('HANDOFF','REFUSE') and reason_code is not null) or "
            "(classification in ('AUTO_DRAFT','CONFIRM') and reason_code is null)",
            name="classification_reason_consistent",
        ),
        CheckConstraint("is_synthetic = true", name="synthetic_only"),
        Index("ix_safety_decisions_session_created", "session_id", "created_at"),
        Index("ix_safety_decisions_tenant_class", "restaurant_id", "branch_id", "classification"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_id: Mapped[int | None] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    explanation_code: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    required_confirmations_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risk_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    blocked_actions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metric_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class HandoffCase(Base):
    __tablename__ = "handoff_cases"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_handoff_cases_public_id"),
        ForeignKeyConstraint(
            ["session_id", "restaurant_id", "branch_id"],
            ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"],
            name="fk_handoff_cases_session_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["order_id", "restaurant_id", "branch_id"],
            ["orders.id", "orders.restaurant_id", "orders.branch_id"],
            name="fk_handoff_cases_order_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status in ('NOT_REQUIRED','REQUESTED','PENDING','SIMULATED_AGENT_ASSIGNED',"
            "'SIMULATED_AGENT_CONNECTED','RESOLVED','FAILED','CANCELLED')",
            name="status_valid",
        ),
        CheckConstraint(
            "reason_code in ('EXPLICIT_HUMAN_REQUEST','SEVERE_ALLERGY','CROSS_CONTAMINATION',"
            "'REPEATED_MISUNDERSTANDING','AMBIGUOUS_ITEM','AMBIGUOUS_QUANTITY','UNVERIFIED_ADDRESS',"
            "'PRICE_UNAVAILABLE','MENU_DATA_MISSING','COMPLAINT','REFUND_REQUEST','PAYMENT_DISPUTE',"
            "'MERCHANT_REJECTED','MERCHANT_TIMEOUT','SYSTEM_FAILURE','LANGUAGE_UNSUPPORTED',"
            "'ABUSE_OR_SECURITY','REGULATED_ITEM')",
            name="reason_valid",
        ),
        CheckConstraint("decision_classification = 'HANDOFF'", name="classification_handoff"),
        CheckConstraint("priority in ('LOW','NORMAL','HIGH','CRITICAL')", name="priority_valid"),
        CheckConstraint("summary_version > 0", name="summary_version_positive"),
        CheckConstraint(
            "failure_code is null or failure_code in ('NO_AGENT_AVAILABLE','QUEUE_TIMEOUT','ASSIGNMENT_FAILED',"
            "'CONNECTION_FAILED','CASE_CANCELLED','SYSTEM_ERROR')",
            name="failure_code_valid",
        ),
        CheckConstraint("is_synthetic = true", name="synthetic_only"),
        Index("ix_handoff_cases_tenant_status", "restaurant_id", "branch_id", "status"),
        Index(
            "uq_handoff_cases_active_session",
            "session_id",
            unique=True,
            sqlite_where=text(
                "status in ('REQUESTED','PENDING','SIMULATED_AGENT_ASSIGNED','SIMULATED_AGENT_CONNECTED')"
            ),
            postgresql_where=text(
                "status in ('REQUESTED','PENDING','SIMULATED_AGENT_ASSIGNED','SIMULATED_AGENT_CONNECTED')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="REQUESTED")
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="NORMAL")
    decision_classification: Mapped[str] = mapped_column(String(24), nullable=False, default="HANDOFF")
    risk_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    blocked_actions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    summary_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    resolution_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class HandoffEvent(Base):
    __tablename__ = "handoff_events"
    __table_args__ = (
        UniqueConstraint("handoff_case_id", "sequence_number", name="uq_handoff_events_sequence"),
        CheckConstraint("sequence_number > 0", name="sequence_positive"),
        CheckConstraint(
            "actor_type in ('CUSTOMER','ORCHESTRATOR','SIMULATION_PROVIDER','SYSTEM')",
            name="actor_type_valid",
        ),
        Index("ix_handoff_events_case_occurred", "handoff_case_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    handoff_case_id: Mapped[int] = mapped_column(ForeignKey("handoff_cases.id", ondelete="CASCADE"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class SpeechTurnRecord(Base):
    __tablename__ = "speech_turn_records"
    __table_args__ = (
        UniqueConstraint("public_id", name="uq_speech_turns_public_id"),
        ForeignKeyConstraint(
            ["session_id", "restaurant_id", "branch_id"],
            ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"],
            name="fk_speech_turns_session_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["order_id", "restaurant_id", "branch_id"],
            ["orders.id", "orders.restaurant_id", "orders.branch_id"],
            name="fk_speech_turns_order_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint("direction in ('INPUT','OUTPUT')", name="direction_valid"),
        CheckConstraint(
            "provider_mode in ('DISABLED','REPLAY','LOCAL','LIVE')",
            name="provider_mode_valid",
        ),
        CheckConstraint(
            "outcome in ('SUCCESS','NO_SPEECH','LOW_CONFIDENCE','TRUNCATED','PROVIDER_TIMEOUT',"
            "'PROVIDER_ERROR','UNSUPPORTED_LANGUAGE','VALIDATION_ERROR')",
            name="outcome_valid",
        ),
        CheckConstraint("duration_ms is null or duration_ms >= 0", name="duration_nonnegative"),
        CheckConstraint("sample_rate_hz > 0", name="sample_rate_positive"),
        CheckConstraint("length(audio_sha256) = 64", name="audio_sha256_length"),
        CheckConstraint("is_synthetic = true", name="synthetic_only"),
        Index("ix_speech_turns_session_created", "session_id", "created_at"),
        Index("ix_speech_turns_tenant_outcome", "restaurant_id", "branch_id", "outcome"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_id: Mapped[int | None] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    audio_encoding: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_rate_hz: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    audio_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fixture_id: Mapped[str | None] = mapped_column(String(160))
    detected_locale: Mapped[str | None] = mapped_column(String(32))
    response_locale: Mapped[str | None] = mapped_column(String(32))
    confidence_bucket: Mapped[str | None] = mapped_column(String(24))
    decision_classification: Mapped[str | None] = mapped_column(String(24))
    reason_code: Mapped[str | None] = mapped_column(String(80))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(80), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
