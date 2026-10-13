"""Client of the fake HelloAsso (e2e/fakes/helloasso_fake.py) and builders of HelloAsso v5 objects."""
import itertools
import json
import urllib.request

FAKE_PORT = 8095
FAKE_URL = f"http://localhost:{FAKE_PORT}"
ORG_SLUG = "alj-e2e"
# Competition registrations form (app setting HELLOASSO_ANNUAL_CAMPAIGN) and membership form (CAMPAIGN_SLUG)
COMPETITION_FORM = "competitions-e2e"
MEMBERSHIP_FORM = "adhesion-e2e"
WEBHOOK_TOKEN = "e2e-webhook-token"

SERVER_ENV = {
    "HELLOASSO_API_BASE_URL": f"{FAKE_URL}/v5",
    "HELLOASSO_OAUTH_URL": f"{FAKE_URL}/oauth2/token",
    "HELLOASSO_CLIENT_ID": "e2e-client",
    "HELLOASSO_CLIENT_SECRET": "e2e-secret",
    "HELLOASSO_ORG_SLUG": ORG_SLUG,
    "HELLOASSO_WEBHOOK_TOKEN": WEBHOOK_TOKEN,
    "CAMPAIGN_SLUG": MEMBERSHIP_FORM,
}

_ids = itertools.count(900_001)


def form(slug: str, form_type: str = "Event") -> dict:
    return {"formSlug": slug, "formType": form_type, "title": slug}


def item(first_name: str, last_name: str, amount_eur: float, licence: str = "", competition_number: str = "",
         state: str = "Processed", form_slug: str = COMPETITION_FORM, item_type: str = "Registration",
         name: str = "Inscription compétition") -> dict:
    """A paid HelloAsso item (one order per item, amount in cents as in the API)."""
    item_id = next(_ids)
    custom_fields = []
    if licence:
        custom_fields.append({"name": "Numéro de licence FFME", "type": "TextInput", "answer": licence})
    if competition_number:
        custom_fields.append({"name": "Numéro de la compétition", "type": "TextInput", "answer": competition_number})
    return {
        "id": item_id,
        "name": name,
        "type": item_type,
        "state": state,
        "amount": int(round(amount_eur * 100)),
        "user": {"firstName": first_name, "lastName": last_name},
        "payer": {"firstName": first_name, "lastName": last_name, "email": f"{first_name}.{last_name}@hogwarts.example"},
        "order": {"id": item_id, "date": "2026-10-01T10:00:00+02:00", "formSlug": form_slug,
                  "formType": "Event", "formName": form_slug},
        "customFields": custom_fields,
        "payments": [{"id": item_id, "amount": int(round(amount_eur * 100)), "state": "Authorized",
                      "date": "2026-10-01T10:00:00+02:00"}],
    }


class FakeHelloAsso:
    def set(self, items: list, forms: list = None) -> None:
        forms = forms if forms is not None else [form(COMPETITION_FORM), form(MEMBERSHIP_FORM, "Membership")]
        body = json.dumps({"forms": forms, "items": items}).encode()
        req = urllib.request.Request(f"{FAKE_URL}/_e2e/state", data=body, method="PUT",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).read()

    def clear(self) -> None:
        self.set([])
