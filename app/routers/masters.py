from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from .. import services as svc
from ..database import get_db

router = APIRouter(tags=["masters"])


# ---------- fish ----------
@router.post("/fish", response_model=s.FishOut, status_code=201)
def create_fish(body: s.FishIn, db: Session = Depends(get_db)):
    svc.check_unique_name(db, m.Fish, body.name)
    f = m.Fish(name=body.name, is_active=True)
    db.add(f)
    db.commit()
    return f


@router.get("/fish", response_model=list[s.FishOut])
def list_fish(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = select(m.Fish).order_by(m.Fish.name)
    if not include_inactive:
        q = q.where(m.Fish.is_active.is_(True))
    return db.scalars(q).all()


@router.get("/fish/{fish_id}", response_model=s.FishOut)
def get_fish(fish_id: int, db: Session = Depends(get_db)):
    return svc.get_or_404(db, m.Fish, fish_id, "Fish")


@router.patch("/fish/{fish_id}", response_model=s.FishOut)
def patch_fish(fish_id: int, body: s.FishPatch, db: Session = Depends(get_db)):
    f = svc.get_or_404(db, m.Fish, fish_id, "Fish")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise svc.invalid("name must not be empty")
        svc.check_unique_name(db, m.Fish, name, fish_id)
        f.name = name
    if body.is_active is not None:
        f.is_active = body.is_active
    db.commit()
    return f


# ---------- suppliers ----------
def supplier_out(db: Session, x: m.Supplier) -> dict:
    ob = svc.get_opening_balance(db, "supplier", x.id)
    return dict(id=x.id, name=x.name, phone=x.phone, is_active=x.is_active,
                opening_balance=ob["amount"], opening_balance_date=ob["balance_date"])


@router.post("/suppliers", response_model=s.SupplierOut, status_code=201)
def create_supplier(body: s.PartyIn, db: Session = Depends(get_db)):
    svc.check_unique_name(db, m.Supplier, body.name)
    x = m.Supplier(name=body.name, phone=body.phone, is_active=True)
    db.add(x)
    db.flush()
    if body.opening_balance > 0:
        svc.set_opening_balance(db, "supplier", x, body.opening_balance, body.opening_balance_date)
    db.commit()
    return supplier_out(db, x)


@router.get("/suppliers", response_model=list[s.SupplierOut])
def list_suppliers(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = select(m.Supplier).order_by(m.Supplier.name)
    if not include_inactive:
        q = q.where(m.Supplier.is_active.is_(True))
    return [supplier_out(db, x) for x in db.scalars(q)]


@router.get("/suppliers/{supplier_id}", response_model=s.SupplierOut)
def get_supplier(supplier_id: int, db: Session = Depends(get_db)):
    return supplier_out(db, svc.get_or_404(db, m.Supplier, supplier_id, "Supplier"))


@router.patch("/suppliers/{supplier_id}", response_model=s.SupplierOut)
def patch_supplier(supplier_id: int, body: s.PartyPatch, db: Session = Depends(get_db)):
    x = svc.get_or_404(db, m.Supplier, supplier_id, "Supplier")
    _patch_party(db, m.Supplier, x, body)
    db.commit()
    return supplier_out(db, x)


@router.get("/suppliers/{supplier_id}/opening-balance", response_model=s.OpeningBalanceOut)
def get_supplier_opening(supplier_id: int, db: Session = Depends(get_db)):
    svc.get_or_404(db, m.Supplier, supplier_id, "Supplier")
    return svc.get_opening_balance(db, "supplier", supplier_id)


@router.put("/suppliers/{supplier_id}/opening-balance", response_model=s.OpeningBalanceOut)
def put_supplier_opening(supplier_id: int, body: s.OpeningBalanceIn, db: Session = Depends(get_db)):
    x = svc.get_or_404(db, m.Supplier, supplier_id, "Supplier")
    out = svc.set_opening_balance(db, "supplier", x, body.amount, body.balance_date)
    db.commit()
    return out


# ---------- hotels ----------
def hotel_out(db: Session, h: m.Hotel) -> dict:
    rates = sorted(h.rates, key=lambda r: r.fish.name)
    ob = svc.get_opening_balance(db, "hotel", h.id)
    return dict(
        id=h.id, name=h.name, phone=h.phone, is_active=h.is_active,
        opening_balance=ob["amount"], opening_balance_date=ob["balance_date"],
        rates=[dict(fish_id=r.fish_id, fish_name=r.fish.name, rate=svc.money(r.rate)) for r in rates],
    )


def _patch_party(db, model, x, body: s.PartyPatch):
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise svc.invalid("name must not be empty")
        svc.check_unique_name(db, model, name, x.id)
        x.name = name
    if body.phone is not None:
        x.phone = body.phone
    if body.is_active is not None:
        x.is_active = body.is_active


@router.post("/hotels", response_model=s.HotelOut, status_code=201)
def create_hotel(body: s.PartyIn, db: Session = Depends(get_db)):
    svc.check_unique_name(db, m.Hotel, body.name)
    h = m.Hotel(name=body.name, phone=body.phone, is_active=True)
    db.add(h)
    db.flush()
    if body.opening_balance > 0:
        svc.set_opening_balance(db, "hotel", h, body.opening_balance, body.opening_balance_date)
    db.commit()
    return hotel_out(db, h)


@router.get("/hotels", response_model=list[s.HotelOut])
def list_hotels(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = select(m.Hotel).order_by(m.Hotel.name)
    if not include_inactive:
        q = q.where(m.Hotel.is_active.is_(True))
    return [hotel_out(db, h) for h in db.scalars(q)]


@router.get("/hotels/{hotel_id}", response_model=s.HotelOut)
def get_hotel(hotel_id: int, db: Session = Depends(get_db)):
    return hotel_out(db, svc.get_or_404(db, m.Hotel, hotel_id, "Hotel"))


@router.patch("/hotels/{hotel_id}", response_model=s.HotelOut)
def patch_hotel(hotel_id: int, body: s.PartyPatch, db: Session = Depends(get_db)):
    h = svc.get_or_404(db, m.Hotel, hotel_id, "Hotel")
    _patch_party(db, m.Hotel, h, body)
    db.commit()
    return hotel_out(db, h)


@router.get("/hotels/{hotel_id}/rates", response_model=list[s.RateOut])
def list_rates(hotel_id: int, db: Session = Depends(get_db)):
    return hotel_out(db, svc.get_or_404(db, m.Hotel, hotel_id, "Hotel"))["rates"]


@router.put("/hotels/{hotel_id}/rates/{fish_id}", response_model=s.HotelOut)
def set_rate(hotel_id: int, fish_id: int, body: s.RateIn, db: Session = Depends(get_db)):
    h = svc.get_or_404(db, m.Hotel, hotel_id, "Hotel")
    svc.get_or_404(db, m.Fish, fish_id, "Fish")
    r = db.scalar(select(m.HotelRate).where(m.HotelRate.hotel_id == hotel_id, m.HotelRate.fish_id == fish_id))
    if r is None:
        db.add(m.HotelRate(hotel_id=hotel_id, fish_id=fish_id, rate=svc.money(body.rate)))
    else:
        r.rate = svc.money(body.rate)  # only the default changes; past sales keep their own rate
    db.commit()
    db.refresh(h)
    return hotel_out(db, h)


@router.delete("/hotels/{hotel_id}/rates/{fish_id}", response_model=s.HotelOut)
def delete_rate(hotel_id: int, fish_id: int, db: Session = Depends(get_db)):
    h = svc.get_or_404(db, m.Hotel, hotel_id, "Hotel")
    r = db.scalar(select(m.HotelRate).where(m.HotelRate.hotel_id == hotel_id, m.HotelRate.fish_id == fish_id))
    if r is None:
        raise svc.not_found("Rate for fish", fish_id)
    db.delete(r)
    db.commit()
    db.refresh(h)
    return hotel_out(db, h)


@router.get("/hotels/{hotel_id}/opening-balance", response_model=s.OpeningBalanceOut)
def get_hotel_opening(hotel_id: int, db: Session = Depends(get_db)):
    svc.get_or_404(db, m.Hotel, hotel_id, "Hotel")
    return svc.get_opening_balance(db, "hotel", hotel_id)


@router.put("/hotels/{hotel_id}/opening-balance", response_model=s.OpeningBalanceOut)
def put_hotel_opening(hotel_id: int, body: s.OpeningBalanceIn, db: Session = Depends(get_db)):
    h = svc.get_or_404(db, m.Hotel, hotel_id, "Hotel")
    out = svc.set_opening_balance(db, "hotel", h, body.amount, body.balance_date)
    db.commit()
    return out
