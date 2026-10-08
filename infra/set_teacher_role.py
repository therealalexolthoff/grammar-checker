"""Marks the teacher's Identity Platform account with role "teacher".

The API refuses any token without a role claim (api/app/auth.py). Student
accounts get theirs when the teacher creates them; the teacher's own
account needs this one-time step. Safe to run again: it prints the
current state and only writes if the claim is missing.

Usage (needs `gcloud auth application-default login` first):
    GOOGLE_CLOUD_PROJECT=<project id> python infra/set_teacher_role.py <teacher email>
"""

import os
import sys

import firebase_admin
from firebase_admin import auth


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    firebase_admin.initialize_app(options={"projectId": os.environ["GOOGLE_CLOUD_PROJECT"]})
    user = auth.get_user_by_email(sys.argv[1])
    print(f"claims: {user.custom_claims} | email verified: {user.email_verified} | disabled: {user.disabled}")

    if (user.custom_claims or {}).get("role") == "teacher":
        print("Already set - nothing to do.")
        return
    auth.set_custom_user_claims(user.uid, {**(user.custom_claims or {}), "role": "teacher"})
    print('Set role "teacher". Sign out and back in for it to take effect.')


if __name__ == "__main__":
    main()
