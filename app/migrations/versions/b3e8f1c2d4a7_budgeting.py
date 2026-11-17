"""Budgeting: periods, budget lines, income, and recurring income and variable bills

Revision ID: b3e8f1c2d4a7
Revises: a1d5e9c3f702
Create Date: 2026-11-06

Additive, apart from one constraint. The `budgets` table existed from the start as a monthly
cap per category that nothing ever used; it now holds a budget *line's* amount per month, so
it gains `line_id` and its uniqueness moves from (category, month) to (line, month). Any rows
it already had are kept: each category they named becomes a Közös line covering that
category, and the rows are attached to it. The old `category_id` column stays, unused - a
migration here never drops a column.

Existing recurring payments become what they always were: fixed expenses, owned by nobody in
particular (Közös), with no payer and no split. Nothing they generate changes.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3e8f1c2d4a7"
down_revision: str | None = "a1d5e9c3f702"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "budget_periods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("opened_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("month", name="uq_budget_periods_month"),
        sa.UniqueConstraint("starts_on", name="uq_budget_periods_starts_on"),
    )
    op.create_index("ix_budget_periods_month", "budget_periods", ["month"])
    op.create_index("ix_budget_periods_starts_on", "budget_periods", ["starts_on"])

    op.create_table(
        "budget_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("owner_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(length=14), nullable=False, server_default="valtozo"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_budget_lines_owner_id", "budget_lines", ["owner_id"])

    op.create_table(
        "budget_line_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("line_id", sa.Uuid(),
                  sa.ForeignKey("budget_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Uuid(),
                  sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("line_id", "category_id", name="uq_budget_line_categories"),
    )
    op.create_index("ix_budget_line_categories_line_id", "budget_line_categories", ["line_id"])
    op.create_index(
        "ix_budget_line_categories_category_id", "budget_line_categories", ["category_id"]
    )

    op.create_table(
        "income_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("recurring_id", sa.Uuid(),
                  sa.ForeignKey("recurring_payments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("amount > 0", name="ck_income_entries_positive"),
    )
    op.create_index("ix_income_entries_user_id", "income_entries", ["user_id"])
    op.create_index("ix_income_entries_received_on", "income_entries", ["received_on"])
    op.create_index("ix_income_entries_recurring_id", "income_entries", ["recurring_id"])

    # --- budgets: from a cap per category to an amount per line ------------------
    op.add_column("budgets", sa.Column("line_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_budgets_line_id", "budgets", "budget_lines", ["line_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_budgets_line_id", "budgets", ["line_id"])
    op.drop_constraint("uq_budget_category_month", "budgets", type_="unique")
    _move_budgets_onto_lines()
    op.alter_column("budgets", "line_id", nullable=False)
    op.create_unique_constraint("uq_budgets_line_month", "budgets", ["line_id", "month"])

    # --- recurring: income, variable amounts, whose and who pays ------------------
    op.add_column("recurring_payments", sa.Column(
        "direction", sa.String(length=10), nullable=False, server_default="expense"))
    op.add_column("recurring_payments", sa.Column(
        "amount_mode", sa.String(length=10), nullable=False, server_default="fixed"))
    op.add_column("recurring_payments", sa.Column(
        "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("recurring_payments", sa.Column(
        "payer_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("recurring_payments", sa.Column("default_shares", sa.JSON(), nullable=True))

    op.add_column("recurring_charges", sa.Column(
        "income_id", sa.Uuid(),
        sa.ForeignKey("income_entries.id", ondelete="SET NULL"), nullable=True))


def _move_budgets_onto_lines() -> None:
    """Give every existing budget row a line: one Közös line per category it named.

    A row with no category was a cap on the whole month. It becomes a line of its own that
    covers no category, which keeps the amount visible in the plan without claiming any
    receipt - you can delete it there, or give it categories.
    """
    bind = op.get_bind()
    groups = bind.execute(sa.text(
        "SELECT DISTINCT b.category_id, c.name FROM budgets b "
        "LEFT JOIN categories c ON c.id = b.category_id"
    )).all()
    for order, (category_id, category_name) in enumerate(groups, start=1):
        line_id = uuid.uuid4()
        bind.execute(
            sa.text(
                "INSERT INTO budget_lines (id, name, kind, sort_order, active) "
                "VALUES (:id, :name, 'valtozo', :order, true)"
            ),
            {"id": line_id, "name": category_name or "Teljes havi költés", "order": order},
        )
        if category_id is not None:
            bind.execute(
                sa.text(
                    "INSERT INTO budget_line_categories (id, line_id, category_id) "
                    "VALUES (:id, :line, :category)"
                ),
                {"id": uuid.uuid4(), "line": line_id, "category": category_id},
            )
            bind.execute(
                sa.text("UPDATE budgets SET line_id = :line WHERE category_id = :category"),
                {"line": line_id, "category": category_id},
            )
        else:
            bind.execute(
                sa.text("UPDATE budgets SET line_id = :line WHERE category_id IS NULL"),
                {"line": line_id},
            )


def downgrade() -> None:
    op.drop_column("recurring_charges", "income_id")
    for column in ("default_shares", "payer_id", "owner_id", "amount_mode", "direction"):
        op.drop_column("recurring_payments", column)
    op.drop_constraint("uq_budgets_line_month", "budgets", type_="unique")
    op.drop_index("ix_budgets_line_id", table_name="budgets")
    op.drop_constraint("fk_budgets_line_id", "budgets", type_="foreignkey")
    op.drop_column("budgets", "line_id")
    op.create_unique_constraint("uq_budget_category_month", "budgets", ["category_id", "month"])
    op.drop_table("income_entries")
    op.drop_table("budget_line_categories")
    op.drop_table("budget_lines")
    op.drop_table("budget_periods")
