"""All business logic. Routers stay thin."""
import calendar
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import models as m
from . import schemas as s

ZERO = Decimal("0")


# ---------- numeric helpers ----------
def D(x) -> Decimal:
    return Decimal(str(x)) if x is not None else ZERO


def money(x) -> Decimal:
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def qty(x) -> Decimal:
    return D(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# ---------- errors ----------
def not_found(label: str, id_) -> HTTPException:
    return HTTPException(404, f"{label} {id_} not found")


def conflict(msg) -> HTTPException:
    return HTTPException(409, msg)


def invalid(msg) -> HTTPException:
    return HTTPException(422, msg)


def get_or_404(db: Session, model, id_: int, label: str):
    obj = db.get(model, id_)
    if obj is None:
        raise not_found(label, id_)
    return obj


def check_unique_name(db: Session, model, name: str, exclude_id: Optional[int] = None):
    q = select(model).where(func.lower(model.name) == name.lower())
    if exclude_id is not None:
        q = q.where(model.id != exclude_id)
    if db.scalar(q) is not None:
        raise conflict(f"'{name}' already exists")


# ---------- journal state ----------
def require_open(journal: m.Journal):
    if journal.status != "open":
        raise conflict("Journal is closed and read-only. Reopen it (with confirmation) to make corrections.")


def ensure_opening_rows(db: Session, journal: m.Journal):
    """Every active fish gets an (unconfirmed) opening row in an open journal."""
    existing = {o.fish_id for o in db.scalars(select(m.OpeningStock).where(m.OpeningStock.journal_id == journal.id))}
    for f in db.scalars(select(m.Fish).where(m.Fish.is_active.is_(True))):
        if f.id not in existing:
            db.add(m.OpeningStock(journal_id=journal.id, fish_id=f.id, quantity=None, confirmed=False))
    db.flush()
    db.expire(journal, ["openings"])


def opening_row(db: Session, journal: m.Journal, fish_id: int) -> m.OpeningStock:
    row = db.scalar(
        select(m.OpeningStock).where(m.OpeningStock.journal_id == journal.id, m.OpeningStock.fish_id == fish_id)
    )
    if row is None:
        row = m.OpeningStock(journal_id=journal.id, fish_id=fish_id, quantity=None, confirmed=False)
        db.add(row)
        db.flush()
        db.expire(journal, ["openings"])
    return row


def previous_closing_map(db: Session, journal: m.Journal) -> Optional[dict]:
    """Closing stock of the latest earlier journal. None = no suggestion available
    (first journal, or the previous journal is not closed / is reopened)."""
    prev = db.scalars(
        select(m.Journal).where(m.Journal.business_date < journal.business_date).order_by(m.Journal.business_date.desc())
    ).first()
    if prev is None or prev.status != "closed":
        return None
    return {c.fish_id: D(c.quantity) for c in prev.closings}


def create_journal(db: Session, business_date: dt.date) -> m.Journal:
    if db.scalar(select(m.Journal).where(m.Journal.business_date == business_date)):
        raise conflict(f"A journal already exists for {business_date}")
    j = m.Journal(business_date=business_date, status="open")
    db.add(j)
    db.flush()
    ensure_opening_rows(db, j)
    return j


def set_opening_stock(db: Session, journal: m.Journal, items: list[s.OpeningItem]):
    require_open(journal)
    ensure_opening_rows(db, journal)
    prev = previous_closing_map(db, journal)
    seen = set()
    for it in items:
        if it.fish_id in seen:
            raise invalid(f"Duplicate fish {it.fish_id} in request")
        seen.add(it.fish_id)
        get_or_404(db, m.Fish, it.fish_id, "Fish")
        q = it.quantity
        if q is None:
            if prev is None:
                raise invalid(f"No suggested opening quantity for fish {it.fish_id}; enter the quantity manually")
            q = prev.get(it.fish_id, ZERO)
        row = opening_row(db, journal, it.fish_id)
        row.quantity = qty(q)
        row.confirmed = True
    db.flush()


# ---------- stock reconciliation ----------
def _sum_by_fish(db: Session, model, journal_id: int) -> dict:
    rows = db.execute(
        select(model.fish_id, func.sum(model.quantity)).where(model.journal_id == journal_id).group_by(model.fish_id)
    ).all()
    return {fid: qty(v) for fid, v in rows}


def _total(rows: list, key: str):
    vals = [r[key] for r in rows]
    if not vals:
        return qty(0)
    if any(v is None for v in vals):
        return None
    return qty(sum(vals, ZERO))


def build_stock(db: Session, journal: m.Journal, closing_override: Optional[dict] = None) -> dict:
    prev = previous_closing_map(db, journal)
    openings = db.scalars(
        select(m.OpeningStock).join(m.Fish).where(m.OpeningStock.journal_id == journal.id).order_by(m.Fish.name)
    ).all()
    purchased = _sum_by_fish(db, m.Purchase, journal.id)
    sold = _sum_by_fish(db, m.HotelSale, journal.id)
    if closing_override is not None:
        closing = {k: qty(v) for k, v in closing_override.items()}
    elif journal.status == "closed":
        closing = {c.fish_id: qty(c.quantity) for c in journal.closings}
    else:
        closing = None

    rows = []
    for o in openings:
        fid = o.fish_id
        suggested = None if prev is None else qty(prev.get(fid, ZERO))
        opening = qty(o.quantity) if (o.confirmed and o.quantity is not None) else None
        p = purchased.get(fid, qty(0))
        h = sold.get(fid, qty(0))
        available = qty(opening + p) if opening is not None else None
        remaining = closing.get(fid) if closing is not None else None
        normal = qty(available - h - remaining) if (available is not None and remaining is not None) else None
        if remaining is not None:
            current = remaining
        elif available is not None:
            current = qty(available - h)
        else:
            current = None
        rows.append(
            dict(
                fish_id=fid, fish_name=o.fish.name, previous_closing=suggested, suggested_opening=suggested,
                opening_quantity=opening, opening_confirmed=bool(o.confirmed), purchased=p, available=available,
                hotel_sold=h, normal_customer=normal, remaining=remaining, current_stock=current,
            )
        )
    keys = ["previous_closing", "opening_quantity", "purchased", "available", "hotel_sold", "normal_customer", "remaining"]
    return {"rows": rows, "totals": {k: _total(rows, k) for k in keys}}


# ---------- purchases ----------
def purchase_out(p: m.Purchase) -> dict:
    return dict(
        id=p.id, journal_id=p.journal_id, business_date=p.journal.business_date, supplier_id=p.supplier_id,
        supplier_name=p.supplier.name, fish_id=p.fish_id, fish_name=p.fish.name, quantity=qty(p.quantity),
        rate=money(p.rate), amount=money(p.amount), paid_now=money(p.paid_now), payment_mode=p.payment_mode,
        due_created=money(p.due_created),
    )


def purchase_list(purchases: list[m.Purchase]) -> dict:
    entries = [purchase_out(p) for p in purchases]
    return {
        "entries": entries,
        "totals": dict(
            total_quantity=qty(sum((e["quantity"] for e in entries), ZERO)),
            total_amount=money(sum((e["amount"] for e in entries), ZERO)),
            total_paid_now=money(sum((e["paid_now"] for e in entries), ZERO)),
            total_due_created=money(sum((e["due_created"] for e in entries), ZERO)),
        ),
    }


def _apply_purchase(db: Session, p: m.Purchase, journal: m.Journal, data: s.PurchaseUpdate):
    supplier = get_or_404(db, m.Supplier, data.supplier_id, "Supplier")
    fish = get_or_404(db, m.Fish, data.fish_id, "Fish")
    if not fish.is_active and p.fish_id != fish.id:
        raise invalid("Fish is inactive")
    if not supplier.is_active and p.supplier_id != supplier.id:
        raise invalid("Supplier is inactive")
    amount = money(data.quantity * data.rate)
    paid = money(data.paid_now)
    if paid > amount:
        raise invalid(f"Paid now ({paid}) cannot exceed purchase amount ({amount})")
    if paid > 0 and data.payment_mode is None:
        raise invalid("payment_mode (cash or upi) is required when paid_now is greater than 0")
    p.journal_id = journal.id
    p.supplier_id, p.fish_id = supplier.id, fish.id
    p.quantity, p.rate, p.amount = qty(data.quantity), money(data.rate), amount
    p.paid_now = paid
    p.payment_mode = data.payment_mode.value if paid > 0 else None
    p.due_created = money(amount - paid)
    db.add(p)
    db.flush()
    opening_row(db, journal, fish.id)
    # keep the immediate payment in the supplier payment ledger in sync (no double counting)
    if paid > 0:
        if p.payment is None:
            p.payment = m.SupplierPayment(purchase_id=p.id)
        p.payment.supplier_id = supplier.id
        p.payment.journal_id = journal.id
        p.payment.amount = paid
        p.payment.payment_mode = data.payment_mode.value
        p.payment.payment_date = journal.business_date
    elif p.payment is not None:
        p.payment = None
    db.flush()


def create_purchase(db: Session, data: s.PurchaseIn) -> m.Purchase:
    journal = get_or_404(db, m.Journal, data.journal_id, "Journal")
    require_open(journal)
    p = m.Purchase()
    _apply_purchase(db, p, journal, data)
    assert_non_negative(db, "supplier", p.supplier_id)
    return p


def update_purchase(db: Session, p: m.Purchase, data: s.PurchaseUpdate):
    require_open(p.journal)
    old = p.supplier_id
    _apply_purchase(db, p, p.journal, data)
    assert_non_negative(db, "supplier", p.supplier_id)
    if old != p.supplier_id:
        assert_non_negative(db, "supplier", old)


def delete_purchase(db: Session, p: m.Purchase):
    require_open(p.journal)
    sid = p.supplier_id
    db.delete(p)  # cascades to its immediate payment
    db.flush()
    assert_non_negative(db, "supplier", sid)


# ---------- hotel sales ----------
def hotel_sale_out(x: m.HotelSale) -> dict:
    return dict(
        id=x.id, journal_id=x.journal_id, business_date=x.journal.business_date, hotel_id=x.hotel_id,
        hotel_name=x.hotel.name, fish_id=x.fish_id, fish_name=x.fish.name, quantity=qty(x.quantity),
        rate=money(x.rate), rate_overridden=bool(x.rate_overridden), amount=money(x.amount),
    )


def hotel_sale_list(sales: list[m.HotelSale]) -> dict:
    entries = [hotel_sale_out(x) for x in sales]
    return {
        "entries": entries,
        "total_quantity": qty(sum((e["quantity"] for e in entries), ZERO)),
        "total_amount": money(sum((e["amount"] for e in entries), ZERO)),
    }


def default_rate(db: Session, hotel_id: int, fish_id: int) -> Optional[Decimal]:
    r = db.scalar(select(m.HotelRate).where(m.HotelRate.hotel_id == hotel_id, m.HotelRate.fish_id == fish_id))
    return money(r.rate) if r else None


def _apply_sale(db: Session, x: m.HotelSale, journal: m.Journal, data: s.HotelSaleUpdate):
    hotel = get_or_404(db, m.Hotel, data.hotel_id, "Hotel")
    fish = get_or_404(db, m.Fish, data.fish_id, "Fish")
    if not fish.is_active and x.fish_id != fish.id:
        raise invalid("Fish is inactive")
    if not hotel.is_active and x.hotel_id != hotel.id:
        raise invalid("Hotel is inactive")
    agreed = default_rate(db, hotel.id, fish.id)
    if data.rate is not None:
        rate = money(data.rate)
    elif agreed is not None:
        rate = agreed
    else:
        raise invalid(f"No agreed rate for {hotel.name} / {fish.name}. Set the hotel rate or send a rate for this sale")
    x.journal_id, x.hotel_id, x.fish_id = journal.id, hotel.id, fish.id
    x.quantity, x.rate = qty(data.quantity), rate
    x.rate_overridden = agreed is None or rate != agreed
    x.amount = money(x.quantity * rate)
    db.add(x)
    db.flush()
    opening_row(db, journal, fish.id)


def create_hotel_sale(db: Session, data: s.HotelSaleIn) -> m.HotelSale:
    journal = get_or_404(db, m.Journal, data.journal_id, "Journal")
    require_open(journal)
    x = m.HotelSale()
    _apply_sale(db, x, journal, data)
    return x


def update_hotel_sale(db: Session, x: m.HotelSale, data: s.HotelSaleUpdate):
    require_open(x.journal)
    old = x.hotel_id
    _apply_sale(db, x, x.journal, data)
    assert_non_negative(db, "hotel", x.hotel_id)
    if old != x.hotel_id:
        assert_non_negative(db, "hotel", old)


# ---------- payments ----------
def supplier_payment_out(p: m.SupplierPayment) -> dict:
    return dict(
        id=p.id, supplier_id=p.supplier_id, supplier_name=p.supplier.name, amount=money(p.amount),
        payment_mode=p.payment_mode, payment_date=p.payment_date, purchase_id=p.purchase_id,
        is_immediate=p.purchase_id is not None,
    )


def hotel_payment_out(p: m.HotelPayment) -> dict:
    return dict(
        id=p.id, hotel_id=p.hotel_id, hotel_name=p.hotel.name, amount=money(p.amount),
        payment_mode=p.payment_mode, payment_date=p.payment_date,
    )


# ---------- balances / ledgers ----------
def _date_filters(q, col, gte, lte):
    if gte is not None:
        q = q.where(col >= gte)
    if lte is not None:
        q = q.where(col <= lte)
    return q


def _opening_sum(db: Session, model, col, pid: int, gte=None, lte=None) -> Decimal:
    q = select(func.sum(model.amount)).where(col == pid)
    q = _date_filters(q, model.balance_date, gte, lte)
    return money(db.scalar(q))


def supplier_opening(db: Session, sid: int, gte=None, lte=None) -> Decimal:
    return _opening_sum(db, m.SupplierOpeningBalance, m.SupplierOpeningBalance.supplier_id, sid, gte, lte)


def hotel_opening(db: Session, hid: int, gte=None, lte=None) -> Decimal:
    return _opening_sum(db, m.HotelOpeningBalance, m.HotelOpeningBalance.hotel_id, hid, gte, lte)


def supplier_sums(db: Session, sid: int, gte=None, lte=None):
    """(purchase amounts, payments made) in the date window. Opening balance not included."""
    q1 = select(func.sum(m.Purchase.amount)).join(m.Journal, m.Journal.id == m.Purchase.journal_id).where(
        m.Purchase.supplier_id == sid
    )
    q2 = select(func.sum(m.SupplierPayment.amount)).where(m.SupplierPayment.supplier_id == sid)
    q1 = _date_filters(q1, m.Journal.business_date, gte, lte)
    q2 = _date_filters(q2, m.SupplierPayment.payment_date, gte, lte)
    return money(db.scalar(q1)), money(db.scalar(q2))


def hotel_sums(db: Session, hid: int, gte=None, lte=None):
    """(sale amounts, payments received) in the date window. Opening balance not included."""
    q1 = select(func.sum(m.HotelSale.amount)).join(m.Journal, m.Journal.id == m.HotelSale.journal_id).where(
        m.HotelSale.hotel_id == hid
    )
    q2 = select(func.sum(m.HotelPayment.amount)).where(m.HotelPayment.hotel_id == hid)
    q1 = _date_filters(q1, m.Journal.business_date, gte, lte)
    q2 = _date_filters(q2, m.HotelPayment.payment_date, gte, lte)
    return money(db.scalar(q1)), money(db.scalar(q2))


def supplier_balance(db: Session, sid: int, lte=None) -> Decimal:
    a, b = supplier_sums(db, sid, lte=lte)
    return money(supplier_opening(db, sid, lte=lte) + a - b)


def hotel_balance(db: Session, hid: int, lte=None) -> Decimal:
    a, b = hotel_sums(db, hid, lte=lte)
    return money(hotel_opening(db, hid, lte=lte) + a - b)


# ---------- opening balances ----------
def _ob_model(kind: str):
    return (m.HotelOpeningBalance, m.HotelOpeningBalance.hotel_id) if kind == "hotel" else (
        m.SupplierOpeningBalance, m.SupplierOpeningBalance.supplier_id)


def get_opening_balance(db: Session, kind: str, party_id: int) -> dict:
    model, col = _ob_model(kind)
    row = db.scalar(select(model).where(col == party_id))
    if row is None:
        return dict(amount=money(0), balance_date=None)
    return dict(amount=money(row.amount), balance_date=row.balance_date)


def set_opening_balance(db: Session, kind: str, party, amount, balance_date: dt.date) -> dict:
    model, col = _ob_model(kind)
    row = db.scalar(select(model).where(col == party.id))
    amount = money(amount)
    if amount == 0:
        if row is not None:
            db.delete(row)  # zero opening balance = no entry
    elif row is not None:
        row.amount, row.balance_date = amount, balance_date
    else:
        db.add(model(**{f"{kind}_id": party.id}, amount=amount, balance_date=balance_date))
    db.flush()
    assert_non_negative(db, kind, party.id)
    return get_opening_balance(db, kind, party.id)


def assert_non_negative(db: Session, kind: str, party_id: int):
    """No advance payments: the running balance may never drop below zero on any date."""
    if kind == "hotel":
        party = db.get(m.Hotel, party_id)
        led = hotel_ledger(db, party)
    else:
        party = db.get(m.Supplier, party_id)
        led = supplier_ledger(db, party)
    for e in led["entries"]:
        if e["running_balance"] < 0:
            raise invalid(
                f"This change would make the balance of {party.name} negative ({e['running_balance']}) on "
                f"{e['date']}. Payments cannot exceed the outstanding balance."
            )


def create_supplier_payment(db: Session, data: s.SupplierPaymentIn) -> m.SupplierPayment:
    sup = get_or_404(db, m.Supplier, data.supplier_id, "Supplier")
    outstanding = supplier_balance(db, sup.id, lte=data.payment_date)
    if money(data.amount) > outstanding:
        raise invalid(f"Payment {money(data.amount)} exceeds outstanding balance {outstanding} of {sup.name} as of {data.payment_date}")
    p = m.SupplierPayment(supplier_id=sup.id, amount=money(data.amount), payment_mode=data.payment_mode.value,
                          payment_date=data.payment_date, purchase_id=None, journal_id=None)
    db.add(p)
    db.flush()
    assert_non_negative(db, "supplier", sup.id)
    return p


def update_supplier_payment(db: Session, p: m.SupplierPayment, data: s.SupplierPaymentIn):
    sup = get_or_404(db, m.Supplier, data.supplier_id, "Supplier")
    old = p.supplier_id
    p.supplier_id, p.amount = sup.id, money(data.amount)
    p.payment_mode, p.payment_date = data.payment_mode.value, data.payment_date
    db.flush()
    assert_non_negative(db, "supplier", sup.id)
    if old != sup.id:
        assert_non_negative(db, "supplier", old)


def create_hotel_payment(db: Session, data: s.HotelPaymentIn) -> m.HotelPayment:
    h = get_or_404(db, m.Hotel, data.hotel_id, "Hotel")
    outstanding = hotel_balance(db, h.id, lte=data.payment_date)
    if money(data.amount) > outstanding:
        raise invalid(f"Payment {money(data.amount)} exceeds outstanding balance {outstanding} of {h.name} as of {data.payment_date}")
    p = m.HotelPayment(hotel_id=h.id, amount=money(data.amount), payment_mode=data.payment_mode.value,
                       payment_date=data.payment_date)
    db.add(p)
    db.flush()
    assert_non_negative(db, "hotel", h.id)
    return p


def update_hotel_payment(db: Session, p: m.HotelPayment, data: s.HotelPaymentIn):
    h = get_or_404(db, m.Hotel, data.hotel_id, "Hotel")
    old = p.hotel_id
    p.hotel_id, p.amount = h.id, money(data.amount)
    p.payment_mode, p.payment_date = data.payment_mode.value, data.payment_date
    db.flush()
    assert_non_negative(db, "hotel", h.id)
    if old != h.id:
        assert_non_negative(db, "hotel", old)


def delete_hotel_sale(db: Session, x: m.HotelSale):
    require_open(x.journal)
    hid = x.hotel_id
    db.delete(x)
    db.flush()
    assert_non_negative(db, "hotel", hid)


def _finish_ledger(party, raw: list, from_date, to_date) -> dict:
    raw.sort(key=lambda t: (t[0]["date"], t[1], t[0]["reference_id"]))
    entries = [t[0] for t in raw]
    previous = ZERO
    if from_date is not None:
        previous = sum((e["balance_change"] for e in entries if e["date"] < from_date), ZERO)
    window = [
        e for e in entries
        if (from_date is None or e["date"] >= from_date) and (to_date is None or e["date"] <= to_date)
    ]
    running = money(previous)
    for e in window:
        running = money(running + e["balance_change"])
        e["running_balance"] = running
    return dict(
        id=party.id, name=party.name, from_date=from_date, to_date=to_date,
        previous_balance=money(previous), entries=window, closing_balance=running,
    )


def supplier_ledger(db: Session, supplier: m.Supplier, from_date=None, to_date=None) -> dict:
    raw = []
    for p in db.scalars(select(m.Purchase).where(m.Purchase.supplier_id == supplier.id)):
        raw.append((dict(
            date=p.journal.business_date, entry_type="purchase", reference_id=p.id, fish_id=p.fish_id,
            fish_name=p.fish.name, quantity=qty(p.quantity), rate=money(p.rate), amount=money(p.amount),
            paid_now=money(p.paid_now), due_created=money(p.due_created), payment_mode=p.payment_mode,
            balance_change=money(p.amount),
        ), 0))
    for pay in db.scalars(select(m.SupplierPayment).where(m.SupplierPayment.supplier_id == supplier.id)):
        immediate = pay.purchase_id is not None
        raw.append((dict(
            date=pay.payment_date, entry_type="immediate_payment" if immediate else "payment",
            reference_id=pay.id, amount=money(pay.amount), payment_mode=pay.payment_mode,
            balance_change=-money(pay.amount),
        ), 1 if immediate else 2))
    ob = db.scalar(select(m.SupplierOpeningBalance).where(m.SupplierOpeningBalance.supplier_id == supplier.id))
    if ob:
        raw.append((dict(date=ob.balance_date, entry_type="opening_balance", reference_id=ob.id,
                         amount=money(ob.amount), balance_change=money(ob.amount)), -1))
    return _finish_ledger(supplier, raw, from_date, to_date)


def hotel_ledger(db: Session, hotel: m.Hotel, from_date=None, to_date=None) -> dict:
    raw = []
    for x in db.scalars(select(m.HotelSale).where(m.HotelSale.hotel_id == hotel.id)):
        raw.append((dict(
            date=x.journal.business_date, entry_type="sale", reference_id=x.id, fish_id=x.fish_id,
            fish_name=x.fish.name, quantity=qty(x.quantity), rate=money(x.rate), amount=money(x.amount),
            balance_change=money(x.amount),
        ), 0))
    for pay in db.scalars(select(m.HotelPayment).where(m.HotelPayment.hotel_id == hotel.id)):
        raw.append((dict(
            date=pay.payment_date, entry_type="payment", reference_id=pay.id, amount=money(pay.amount),
            payment_mode=pay.payment_mode, balance_change=-money(pay.amount),
        ), 1))
    ob = db.scalar(select(m.HotelOpeningBalance).where(m.HotelOpeningBalance.hotel_id == hotel.id))
    if ob:
        raw.append((dict(date=ob.balance_date, entry_type="opening_balance", reference_id=ob.id,
                         amount=money(ob.amount), balance_change=money(ob.amount)), -1))
    return _finish_ledger(hotel, raw, from_date, to_date)


def hotel_monthly_summary(db: Session, hotel: m.Hotel, year: int, month: int) -> dict:
    if not 1 <= month <= 12:
        raise invalid("month must be 1-12")
    first = dt.date(year, month, 1)
    last = dt.date(year, month, calendar.monthrange(year, month)[1])
    # an opening balance dated inside the month is brought forward as the month's opening outstanding
    opening = money(hotel_balance(db, hotel.id, lte=first - dt.timedelta(days=1)) + hotel_opening(db, hotel.id, gte=first, lte=last))
    sales, paid = hotel_sums(db, hotel.id, gte=first, lte=last)
    return dict(
        hotel_id=hotel.id, hotel_name=hotel.name, year=year, month=month, opening_outstanding=opening,
        fish_taken=sales, payments_received=paid, closing_outstanding=money(opening + sales - paid),
    )


# ---------- journal detail ----------
def journal_detail(db: Session, journal: m.Journal) -> dict:
    if journal.status == "open":
        ensure_opening_rows(db, journal)
    d = journal.business_date
    stock = build_stock(db, journal)
    purchases = db.scalars(select(m.Purchase).where(m.Purchase.journal_id == journal.id).order_by(m.Purchase.id)).all()
    sales = db.scalars(select(m.HotelSale).where(m.HotelSale.journal_id == journal.id).order_by(m.HotelSale.id)).all()
    sale_list = hotel_sale_list(sales)
    purchase_data = purchase_list(purchases)
    normal = [
        dict(fish_id=r["fish_id"], fish_name=r["fish_name"], quantity=r["normal_customer"])
        for r in stock["rows"] if r["normal_customer"] is not None
    ]
    money_rec = None
    if journal.status == "closed":
        cash, upi = money(journal.cash_amount), money(journal.upi_amount)
        money_rec = dict(cash_amount=cash, upi_amount=upi, total=money(cash + upi))

    hotel_pays = db.scalars(select(m.HotelPayment).where(m.HotelPayment.payment_date == d).order_by(m.HotelPayment.id)).all()
    later = db.scalars(
        select(m.SupplierPayment)
        .where(m.SupplierPayment.payment_date == d, m.SupplierPayment.purchase_id.is_(None))
        .order_by(m.SupplierPayment.id)
    ).all()
    hotel_bal = []
    for h in db.scalars(select(m.Hotel).order_by(m.Hotel.name)):
        a, b = hotel_sums(db, h.id, lte=d)
        o = hotel_opening(db, h.id, lte=d)
        if a != 0 or b != 0 or o != 0:
            hotel_bal.append(dict(id=h.id, name=h.name, outstanding=money(o + a - b)))
    sup_bal = []
    for sp in db.scalars(select(m.Supplier).order_by(m.Supplier.name)):
        a, b = supplier_sums(db, sp.id, lte=d)
        o = supplier_opening(db, sp.id, lte=d)
        if a != 0 or b != 0 or o != 0:
            sup_bal.append(dict(id=sp.id, name=sp.name, outstanding=money(o + a - b)))
    return dict(
        id=journal.id, business_date=d, status=journal.status, closed_at=journal.closed_at, stock=stock,
        purchases=purchase_data,
        sales=dict(
            hotel_sales=sale_list["entries"], total_hotel_quantity=sale_list["total_quantity"],
            total_hotel_amount=sale_list["total_amount"], normal_customer=normal,
            total_normal_customer_quantity=stock["totals"]["normal_customer"],
        ),
        money=money_rec,
        hotel_info=dict(
            sales_total=sale_list["total_amount"],
            payments_received=[hotel_payment_out(p) for p in hotel_pays], outstanding_balances=hotel_bal,
        ),
        supplier_info=dict(
            paid_immediately_total=purchase_data["totals"]["total_paid_now"],
            dues_created_total=purchase_data["totals"]["total_due_created"],
            later_payments=[supplier_payment_out(p) for p in later], outstanding_balances=sup_bal,
        ),
    )


# ---------- closing / reopening ----------
def validate_close(db: Session, journal: m.Journal, body: s.ClosingIn):
    ensure_opening_rows(db, journal)
    problems = []
    openings = db.scalars(select(m.OpeningStock).where(m.OpeningStock.journal_id == journal.id)).all()
    fish_ids = {o.fish_id for o in openings}
    override, seen = {}, set()
    for item in body.stocks:
        if item.fish_id in seen:
            problems.append(f"Remaining quantity sent twice for fish {item.fish_id}")
        seen.add(item.fish_id)
        if item.fish_id not in fish_ids:
            problems.append(f"Fish {item.fish_id} is not part of this journal")
        override[item.fish_id] = item.quantity
    for o in openings:
        if not o.confirmed:
            problems.append(f"Opening quantity not confirmed for {o.fish.name}")
        if o.fish_id not in override:
            problems.append(f"Remaining quantity missing for {o.fish.name}")
    stock = build_stock(db, journal, override)
    for r in stock["rows"]:
        if r["normal_customer"] is not None and r["normal_customer"] < 0:
            problems.append(
                f"Remaining quantity for {r['fish_name']} is more than available stock minus hotel sales "
                f"(normal customer quantity would be {r['normal_customer']})"
            )
    return problems, stock, override


def close_preview(db: Session, journal: m.Journal, body: s.ClosingIn) -> dict:
    require_open(journal)
    problems, stock, _ = validate_close(db, journal, body)
    cash, upi = money(body.cash_amount), money(body.upi_amount)
    return dict(
        can_close=not problems, problems=problems, stock=stock,
        sales_normal_customer=[
            dict(fish_id=r["fish_id"], fish_name=r["fish_name"], quantity=r["normal_customer"])
            for r in stock["rows"] if r["normal_customer"] is not None
        ],
        money=dict(cash_amount=cash, upi_amount=upi, total=money(cash + upi)),
    )


def close_journal(db: Session, journal: m.Journal, body: s.ClosingIn):
    require_open(journal)
    problems, _, override = validate_close(db, journal, body)
    if problems:
        raise HTTPException(422, detail=problems)
    db.execute(delete(m.ClosingStock).where(m.ClosingStock.journal_id == journal.id))
    db.expire(journal, ["closings"])
    for fid, q in override.items():
        db.add(m.ClosingStock(journal_id=journal.id, fish_id=fid, quantity=qty(q)))
    journal.cash_amount = money(body.cash_amount)
    journal.upi_amount = money(body.upi_amount)
    journal.status = "closed"
    journal.closed_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    db.flush()
    db.expire(journal, ["closings"])


REOPEN_WARNING = (
    "Reopening a closed journal lets you change its records. After you close it again, later stock "
    "suggestions and outstanding balances are recalculated. Send {\"confirm\": true} to continue."
)


def reopen_journal(db: Session, journal: m.Journal, confirm: bool):
    if journal.status != "closed":
        raise conflict("Journal is already open")
    if not confirm:
        raise HTTPException(409, detail={"requires_confirmation": True, "warning": REOPEN_WARNING})
    journal.status = "open"
    journal.closed_at = None
    db.flush()


# ---------- dashboard ----------
def dashboard(db: Session, d: dt.date) -> dict:
    j = db.scalar(select(m.Journal).where(m.Journal.business_date == d))
    journal, rows = None, []
    if j:
        if j.status == "open":
            ensure_opening_rows(db, j)
        journal = dict(id=j.id, business_date=j.business_date, status=j.status)
        rows = build_stock(db, j)["rows"]
    hotels = [dict(id=h.id, name=h.name, outstanding=hotel_balance(db, h.id)) for h in db.scalars(select(m.Hotel).order_by(m.Hotel.name))]
    sups = [dict(id=x.id, name=x.name, outstanding=supplier_balance(db, x.id)) for x in db.scalars(select(m.Supplier).order_by(m.Supplier.name))]
    # hotel and supplier totals are kept separate on purpose: no combined net position
    return dict(
        business_date=d, journal=journal, stock_overview=rows,
        hotel_outstanding_total=money(sum((h["outstanding"] for h in hotels), ZERO)),
        supplier_outstanding_total=money(sum((x["outstanding"] for x in sups), ZERO)),
        hotels=hotels, suppliers=sups,
    )
