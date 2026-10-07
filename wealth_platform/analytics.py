from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from math import ceil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import Transaction, Budget, User
from currency import convert


async def dashboard_analytics(db: AsyncSession, user: User):
    today = date.today()
    start = today.replace(day=1)

    result = await db.execute(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.transaction_date <= today,
        ).order_by(Transaction.transaction_date)
    )
    transactions = result.scalars().all()

    income = Decimal("0")
    expenses = Decimal("0")
    category = defaultdict(Decimal)
    daily = defaultdict(lambda: {"income": Decimal("0"), "expense": Decimal("0")})

    for t in transactions:
        value = convert(t.amount, t.currency, user.base_currency)
        if t.kind == "income":
            income += value
            daily[t.transaction_date.isoformat()]["income"] += value
        else:
            expenses += value
            daily[t.transaction_date.isoformat()]["expense"] += value
            if t.transaction_date >= start:
                category[t.category] += value

    month_expenses = sum(
        convert(t.amount, t.currency, user.base_currency)
        for t in transactions
        if t.kind == "expense" and t.transaction_date >= start
    )

    elapsed = max((today - start).days + 1, 1)
    velocity = month_expenses / Decimal(elapsed)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    days_in_month = (next_month - start).days
    projected = (velocity * Decimal(days_in_month)).quantize(Decimal("0.01"))

    budgets_result = await db.execute(
        select(Budget).where(
            Budget.user_id == user.id,
            Budget.month == today.month,
            Budget.year == today.year,
        )
    )
    budgets = budgets_result.scalars().all()
    total_budget = sum((b.amount for b in budgets), Decimal("0"))
    burn = (month_expenses / total_budget * 100) if total_budget else Decimal("0")

    threshold_dates = []
    if total_budget > 0 and velocity > 0:
        for threshold in (Decimal("0.5"), Decimal("0.75"), Decimal("1.0")):
            target = total_budget * threshold
            remaining = target - month_expenses
            if remaining <= 0:
                crossing = today
            else:
                crossing = today + timedelta(days=ceil(float(remaining / velocity)))
            threshold_dates.append({
                "threshold": int(threshold * 100),
                "date": crossing.isoformat(),
            })

    series = [
        {"date": d, "income": float(v["income"]), "expense": float(v["expense"])}
        for d, v in sorted(daily.items())
    ]

    return {
        "base_currency": user.base_currency,
        "total_income": income,
        "total_expenses": expenses,
        "net_worth_flow": income - expenses,
        "month_expenses": month_expenses,
        "daily_velocity": velocity.quantize(Decimal("0.01")),
        "projected_month_end_spend": projected,
        "budget_total": total_budget,
        "budget_burn_percent": burn.quantize(Decimal("0.01")),
        "threshold_dates": threshold_dates,
        "category_breakdown": [
            {"category": k, "amount": v.quantize(Decimal("0.01"))}
            for k, v in sorted(category.items(), key=lambda x: x[1], reverse=True)
        ],
        "timeline": series,
    }
