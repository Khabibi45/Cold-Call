"""Creation des tables initiales : users, leads, calls

Revision ID: 0001
Revises: None
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Table users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("oauth_provider", sa.String(50), nullable=True),
        sa.Column("oauth_id", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=True),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("subscription_plan", sa.String(50), server_default="free", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # --- Table leads ---
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("place_id", sa.String(255), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="google_maps"),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("phone_e164", sa.String(20), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("has_website", sa.Boolean(), server_default=sa.text("false"), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country", sa.String(50), server_default="FR", nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("review_count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("photo_count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("maps_url", sa.String(500), nullable=True),
        sa.Column("lead_score", sa.Integer(), server_default="0", nullable=True),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leads_place_id", "leads", ["place_id"], unique=True)
    op.create_index("ix_leads_phone_e164", "leads", ["phone_e164"], unique=True)
    op.create_index("ix_leads_city", "leads", ["city"])
    op.create_index("ix_leads_category", "leads", ["category"])
    op.create_index("ix_leads_has_website", "leads", ["has_website"])
    op.create_index("ix_leads_lead_score", "leads", ["lead_score"])
    op.create_index("ix_leads_city_category", "leads", ["city", "category"])
    op.create_index("ix_leads_has_website_score", "leads", ["has_website", "lead_score"])

    # --- Table calls ---
    op.create_table(
        "calls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="no_answer"),
        sa.Column("duration_seconds", sa.Float(), server_default="0", nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("callback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("twilio_call_sid", sa.String(50), nullable=True),
        sa.Column("recording_url", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calls_lead_id", "calls", ["lead_id"])
    op.create_index("ix_calls_user_id", "calls", ["user_id"])
    op.create_index("ix_calls_status", "calls", ["status"])
    op.create_index("ix_calls_callback_at", "calls", ["callback_at"])


def downgrade() -> None:
    op.drop_table("calls")
    op.drop_table("leads")
    op.drop_table("users")
