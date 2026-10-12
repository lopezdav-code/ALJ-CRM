"""
Sign-in against the Firebase Auth emulator without its account picker.

The emulator accepts an unsigned Google id_token (a plain JSON object), exactly as
dev/seed/seed_emulator.py does with accounts:signInWithIdp: signing in with the seeded `sub`
reuses the seeded account, custom claims (roles) included. Only the picker test goes through
the real redirect flow.
"""
from dataclasses import dataclass

from playwright.sync_api import Page


@dataclass(frozen=True)
class Account:
    sub: str
    email: str


# Same accounts as DEV_ACCOUNTS in dev/seed/seed_emulator.py
ACCOUNTS = {
    "admin": Account("dev-dumbledore", "albus.dumbledore@alj-escalade.fr"),
    "coach": Account("dev-snape", "severus.snape@hogwarts.example"),
    "readonly": Account("dev-filch", "argus.filch@hogwarts.example"),
    # Not seeded: created on first sign-in, without any role
    "stranger": Account("e2e-stranger", "stranger@hogwarts.example"),
}

_SIGN_IN = """async ([sub, email]) => {
  const { auth } = ALJFirebase.init();
  const idToken = JSON.stringify({ sub, email, email_verified: true });
  await auth.signInWithCredential(firebase.auth.GoogleAuthProvider.credential(idToken));
}"""


def login_as(page: Page, role: str) -> Account:
    """Signs the current page in; the page's onAuthStateChanged handler then renders the UI."""
    account = ACCOUNTS[role]
    page.wait_for_function("() => window.ALJFirebase && window.firebase")
    page.evaluate(_SIGN_IN, [account.sub, account.email])
    return account
