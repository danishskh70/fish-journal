import datetime as dt
from decimal import Decimal
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, Field, PlainSerializer, field_validator

_S = PlainSerializer(lambda v: float(v), return_type=float, when_used="json")

Num = Annotated[Decimal, _S]  # output number (JSON number, not string)
PosQty = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3), _S]
NonNegQty = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=3), _S]
PosMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2), _S]
NonNegMoney = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2), _S]


class PaymentMode(str, Enum):
    cash = "cash"
    upi = "upi"


def _clean(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("must not be empty")
    return v


# ---------- masters ----------
class FishIn(BaseModel):
    name: str = Field(max_length=100)
    _c = field_validator("name")(_clean)


class FishPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None


class FishOut(BaseModel):
    id: int
    name: str
    is_active: bool


class PartyIn(BaseModel):
    name: str = Field(max_length=150)
    phone: Optional[str] = Field(default=None, max_length=30)
    opening_balance: NonNegMoney = Decimal("0")  # existing outstanding amount; default zero
    opening_balance_date: dt.date = Field(default_factory=dt.date.today)
    _c = field_validator("name")(_clean)


class OpeningBalanceIn(BaseModel):
    amount: NonNegMoney
    balance_date: dt.date = Field(default_factory=dt.date.today)


class OpeningBalanceOut(BaseModel):
    amount: Num
    balance_date: Optional[dt.date]


class PartyPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=150)
    phone: Optional[str] = Field(default=None, max_length=30)
    is_active: Optional[bool] = None


class SupplierOut(BaseModel):
    id: int
    name: str
    phone: Optional[str]
    is_active: bool
    opening_balance: Num
    opening_balance_date: Optional[dt.date]


class RateIn(BaseModel):
    rate: PosMoney


class RateOut(BaseModel):
    fish_id: int
    fish_name: str
    rate: Num


class HotelOut(BaseModel):
    id: int
    name: str
    phone: Optional[str]
    is_active: bool
    opening_balance: Num
    opening_balance_date: Optional[dt.date]
    rates: list[RateOut]


# ---------- journal ----------
class JournalCreate(BaseModel):
    business_date: Optional[dt.date] = None


class OpeningItem(BaseModel):
    fish_id: int
    quantity: Optional[NonNegQty] = None  # omitted -> accept suggested value


class OpeningIn(BaseModel):
    items: list[OpeningItem] = Field(min_length=1)


class ClosingItem(BaseModel):
    fish_id: int
    quantity: NonNegQty


class ClosingIn(BaseModel):
    stocks: list[ClosingItem]
    cash_amount: NonNegMoney
    upi_amount: NonNegMoney


class ReopenIn(BaseModel):
    confirm: bool = False


class StockRow(BaseModel):
    fish_id: int
    fish_name: str
    previous_closing: Optional[Num]
    suggested_opening: Optional[Num]
    opening_quantity: Optional[Num]
    opening_confirmed: bool
    purchased: Num
    available: Optional[Num]
    hotel_sold: Num
    normal_customer: Optional[Num]
    remaining: Optional[Num]
    current_stock: Optional[Num]


class StockTotals(BaseModel):
    previous_closing: Optional[Num]
    opening_quantity: Optional[Num]
    purchased: Optional[Num]
    available: Optional[Num]
    hotel_sold: Optional[Num]
    normal_customer: Optional[Num]
    remaining: Optional[Num]


class StockOut(BaseModel):
    rows: list[StockRow]
    totals: StockTotals


# ---------- purchases ----------
class PurchaseUpdate(BaseModel):
    supplier_id: int
    fish_id: int
    quantity: PosQty
    rate: PosMoney
    paid_now: NonNegMoney = Decimal("0")
    payment_mode: Optional[PaymentMode] = None


class PurchaseIn(PurchaseUpdate):
    journal_id: int


class PurchaseOut(BaseModel):
    id: int
    journal_id: int
    business_date: dt.date
    supplier_id: int
    supplier_name: str
    fish_id: int
    fish_name: str
    quantity: Num
    rate: Num
    amount: Num
    paid_now: Num
    payment_mode: Optional[PaymentMode]
    due_created: Num


class PurchaseTotals(BaseModel):
    total_quantity: Num
    total_amount: Num
    total_paid_now: Num
    total_due_created: Num


class PurchaseList(BaseModel):
    entries: list[PurchaseOut]
    totals: PurchaseTotals


