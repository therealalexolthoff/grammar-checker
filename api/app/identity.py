"""Identity Platform access: student user lifecycle and ID token verification.

Wraps firebase_admin so the rest of the API never imports it directly -
that makes it simple to monkeypatch in tests (see api/tests/conftest.py)
instead of needing live Identity Platform credentials to run the suite.

The teacher's own account (email + password + TOTP) is created once by
hand in the Identity Platform console during setup, not through this API -
see docs/REQUIREMENTS.md FR-1/FR-2 (no self-signup for anyone).
"""

import firebase_admin
from firebase_admin import auth as fb_auth

STUDENT_EMAIL_DOMAIN = "students.internal"

_app: firebase_admin.App | None = None


def _get_app() -> firebase_admin.App:
    global _app
    if _app is None:
        _app = firebase_admin.initialize_app()
    return _app


def student_email(username: str) -> str:
    return f"{username}@{STUDENT_EMAIL_DOMAIN}"


def create_student_user(username: str, password: str) -> str:
    """Creates the Identity Platform user for a new student. Returns the auth uid."""
    _get_app()
    user = fb_auth.create_user(
        email=student_email(username),
        password=password,
        # True because this address is synthetic and unreachable, not because
        # anyone verified it - there's no inbox to check. Avoids the console
        # showing a permanently "unverified" account.
        email_verified=True,
    )
    return user.uid


def set_student_claims(uid: str, student_id: str) -> None:
    _get_app()
    fb_auth.set_custom_user_claims(uid, {"role": "student", "student_id": student_id})


def disable_user(uid: str) -> None:
    _get_app()
    fb_auth.update_user(uid, disabled=True)


def enable_user(uid: str) -> None:
    _get_app()
    fb_auth.update_user(uid, disabled=False)


def reset_password(uid: str, new_password: str) -> None:
    _get_app()
    fb_auth.update_user(uid, password=new_password)


def delete_user(uid: str) -> None:
    _get_app()
    fb_auth.delete_user(uid)


def verify_id_token(token: str) -> dict:
    """Returns the decoded token claims, including role/student_id custom
    claims. Raises firebase_admin.auth errors on an invalid/expired token."""
    _get_app()
    return fb_auth.verify_id_token(token)
