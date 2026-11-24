import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from .. import services as svc
from ..database import get_db

router = APIRouter(tags=["journals"])


@router.post("/journals", response_model=s.JournalDetail, status_code=201)
def start_journal(body: s.JournalCreate, db: Session = Depends(get_db)):
    j = svc.create_journal(db, body.business_date or dt.date.today())
    db.commit()
    return svc.journal_detail(db, j)


@router.get("/journals/by-date/{business_date}", response_model=s.JournalDetail)
def journal_by_date(business_date: dt.date, db: Session = Depends(get_db)):
    j = db.scalar(select(m.Journal).where(m.Journal.business_date == business_date))
    if j is None:
        raise svc.HTTPException(404, f"No journal for {business_date}")
    out = svc.journal_detail(db, j)
    db.commit()
    return out


@router.get("/journals/{journal_id}", response_model=s.JournalDetail)
def get_journal(journal_id: int, db: Session = Depends(get_db)):
    j = svc.get_or_404(db, m.Journal, journal_id, "Journal")
    out = svc.journal_detail(db, j)
    db.commit()
    return out


@router.put("/journals/{journal_id}/opening-stock", response_model=s.JournalDetail)
def confirm_opening_stock(journal_id: int, body: s.OpeningIn, db: Session = Depends(get_db)):
    j = svc.get_or_404(db, m.Journal, journal_id, "Journal")
    svc.set_opening_stock(db, j, body.items)
    db.commit()
    return svc.journal_detail(db, j)


@router.post("/journals/{journal_id}/close-preview", response_model=s.ClosePreview)
def close_preview(journal_id: int, body: s.ClosingIn, db: Session = Depends(get_db)):
    j = svc.get_or_404(db, m.Journal, journal_id, "Journal")
    out = svc.close_preview(db, j, body)
    db.rollback()  # preview never saves
    return out


@router.post("/journals/{journal_id}/close", response_model=s.JournalDetail)
def close_journal(journal_id: int, body: s.ClosingIn, db: Session = Depends(get_db)):
    j = svc.get_or_404(db, m.Journal, journal_id, "Journal")
    svc.close_journal(db, j, body)
    db.commit()
    return svc.journal_detail(db, j)


@router.post("/journals/{journal_id}/reopen", response_model=s.JournalDetail)
def reopen_journal(journal_id: int, body: s.ReopenIn, db: Session = Depends(get_db)):
    j = svc.get_or_404(db, m.Journal, journal_id, "Journal")
    svc.reopen_journal(db, j, body.confirm)
    db.commit()
    return svc.journal_detail(db, j)


@router.get("/history", response_model=list[s.HistoryRow])
def history(
    from_date: Optional[dt.date] = None,
    to_date: Optional[dt.date] = None,
    limit: int = 60,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = select(m.Journal).order_by(m.Journal.business_date.desc()).limit(min(max(limit, 1), 366)).offset(max(offset, 0))
    if from_date:
        q = q.where(m.Journal.business_date >= from_date)
    if to_date:
        q = q.where(m.Journal.business_date <= to_date)
    out = []
    for j in db.scalars(q):
        closed = j.status == "closed"
        cash = svc.money(j.cash_amount) if closed else None
        upi = svc.money(j.upi_amount) if closed else None
        out.append(dict(id=j.id, business_date=j.business_date, status=j.status, cash_amount=cash,
                        upi_amount=upi, total_money=svc.money(cash + upi) if closed else None))
    return out
