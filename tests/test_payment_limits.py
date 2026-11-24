"""No advance payments: payments may never exceed the outstanding balance."""
from tests.conftest import P


def _setup(shop):
    j = shop.start("2026-11-02")
    shop.opening(j, Rohu=100, Katla=0, Pomfret=0)
    return j


def test_supplier_payment_over_outstanding_rejected(shop):
    sid = shop.sup["Supplier A"]
    j = _setup(shop)
    shop.buy(j, "Supplier A", "Rohu", 10, 100)  # 1000 due
    r = shop.post("/supplier-payments", {"supplier_id": sid, "amount": 1000.01, "payment_mode": "cash", "payment_date": "2026-11-02"})
    assert r.status_code == 422 and "exceeds outstanding" in r.json()["detail"]
    assert shop.post("/supplier-payments", {"supplier_id": sid, "amount": 1000, "payment_mode": "cash", "payment_date": "2026-11-02"}).status_code == 201
    # now fully paid: any further payment is an advance
    assert shop.post("/supplier-payments", {"supplier_id": sid, "amount": 1, "payment_mode": "cash", "payment_date": "2026-11-02"}).status_code == 422
    assert shop.get("/accounts/suppliers").json()[0]["outstanding"] >= 0


def test_supplier_payment_with_no_dues_rejected(shop):
    r = shop.post("/supplier-payments", {"supplier_id": shop.sup["Supplier B"], "amount": 1, "payment_mode": "upi"})
    assert r.status_code == 422


def test_hotel_payment_over_outstanding_rejected(shop):
    hid = shop.hotel["Hotel A"]
    j = _setup(shop)
    shop.sell(j, "Hotel A", "Rohu", 5)  # 1200
    assert shop.post("/hotel-payments", {"hotel_id": hid, "amount": 1200.5, "payment_mode": "cash", "payment_date": "2026-11-02"}).status_code == 422
    assert shop.post("/hotel-payments", {"hotel_id": hid, "amount": 700, "payment_mode": "cash", "payment_date": "2026-11-02"}).status_code == 201
    assert shop.post("/hotel-payments", {"hotel_id": hid, "amount": 600, "payment_mode": "cash", "payment_date": "2026-11-03"}).status_code == 422
    assert shop.post("/hotel-payments", {"hotel_id": hid, "amount": 500, "payment_mode": "upi", "payment_date": "2026-11-03"}).status_code == 201


def test_payment_dated_before_the_dues_existed_is_rejected(shop):
    hid = shop.hotel["Hotel A"]
    j = _setup(shop)
    shop.sell(j, "Hotel A", "Rohu", 5)  # on 2026-11-02
    r = shop.post("/hotel-payments", {"hotel_id": hid, "amount": 100, "payment_mode": "cash", "payment_date": "2026-11-01"})
    assert r.status_code == 422


def test_later_dated_payment_cannot_make_an_earlier_one_overpay(shop):
    hid = shop.hotel["Hotel A"]
    j = _setup(shop)
    shop.sell(j, "Hotel A", "Rohu", 5)  # 1200
    shop.post("/hotel-payments", {"hotel_id": hid, "amount": 1000, "payment_mode": "cash", "payment_date": "2026-11-20"})
    r = shop.post("/hotel-payments", {"hotel_id": hid, "amount": 500, "payment_mode": "cash", "payment_date": "2026-11-10"})
    assert r.status_code == 422  # balance would be negative on 11-20
    assert shop.get(f"/accounts/hotels/{hid}/ledger").json()["closing_balance"] == 200


def test_editing_payment_cannot_create_overpayment(shop):
    sid = shop.sup["Supplier A"]
    j = _setup(shop)
    shop.buy(j, "Supplier A", "Rohu", 10, 100)
    pid = shop.post("/supplier-payments", {"supplier_id": sid, "amount": 400, "payment_mode": "cash", "payment_date": "2026-11-02"}).json()["id"]
    body = {"supplier_id": sid, "amount": 1500, "payment_mode": "cash", "payment_date": "2026-11-02"}
    assert shop.put(f"/supplier-payments/{pid}", body).status_code == 422
    assert shop.put(f"/supplier-payments/{pid}", {**body, "amount": 1000}).status_code == 200


def test_reducing_or_deleting_dues_below_payments_is_rejected(shop):
    sid, hid = shop.sup["Supplier A"], shop.hotel["Hotel A"]
    j = _setup(shop)
    p = shop.buy(j, "Supplier A", "Rohu", 10, 100).json()
    s = shop.sell(j, "Hotel A", "Rohu", 5).json()
    shop.post("/supplier-payments", {"supplier_id": sid, "amount": 800, "payment_mode": "cash", "payment_date": "2026-11-02"})
    shop.post("/hotel-payments", {"hotel_id": hid, "amount": 1000, "payment_mode": "cash", "payment_date": "2026-11-02"})
    assert shop.c.delete(f"{P}/purchases/{p['id']}").status_code == 422
    assert shop.c.delete(f"{P}/hotel-sales/{s['id']}").status_code == 422
    upd = {"supplier_id": sid, "fish_id": shop.fish["Rohu"], "quantity": 5, "rate": 100}  # 500 < 800 paid
    assert shop.put(f"/purchases/{p['id']}", upd).status_code == 422
    assert len(shop.get("/purchases").json()["entries"]) == 1  # nothing changed
    assert shop.get(f"/accounts/hotels/{hid}/ledger").json()["closing_balance"] == 200


def test_paid_now_still_cannot_exceed_amount(shop):
    j = _setup(shop)
    assert shop.buy(j, "Supplier A", "Rohu", 1, 100, 100.01, "cash").status_code == 422
    assert shop.buy(j, "Supplier A", "Rohu", 1, 100, 100, "cash").status_code == 201
