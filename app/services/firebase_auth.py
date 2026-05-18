"""
Firebase Auth service — wrapper around firebase-admin SDK.
Handles lazy initialization and user verification.
"""

import os
import firebase_admin
from firebase_admin import credentials, auth


_firebase_app = None


def _ensure_initialized():
    """Lazily initialize the Firebase Admin SDK."""
    global _firebase_app
    if _firebase_app is not None:
        return

    cred_path = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_PATH",
        "./firebase-service-account.json",
    )

    if os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        _firebase_app = firebase_admin.initialize_app(cred)
    else:
        print(f"⚠️  Firebase credentials not found at {cred_path}")
        print("   Auth verification will fail. Set FIREBASE_SERVICE_ACCOUNT_PATH.")


def verify_id_token(id_token: str) -> dict:
    """Verify a Firebase ID token and return the decoded claims."""
    _ensure_initialized()
    return auth.verify_id_token(id_token)


def get_user_by_phone(phone_number: str):
    """Look up a Firebase user by phone number."""
    _ensure_initialized()
    return auth.get_user_by_phone_number(phone_number)
