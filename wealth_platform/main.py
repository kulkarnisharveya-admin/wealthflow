from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from analytics import dashboard_analytics
from auth import create_access_token, get_current_user, hash_password, verify_password
from currency import convert
from database import SessionLocal, get_db, init_db, settings
from exports import csv_bytes, get_export_rows, xlsx_bytes
from models import Budget, RecurringTransaction, Transaction, User
from recurring import process_recurring
from schemas import (
    BudgetCreate,
    BudgetOut,
    LoginRequest,
    RecurringCreate,
    RecurringOut,
    TransactionCreate,
    TransactionOut,
    UserCreate,
    UserOut,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "INR"}


async def recurring_worker(stop_event: asyncio.Event) -> None:
    """Run the recurring-transaction processor once a minute."""
    while not stop_event.is_set():
        try:
            async with SessionLocal() as db:
                await process_recurring(db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not crash the API because the background recurring job failed.
            print(f"Recurring engine error: {exc}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(recurring_worker(stop_event))

    try:
        yield
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(worker_task, timeout=5)
        except asyncio.TimeoutError:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="WealthFlow",
    version="1.0.1",
    lifespan=lifespan,
)

# Use absolute paths so the app works even when Uvicorn is started from another
# working directory.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Always convert HTTPException into a real Response object."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return JSON instead of leaking a Python traceback to the browser."""
    import traceback

    traceback.print_exception(type(exc), exc, exc.__traceback__)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request})


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "wealthflow"}


# -----------------------------------------------------------------------------
# Authentication
# -----------------------------------------------------------------------------


def set_auth_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        "access_token",
        create_access_token(user_id),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )


@app.post("/api/auth/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(
    data: UserCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    email = str(data.email).lower().strip()

    exists = await db.scalar(select(User).where(User.email == email))
    if exists:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name.strip(),
        base_currency=data.base_currency.upper(),
    )

    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except Exception:
        await db.rollback()
        raise

    set_auth_cookie(response, user.id)
    return user


