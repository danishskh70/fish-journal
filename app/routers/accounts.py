import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from .. import services as svc
from ..database import get_db

router = APIRouter(tags=["accounts"])


@router.get("/dashboard", response_model=s.Dashboard)
def dashboard(business_date: Optional[dt.date] = None, db: Session = Depends(get_db)):
    out = svc.dashboard(db, business_date or dt.date.today())
    db.commit()
    return out


@router.get("/accounts/hotels", response_model=list[s.Balance])
def hotel_balances(as_of: Optional[dt.date] = None, db: Session = Depends(get_db)):
    return [dict(id=h.id, name=h.name, outstanding=svc.hotel_balance(db, h.id, as_of))
            for h in db.scalars(select(m.Hotel).order_by(m.Hotel.name))]


@router.get("/accounts/suppliers", response_model=list[s.Balance])
def supplier_balances(as_of: Optional[dt.date] = None, db: Session = Depends(get_db)):
    return [dict(id=x.id, name=x.name, outstanding=svc.supplier_balance(db, x.id, as_of))
            for x in db.scalars(select(m.Supplier).order_by(m.Supplier.name))]


@router.get("/accounts/hotels/monthly-summary", response_model=list[s.MonthlyHotelSummary])
def all_hotels_monthly(year: int, month: int, db: Session = Depends(get_db)):
    return [svc.hotel_monthly_summary(db, h, year, month) for h in db.scalars(select(m.Hotel).order_by(m.Hotel.name))]


@router.get("/accounts/hotels/{hotel_id}/ledger", response_model=s.Ledger)
def hotel_ledger(hotel_id: int, from_date: Optional[dt.date] = None, to_date: Optional[dt.date] = None,
                 db: Session = Depends(get_db)):
    return svc.hotel_ledger(db, svc.get_or_404(db, m.Hotel, hotel_id, "Hotel"), from_date, to_date)


@router.get("/accounts/hotels/{hotel_id}/monthly-summary", response_model=s.MonthlyHotelSummary)
def hotel_monthly(hotel_id: int, year: int, month: int, db: Session = Depends(get_db)):
    return svc.hotel_monthly_summary(db, svc.get_or_404(db, m.Hotel, hotel_id, "Hotel"), year, month)


@router.get("/accounts/suppliers/{supplier_id}/ledger", response_model=s.Ledger)
def supplier_ledger(supplier_id: int, from_date: Optional[dt.date] = None, to_date: Optional[dt.date] = None,
                    db: Session = Depends(get_db)):
    return svc.supplier_ledger(db, svc.get_or_404(db, m.Supplier, supplier_id, "Supplier"), from_date, to_date)
