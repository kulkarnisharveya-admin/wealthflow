from datetime import date
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


CURRENCIES = {"USD", "EUR", "GBP", "INR"}
KINDS = {"income", "expense"}


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=120)
    base_currency: str = "USD"

    @field_validator("base_currency")
    @classmethod
    def currency(cls, value: str) -> str:
        value = value.upper()
        if value not in CURRENCIES:
            raise ValueError("Unsupported currency")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    base_currency: str


class TransactionCreate(BaseModel):
    transaction_date: date
    kind: str
    amount: Decimal = Field(gt=0)
    currency: str = "USD"
    category: str = Field(min_length=1, max_length=80)
    merchant: str = Field(default="", max_length=160)
    note: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list)

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        value = value.lower()
        if value not in KINDS:
            raise ValueError("kind must be income or expense")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        value = value.upper()
        if value not in CURRENCIES:
            raise ValueError("Unsupported currency")
        return value


class TransactionOut(BaseModel):
    id: int
    transaction_date: date
    kind: str
    amount: Decimal
    currency: str
    amount_base: Decimal
    category: str
    merchant: str
    note: str
    tags: list[str]


class BudgetCreate(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    amount: Decimal = Field(gt=0)
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    amount: Decimal
    month: int
    year: int


class RecurringCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: str
    amount: Decimal = Field(gt=0)
    currency: str = "USD"
    category: str = Field(min_length=1, max_length=80)
    frequency: str
    next_due: date
    active: bool = True

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, value: str) -> str:
        value = value.lower()
        if value not in KINDS:
            raise ValueError("kind must be income or expense")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        value = value.upper()
        if value not in CURRENCIES:
            raise ValueError("Unsupported currency")
        return value

    @field_validator("frequency")
    @classmethod
    def validate_frequency(cls, value: str) -> str:
        value = value.lower()
        if value not in {"weekly", "monthly", "yearly"}:
            raise ValueError("frequency must be weekly, monthly, or yearly")
        return value


class RecurringOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    kind: str
    amount: Decimal
    currency: str
    category: str
    frequency: str
    next_due: date
    active: bool
