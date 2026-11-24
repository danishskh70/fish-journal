import datetime as dt
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

QTY = Numeric(12, 3)
MONEY = Numeric(12, 2)


def _now():
    return dt.datetime.now(dt.timezone.utc)


class Fish(Base):
    __tablename__ = "fish"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Base):
    __tablename__ = "supplier"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Hotel(Base):
    __tablename__ = "hotel"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rates: Mapped[list["HotelRate"]] = relationship(back_populates="hotel", cascade="all, delete-orphan")


class HotelRate(Base):
    __tablename__ = "hotel_rate"
    __table_args__ = (UniqueConstraint("hotel_id", "fish_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotel.id", ondelete="CASCADE"))
    fish_id: Mapped[int] = mapped_column(ForeignKey("fish.id"))
    rate: Mapped[Decimal] = mapped_column(MONEY)
    hotel: Mapped[Hotel] = relationship(back_populates="rates")
    fish: Mapped[Fish] = relationship()


class Journal(Base):
    __tablename__ = "journal"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[dt.date] = mapped_column(Date, unique=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    cash_amount: Mapped[Optional[Decimal]] = mapped_column(MONEY, nullable=True)
    upi_amount: Mapped[Optional[Decimal]] = mapped_column(MONEY, nullable=True)
    closed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    openings: Mapped[list["OpeningStock"]] = relationship(back_populates="journal", cascade="all, delete-orphan")
    closings: Mapped[list["ClosingStock"]] = relationship(back_populates="journal", cascade="all, delete-orphan")


class OpeningStock(Base):
    __tablename__ = "opening_stock"
    __table_args__ = (UniqueConstraint("journal_id", "fish_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id", ondelete="CASCADE"))
    fish_id: Mapped[int] = mapped_column(ForeignKey("fish.id"))
    quantity: Mapped[Optional[Decimal]] = mapped_column(QTY, nullable=True)  # owner-confirmed
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    journal: Mapped[Journal] = relationship(back_populates="openings")
    fish: Mapped[Fish] = relationship()


class ClosingStock(Base):
    __tablename__ = "closing_stock"
    __table_args__ = (UniqueConstraint("journal_id", "fish_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id", ondelete="CASCADE"))
    fish_id: Mapped[int] = mapped_column(ForeignKey("fish.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    journal: Mapped[Journal] = relationship(back_populates="closings")
    fish: Mapped[Fish] = relationship()


class Purchase(Base):
    __tablename__ = "purchase"
    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"))
    fish_id: Mapped[int] = mapped_column(ForeignKey("fish.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    rate: Mapped[Decimal] = mapped_column(MONEY)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    paid_now: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    payment_mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    due_created: Mapped[Decimal] = mapped_column(MONEY)
    journal: Mapped[Journal] = relationship()
    supplier: Mapped[Supplier] = relationship()
    fish: Mapped[Fish] = relationship()
    payment: Mapped[Optional["SupplierPayment"]] = relationship(
        back_populates="purchase", uselist=False, cascade="all, delete-orphan"
    )


class SupplierPayment(Base):
    """Immediate (purchase_id set) and later (purchase_id NULL) payments to suppliers."""

    __tablename__ = "supplier_payment"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"))
    journal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("journal.id"), nullable=True)
    purchase_id: Mapped[Optional[int]] = mapped_column(ForeignKey("purchase.id", ondelete="CASCADE"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    payment_mode: Mapped[str] = mapped_column(String(10))
    payment_date: Mapped[dt.date] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    supplier: Mapped[Supplier] = relationship()
    purchase: Mapped[Optional[Purchase]] = relationship(back_populates="payment")


class HotelSale(Base):
    __tablename__ = "hotel_sale"
    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journal.id"))
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotel.id"))
    fish_id: Mapped[int] = mapped_column(ForeignKey("fish.id"))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    rate: Mapped[Decimal] = mapped_column(MONEY)  # actual rate used at time of sale
    rate_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    journal: Mapped[Journal] = relationship()
    hotel: Mapped[Hotel] = relationship()
    fish: Mapped[Fish] = relationship()


class HotelPayment(Base):
    __tablename__ = "hotel_payment"
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotel.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    payment_mode: Mapped[str] = mapped_column(String(10))
    payment_date: Mapped[dt.date] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    hotel: Mapped[Hotel] = relationship()


class HotelOpeningBalance(Base):
    """Balance owed by a hotel before the app was used. Separate entry, not a sale."""

    __tablename__ = "hotel_opening_balance"
    id: Mapped[int] = mapped_column(primary_key=True)
    hotel_id: Mapped[int] = mapped_column(ForeignKey("hotel.id"), unique=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    balance_date: Mapped[dt.date] = mapped_column(Date)


class SupplierOpeningBalance(Base):
    """Balance owed to a supplier before the app was used. Separate entry, not a purchase."""

    __tablename__ = "supplier_opening_balance"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"), unique=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    balance_date: Mapped[dt.date] = mapped_column(Date)


class OwnerAccount(Base):
    """The single shop owner login."""

    __tablename__ = "owner_account"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    token_version: Mapped[int] = mapped_column(default=1)  # bump to invalidate all access tokens


class RefreshToken(Base):
    __tablename__ = "refresh_token"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owner_account.id", ondelete="CASCADE"))
    jti: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