# ---------- hotel sales ----------
class HotelSaleUpdate(BaseModel):
    hotel_id: int
    fish_id: int
    quantity: PosQty
    rate: Optional[PosMoney] = None  # omitted -> hotel's agreed rate


class HotelSaleIn(HotelSaleUpdate):
    journal_id: int


class HotelSaleOut(BaseModel):
    id: int
    journal_id: int
    business_date: dt.date
    hotel_id: int
    hotel_name: str
    fish_id: int
    fish_name: str
    quantity: Num
    rate: Num
    rate_overridden: bool
    amount: Num


class HotelSaleList(BaseModel):
    entries: list[HotelSaleOut]
    total_quantity: Num
    total_amount: Num


# ---------- payments ----------
class SupplierPaymentIn(BaseModel):
    supplier_id: int
    amount: PosMoney
    payment_mode: PaymentMode
    payment_date: dt.date = Field(default_factory=dt.date.today)


class SupplierPaymentOut(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str
    amount: Num
    payment_mode: PaymentMode
    payment_date: dt.date
    purchase_id: Optional[int]
    is_immediate: bool


class HotelPaymentIn(BaseModel):
    hotel_id: int
    amount: PosMoney
    payment_mode: PaymentMode
    payment_date: dt.date = Field(default_factory=dt.date.today)


class HotelPaymentOut(BaseModel):
    id: int
    hotel_id: int
    hotel_name: str
    amount: Num
    payment_mode: PaymentMode
    payment_date: dt.date


# ---------- journal detail ----------
class NormalQty(BaseModel):
    fish_id: int
    fish_name: str
    quantity: Num


class SalesRecord(BaseModel):
    hotel_sales: list[HotelSaleOut]
    total_hotel_quantity: Num
    total_hotel_amount: Num
    normal_customer: list[NormalQty]
    total_normal_customer_quantity: Optional[Num]


class MoneyRecord(BaseModel):
    cash_amount: Num
    upi_amount: Num
    total: Num


class Balance(BaseModel):
    id: int
    name: str
    outstanding: Num


class HotelInfo(BaseModel):
    sales_total: Num
    payments_received: list[HotelPaymentOut]
    outstanding_balances: list[Balance]


class SupplierInfo(BaseModel):
    paid_immediately_total: Num
    dues_created_total: Num
    later_payments: list[SupplierPaymentOut]
    outstanding_balances: list[Balance]


class JournalDetail(BaseModel):
    id: int
    business_date: dt.date
    status: str
    closed_at: Optional[dt.datetime]
    stock: StockOut
    purchases: PurchaseList
    sales: SalesRecord
    money: Optional[MoneyRecord]
    hotel_info: HotelInfo
    supplier_info: SupplierInfo


class ClosePreview(BaseModel):
    can_close: bool
    problems: list[str]
    stock: StockOut
    sales_normal_customer: list[NormalQty]
    money: MoneyRecord


class HistoryRow(BaseModel):
    id: int
    business_date: dt.date
    status: str
    cash_amount: Optional[Num]
    upi_amount: Optional[Num]
    total_money: Optional[Num]


# ---------- accounts ----------
class LedgerEntry(BaseModel):
    date: dt.date
    entry_type: str  # opening_balance | sale | purchase | immediate_payment | payment
    reference_id: int
    fish_id: Optional[int] = None
    fish_name: Optional[str] = None
    quantity: Optional[Num] = None
    rate: Optional[Num] = None
    amount: Num
    paid_now: Optional[Num] = None
    due_created: Optional[Num] = None
    payment_mode: Optional[PaymentMode] = None
    balance_change: Num
    running_balance: Num


class Ledger(BaseModel):
    id: int
    name: str
    from_date: Optional[dt.date]
    to_date: Optional[dt.date]
    previous_balance: Num
    entries: list[LedgerEntry]
    closing_balance: Num


class MonthlyHotelSummary(BaseModel):
    hotel_id: int
    hotel_name: str
    year: int
    month: int
    opening_outstanding: Num
    fish_taken: Num
    payments_received: Num
    closing_outstanding: Num


class DashboardJournal(BaseModel):
    id: int
    business_date: dt.date
    status: str


class Dashboard(BaseModel):
    business_date: dt.date
    journal: Optional[DashboardJournal]
    stock_overview: list[StockRow]
    hotel_outstanding_total: Num
    supplier_outstanding_total: Num
    hotels: list[Balance]
    suppliers: list[Balance]
