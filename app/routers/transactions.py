import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas as s
from .. import services as svc
from ..database import get_db

router = APIRouter(tags=["transactions"])


# ---------- purchases ----------
@router.post("/purchases", response_model=s.PurchaseOut, status_code=201)
def create_purchase(body: s.PurchaseIn, db: Session = Depends(get_db)):
    p = svc.create_purchase(db, body)
    db.commit()
    return svc.purchase_out(p)


@router.get("/purchases", response_model=s.PurchaseList)
def list_purchases(journal_id: Optional[int] = None, supplier_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = select(m.Purchase).order_by(m.Purchase.id)
    if journal_id is not None:
        q = q.where(m.Purchase.journal_id == journal_id)
    if supplier_id is not None:
        q = q.where(m.Purchase.supplier_id == supplier_id)
    return svc.purchase_list(db.scalars(q).all())


@router.get("/purchases/{purchase_id}", response_model=s.PurchaseOut)
def get_purchase(purchase_id: int, db: Session = Depends(get_db)):
    return svc.purchase_out(svc.get_or_404(db, m.Purchase, purchase_id, "Purchase"))


@router.put("/purchases/{purchase_id}", response_model=s.PurchaseOut)
def update_purchase(purchase_id: int, body: s.PurchaseUpdate, db: Session = Depends(get_db)):
    p = svc.get_or_404(db, m.Purchase, purchase_id, "Purchase")
    svc.update_purchase(db, p, body)
    db.commit()
    return svc.purchase_out(p)


@router.delete("/purchases/{purchase_id}", status_code=204)
def delete_purchase(purchase_id: int, db: Session = Depends(get_db)):
    p = svc.get_or_404(db, m.Purchase, purchase_id, "Purchase")
    svc.delete_purchase(db, p)
    db.commit()
    return Response(status_code=204)


# ---------- hotel sales ----------
@router.post("/hotel-sales", response_model=s.HotelSaleOut, status_code=201)
def create_sale(body: s.HotelSaleIn, db: Session = Depends(get_db)):
    x = svc.create_hotel_sale(db, body)
    db.commit()
    return svc.hotel_sale_out(x)


@router.get("/hotel-sales", response_model=s.HotelSaleList)
def list_sales(journal_id: Optional[int] = None, hotel_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = select(m.HotelSale).order_by(m.HotelSale.id)
    if journal_id is not None:
        q = q.where(m.HotelSale.journal_id == journal_id)
    if hotel_id is not None:
        q = q.where(m.HotelSale.hotel_id == hotel_id)
    return svc.hotel_sale_list(db.scalars(q).all())


@router.get("/hotel-sales/{sale_id}", response_model=s.HotelSaleOut)
def get_sale(sale_id: int, db: Session = Depends(get_db)):
    return svc.hotel_sale_out(svc.get_or_404(db, m.HotelSale, sale_id, "Hotel sale"))


@router.put("/hotel-sales/{sale_id}", response_model=s.HotelSaleOut)
def update_sale(sale_id: int, body: s.HotelSaleUpdate, db: Session = Depends(get_db)):
    x = svc.get_or_404(db, m.HotelSale, sale_id, "Hotel sale")
    svc.update_hotel_sale(db, x, body)
    db.commit()
    return svc.hotel_sale_out(x)


@router.delete("/hotel-sales/{sale_id}", status_code=204)
def delete_sale(sale_id: int, db: Session = Depends(get_db)):
    x = svc.get_or_404(db, m.HotelSale, sale_id, "Hotel sale")
    svc.delete_hotel_sale(db, x)
    db.commit()
    return Response(status_code=204)


# ---------- supplier payments (independent of purchases) ----------
@router.post("/supplier-payments", response_model=s.SupplierPaymentOut, status_code=201)
def create_supplier_payment(body: s.SupplierPaymentIn, db: Session = Depends(get_db)):
    p = svc.create_supplier_payment(db, body)
    db.commit()
    return svc.supplier_payment_out(p)


@router.get("/supplier-payments", response_model=list[s.SupplierPaymentOut])
def list_supplier_payments(
    supplier_id: Optional[int] = None, from_date: Optional[dt.date] = None, to_date: Optional[dt.date] = None,
    later_only: bool = False, db: Session = Depends(get_db),
):
    q = select(m.SupplierPayment).order_by(m.SupplierPayment.payment_date, m.SupplierPayment.id)
    if supplier_id is not None:
        q = q.where(m.SupplierPayment.supplier_id == supplier_id)
    if from_date:
        q = q.where(m.SupplierPayment.payment_date >= from_date)
    if to_date:
        q = q.where(m.SupplierPayment.payment_date <= to_date)
    if later_only:
        q = q.where(m.SupplierPayment.purchase_id.is_(None))
    return [svc.supplier_payment_out(p) for p in db.scalars(q)]


def _later_payment(db, payment_id):
    p = svc.get_or_404(db, m.SupplierPayment, payment_id, "Supplier payment")
    if p.purchase_id is not None:
        raise svc.conflict("This payment was made with a purchase. Edit the purchase instead.")
    return p


@router.put("/supplier-payments/{payment_id}", response_model=s.SupplierPaymentOut)
def update_supplier_payment(payment_id: int, body: s.SupplierPaymentIn, db: Session = Depends(get_db)):
    p = _later_payment(db, payment_id)
    svc.update_supplier_payment(db, p, body)
    db.commit()
    return svc.supplier_payment_out(p)


@router.delete("/supplier-payments/{payment_id}", status_code=204)
def delete_supplier_payment(payment_id: int, db: Session = Depends(get_db)):
    db.delete(_later_payment(db, payment_id))
    db.commit()
    return Response(status_code=204)


# ---------- hotel payments ----------
@router.post("/hotel-payments", response_model=s.HotelPaymentOut, status_code=201)
def create_hotel_payment(body: s.HotelPaymentIn, db: Session = Depends(get_db)):
    p = svc.create_hotel_payment(db, body)
    db.commit()
    return svc.hotel_payment_out(p)


@router.get("/hotel-payments", response_model=list[s.HotelPaymentOut])
def list_hotel_payments(
    hotel_id: Optional[int] = None, from_date: Optional[dt.date] = None, to_date: Optional[dt.date] = None,
    db: Session = Depends(get_db),
):
    q = select(m.HotelPayment).order_by(m.HotelPayment.payment_date, m.HotelPayment.id)
    if hotel_id is not None:
        q = q.where(m.HotelPayment.hotel_id == hotel_id)
    if from_date:
        q = q.where(m.HotelPayment.payment_date >= from_date)
    if to_date:
        q = q.where(m.HotelPayment.payment_date <= to_date)
    return [svc.hotel_payment_out(p) for p in db.scalars(q)]


@router.put("/hotel-payments/{payment_id}", response_model=s.HotelPaymentOut)
def update_hotel_payment(payment_id: int, body: s.HotelPaymentIn, db: Session = Depends(get_db)):
    p = svc.get_or_404(db, m.HotelPayment, payment_id, "Hotel payment")
    svc.update_hotel_payment(db, p, body)
    db.commit()
    return svc.hotel_payment_out(p)


@router.delete("/hotel-payments/{payment_id}", status_code=204)
def delete_hotel_payment(payment_id: int, db: Session = Depends(get_db)):
    db.delete(svc.get_or_404(db, m.HotelPayment, payment_id, "Hotel payment"))
    db.commit()
    return Response(status_code=204)
