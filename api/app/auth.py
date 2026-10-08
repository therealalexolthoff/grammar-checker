"""Authorization: who is calling, and what they're allowed to touch.

Every endpoint except /health* depends on one of these. There is no
endpoint that skips authorization - see docs/ARCHITECTURE.md section 6.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from . import identity


@dataclass
class CurrentUser:
    uid: str
    role: str  # "teacher" or "student"
    student_id: str | None  # set only when role == "student"


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = authorization.removeprefix("Bearer ")
    try:
        claims = identity.verify_id_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc

    role = claims.get("role")
    if role not in ("teacher", "student"):
        raise HTTPException(status_code=401, detail="token missing a role claim")

    # Teacher MFA is enforced here, not just in the login screen
    # (docs/REQUIREMENTS.md FR-2). Identity Platform records the second
    # factor used for this sign-in in the token's "firebase" claim; a
    # password-only teacher token is refused.
    if role == "teacher" and claims.get("firebase", {}).get("sign_in_second_factor") != "totp":
        raise HTTPException(status_code=401, detail="teacher sign-in requires the authenticator code")

    return CurrentUser(uid=claims["uid"], role=role, student_id=claims.get("student_id"))


def require_teacher(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="teacher only")
    return user


def require_self_or_teacher(student_id: str, user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """For endpoints under /students/{student_id}: only the teacher, or the
    student that this ID belongs to, may proceed."""
    if user.role == "teacher":
        return user
    if user.role == "student" and user.student_id == student_id:
        return user
    raise HTTPException(status_code=403, detail="not authorized for this student")
