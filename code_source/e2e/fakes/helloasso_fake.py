"""
Fake HelloAsso API v5 for the e2e tests: the server reaches it through HELLOASSO_API_BASE_URL /
HELLOASSO_OAUTH_URL (honoured in dev mode only, see infrastructure/runtime_env.py).

Serves the endpoints used by src/helloasso_api.py, from data each test loads with
PUT /_e2e/state {"forms": [...], "items": [...]} (HelloAsso v5 item objects). The response shapes
follow the real API (data + pagination, amounts in cents).

    uvicorn helloasso_fake:app --app-dir e2e/fakes --port 8095
"""
from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="Fake HelloAsso")
_state = {"forms": [], "items": []}


def _page(data: list) -> dict:
    # No continuation token: helloasso_api.fetch_all_pages stops after this page
    return {"data": data, "pagination": {"pageSize": 100, "totalCount": len(data), "pageIndex": 1}}


def _order_items(order_id: int) -> list:
    return [i for i in _state["items"] if (i.get("order") or {}).get("id") == order_id]


# --- test control ---------------------------------------------------------
@app.put("/_e2e/state")
async def set_state(request: Request):
    body = await request.json()
    _state["forms"] = list(body.get("forms") or [])
    _state["items"] = list(body.get("items") or [])
    return {"forms": len(_state["forms"]), "items": len(_state["items"])}


# --- HelloAsso API ----------------------------------------------------------
@app.post("/oauth2/token")
def token():
    return {"access_token": "fake-helloasso-token", "token_type": "bearer", "expires_in": 1800}


@app.get("/v5/organizations/{org}/forms")
def forms(org: str):
    return _page(_state["forms"])


@app.get("/v5/organizations/{org}/forms/{form_type}/{form_slug}/items")
def form_items(org: str, form_type: str, form_slug: str):
    return _page([i for i in _state["items"] if (i.get("order") or {}).get("formSlug") == form_slug])


@app.get("/v5/organizations/{org}/forms/{form_type}/{form_slug}/payments")
def form_payments(org: str, form_type: str, form_slug: str):
    return _page([])


@app.get("/v5/items/{item_id}")
def item(item_id: int):
    found = next((i for i in _state["items"] if i.get("id") == item_id), None)
    if found is None:
        raise HTTPException(404)
    return found


@app.get("/v5/orders/{order_id}")
def order(order_id: int):
    items = _order_items(order_id)
    if not items:
        raise HTTPException(404)
    return {**items[0]["order"], "items": [{"id": i["id"]} for i in items]}


@app.get("/v5/payments/{payment_id}")
def payment(payment_id: int):
    # One payment per order in the test data: same id as the order
    items = _order_items(payment_id)
    if not items:
        raise HTTPException(404)
    return {"id": payment_id, "order": {"id": payment_id}, "items": [{"id": i["id"]} for i in items]}
