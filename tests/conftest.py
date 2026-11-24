import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401
from app.database import Base, get_db, make_engine
from app.main import app
from app.security import limiter, require_auth

P = "/api/v1"


@pytest.fixture()
def raw_client():
    """App with in-memory DB and REAL authentication (used by auth tests)."""
    limiter.reset()
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    c = TestClient(app)  # lifespan not started: tests use the in-memory DB only
    c.session_factory = Session
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client(raw_client):
    """Same app with authentication bypassed, so business-rule tests stay readable."""
    app.dependency_overrides[require_auth] = lambda: None
    yield raw_client


class Shop:
    """Helpers so tests read like the requirement document."""

    def __init__(self, c):
        self.c = c
        self.fish = {n: self.post("/fish", {"name": n}).json()["id"] for n in ("Rohu", "Katla", "Pomfret")}
        self.sup = {n: self.post("/suppliers", {"name": n}).json()["id"] for n in ("Supplier A", "Supplier B")}
        self.hotel = {n: self.post("/hotels", {"name": n}).json()["id"] for n in ("Hotel A", "Hotel B", "Hotel C")}
        rates = {"Hotel A": (240, 280, 420), "Hotel B": (230, 270, 400), "Hotel C": (250, 290, 430)}
        for h, rs in rates.items():
            for f, r in zip(("Rohu", "Katla", "Pomfret"), rs):
                self.c.put(f"{P}/hotels/{self.hotel[h]}/rates/{self.fish[f]}", json={"rate": r})

    def post(self, path, body):
        return self.c.post(P + path, json=body)

    def get(self, path, **params):
        return self.c.get(P + path, params=params)

    def put(self, path, body):
        return self.c.put(P + path, json=body)

    def start(self, day):
        r = self.post("/journals", {"business_date": day})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def opening(self, jid, **qty):
        items = [{"fish_id": self.fish[n], "quantity": q} for n, q in qty.items()]
        r = self.put(f"/journals/{jid}/opening-stock", {"items": items})
        assert r.status_code == 200, r.text
        return r.json()

    def buy(self, jid, supplier, fish, q, rate, paid=0, mode=None):
        body = {"journal_id": jid, "supplier_id": self.sup[supplier], "fish_id": self.fish[fish],
                "quantity": q, "rate": rate, "paid_now": paid, "payment_mode": mode}
        return self.post("/purchases", body)

    def sell(self, jid, hotel, fish, q, rate=None):
        body = {"journal_id": jid, "hotel_id": self.hotel[hotel], "fish_id": self.fish[fish], "quantity": q}
        if rate is not None:
            body["rate"] = rate
        return self.post("/hotel-sales", body)

    def close_body(self, remaining, cash=0, upi=0):
        return {"stocks": [{"fish_id": self.fish[n], "quantity": q} for n, q in remaining.items()],
                "cash_amount": cash, "upi_amount": upi}

    def close(self, jid, cash=0, upi=0, **remaining):
        return self.post(f"/journals/{jid}/close", self.close_body(remaining, cash, upi))

    def day(self, day, opening, remaining, cash=0, upi=0, buys=(), sells=()):
        """Run a full simple day. Returns journal id."""
        jid = self.start(day)
        self.opening(jid, **opening)
        for b in buys:
            assert self.buy(jid, *b[:4], *b[4:]).status_code == 201
        for sl in sells:
            assert self.sell(jid, *sl).status_code == 201
        r = self.close(jid, cash, upi, **remaining)
        assert r.status_code == 200, r.text
        return jid


@pytest.fixture()
def shop(client):
    return Shop(client)


def row(detail, fish_name):
    return next(r for r in detail["stock"]["rows"] if r["fish_name"] == fish_name)