@app.post("/api/auth/login", response_model=UserOut)
async def login(
    data: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    email = str(data.email).lower().strip()
    user = await db.scalar(select(User).where(User.email == email))

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    set_auth_cookie(response, user.id)
    return user


@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@app.get("/api/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@app.patch("/api/profile/currency", response_model=UserOut)
async def update_currency(
    currency: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    currency = currency.upper().strip()
    if currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail="Unsupported currency")

    user.base_currency = currency
    await db.commit()
    await db.refresh(user)
    return user


# -----------------------------------------------------------------------------
# Transactions
# -----------------------------------------------------------------------------


def parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def normalize_tags(tags: list[str]) -> str:
    return ",".join(
        sorted({tag.strip().lower() for tag in tags if tag and tag.strip()})
    )


def transaction_out(tx: Transaction, user: User) -> TransactionOut:
    return TransactionOut(
        id=tx.id,
        transaction_date=tx.transaction_date,
        kind=tx.kind,
        amount=tx.amount,
        currency=tx.currency,
        amount_base=convert(tx.amount, tx.currency, user.base_currency),
        category=tx.category,
        merchant=tx.merchant,
        note=tx.note,
        tags=parse_tags(tx.tags),
    )


@app.post("/api/transactions", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    data: TransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tx = Transaction(
        user_id=user.id,
        transaction_date=data.transaction_date,
        kind=data.kind,
        amount=data.amount,
        currency=data.currency.upper(),
        category=data.category.strip(),
        merchant=data.merchant.strip(),
        note=data.note.strip(),
        tags=normalize_tags(data.tags),
    )

    db.add(tx)
    try:
        await db.commit()
        await db.refresh(tx)
    except Exception:
        await db.rollback()
        raise

    return transaction_out(tx, user)


@app.get("/api/transactions", response_model=list[TransactionOut])
async def list_transactions(
    q: str | None = None,
    kind: str | None = None,
    categories: str | None = None,
    tags: str | None = None,
    min_amount: Decimal | None = Query(default=None, ge=0),
    max_amount: Decimal | None = Query(default=None, ge=0),
    start_date: date | None = None,
    end_date: date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(status_code=400, detail="min_amount cannot exceed max_amount")

    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date cannot be after end_date")

    filters = [Transaction.user_id == user.id]

    if kind:
        kind = kind.lower().strip()
        if kind not in {"income", "expense"}:
            raise HTTPException(status_code=400, detail="kind must be income or expense")
        filters.append(Transaction.kind == kind)

    if categories:
        cats = [x.strip() for x in categories.split(",") if x.strip()]
        if cats:
            filters.append(Transaction.category.in_(cats))

    if start_date:
        filters.append(Transaction.transaction_date >= start_date)
    if end_date:
        filters.append(Transaction.transaction_date <= end_date)

    if q:
        needle = f"%{q.strip().lower()}%"
        filters.append(
            or_(
                func.lower(Transaction.note).like(needle),
                func.lower(Transaction.merchant).like(needle),
                func.lower(Transaction.category).like(needle),
            )
        )

    result = await db.execute(
        select(Transaction)
        .where(and_(*filters))
        .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
        .limit(1000)
    )

    requested_tags = [x.strip().lower() for x in tags.split(",") if x.strip()] if tags else []
    output: list[TransactionOut] = []

    for tx in result.scalars().all():
        base_amount = convert(tx.amount, tx.currency, user.base_currency)

        if min_amount is not None and base_amount < min_amount:
            continue
        if max_amount is not None and base_amount > max_amount:
            continue

        tx_tags = parse_tags(tx.tags)
        if requested_tags and not set(requested_tags).issubset(set(tx_tags)):
            continue

        output.append(transaction_out(tx, user))

    return output


@app.delete("/api/transactions/{transaction_id}")
async def delete_transaction(
    transaction_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tx = await db.scalar(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == user.id,
        )
    )

    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    await db.delete(tx)
    await db.commit()
    return {"ok": True}


# -----------------------------------------------------------------------------
# Budgets
# -----------------------------------------------------------------------------


@app.post("/api/budgets", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
async def create_budget(
    data: BudgetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    budget = await db.scalar(
        select(Budget).where(
            Budget.user_id == user.id,
            Budget.category == data.category,
            Budget.month == data.month,
            Budget.year == data.year,
        )
    )

    if budget:
        budget.amount = data.amount
    else:
        budget = Budget(user_id=user.id, **data.model_dump())
        db.add(budget)

    try:
        await db.commit()
        await db.refresh(budget)
    except Exception:
        await db.rollback()
        raise

    return budget


@app.get("/api/budgets", response_model=list[BudgetOut])
async def list_budgets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Budget)
        .where(Budget.user_id == user.id)
        .order_by(Budget.year.desc(), Budget.month.desc(), Budget.category.asc())
    )
    return result.scalars().all()


# -----------------------------------------------------------------------------
# Recurring transactions
# -----------------------------------------------------------------------------


@app.post("/api/recurring", response_model=RecurringOut, status_code=status.HTTP_201_CREATED)
async def create_recurring(
    data: RecurringCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = RecurringTransaction(
        user_id=user.id,
        name=data.name.strip(),
        kind=data.kind,
        amount=data.amount,
        currency=data.currency.upper(),
        category=data.category.strip(),
        frequency=data.frequency,
        next_due=data.next_due,
        active=data.active,
    )

    db.add(item)
    try:
        await db.commit()
        await db.refresh(item)
    except Exception:
        await db.rollback()
        raise

    return item


@app.get("/api/recurring", response_model=list[RecurringOut])
async def list_recurring(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RecurringTransaction)
        .where(RecurringTransaction.user_id == user.id)
        .order_by(RecurringTransaction.next_due.asc(), RecurringTransaction.id.asc())
    )
    return result.scalars().all()


@app.delete("/api/recurring/{recurring_id}")
async def delete_recurring(
    recurring_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await db.scalar(
        select(RecurringTransaction).where(
            RecurringTransaction.id == recurring_id,
            RecurringTransaction.user_id == user.id,
        )
    )

    if not item:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")

    # Keep history intact; deactivate the recurring rule instead of deleting it.
    item.active = False
    await db.commit()
    return {"ok": True}


# -----------------------------------------------------------------------------
# Analytics and exports
# -----------------------------------------------------------------------------


@app.get("/api/analytics")
async def analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await dashboard_analytics(db, user)


@app.get("/api/export/{fmt}")
async def export_data(
    fmt: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fmt = fmt.lower().strip()
    rows = await get_export_rows(db, user)

    if fmt == "csv":
        data = csv_bytes(rows)
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": "attachment; filename=wealthflow-transactions.csv",
                "X-Content-Type-Options": "nosniff",
            },
        )

    if fmt == "xlsx":
        data = xlsx_bytes(rows)
        return StreamingResponse(
            iter([data]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename=wealthflow-transactions.xlsx",
                "X-Content-Type-Options": "nosniff",
            },
        )

    raise HTTPException(status_code=400, detail="Format must be csv or xlsx")


@app.get("/api/fx")
async def fx():
    return {
        "USD": 1,
        "EUR": 1.08,
        "GBP": 1.27,
        "INR": 0.0120,
    }
