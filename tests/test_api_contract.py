def test_numbers_are_json_numbers_not_strings(shop):
    jid = shop.start("2026-11-02")
    shop.opening(jid, Rohu=1.5, Katla=0, Pomfret=0)
    d = shop.get(f"/journals/{jid}").json()
    assert isinstance(d["stock"]["rows"][0]["opening_quantity"], (int, float))


def test_quantity_precision_and_negative_values_rejected(shop):
    jid = shop.start("2026-11-02")
    assert shop.put(f"/journals/{jid}/opening-stock", {"items": [{"fish_id": shop.fish["Rohu"], "quantity": -1}]}).status_code == 422
    assert shop.buy(jid, "Supplier A", "Rohu", 1.2345, 100).status_code == 422  # max 3 decimals


def test_unknown_ids_return_404(shop):
    assert shop.get("/journals/999").status_code == 404
    assert shop.get("/hotels/999").status_code == 404
    assert shop.get("/accounts/suppliers/999/ledger").status_code == 404
    assert shop.post("/hotel-payments", {"hotel_id": 999, "amount": 1, "payment_mode": "cash"}).status_code == 404
