"""Handwriting photos in the private Cloud Storage bucket (FR-23 to FR-25).

The teacher's browser shrinks each photo and re-saves it as a JPEG before
uploading (that already drops EXIF). The API doesn't rely on that: every
upload goes through strip_jpeg_metadata here before it is stored.

Photos are stored under "{student_id}/{exercise_id}/", so deleting a
student (Phase 8) can remove all their photos by that prefix. Nobody
reads the bucket directly; the teacher sees photos only through
short-lived signed URLs (docs/ARCHITECTURE.md section 6).
"""

from datetime import timedelta
from functools import cache

import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage

from .config import settings

SIGNED_URL_LIFETIME = timedelta(minutes=15)

# JPEG segment types that only hold metadata: APP1-APP15 (EXIF - which
# includes GPS location - XMP, ICC colour profiles, camera maker notes)
# and COM (free-text comments). APP0 is the plain JFIF header and stays.
_METADATA_MARKERS = set(range(0xE1, 0xF0)) | {0xFE}
_START_OF_SCAN = 0xDA


def strip_jpeg_metadata(data: bytes) -> bytes:
    """Returns the JPEG with every metadata segment removed. The image
    itself is copied byte for byte. Raises ValueError if `data` isn't a
    JPEG.

    A JPEG starts with the bytes FF D8, then a list of segments: FF, a
    type byte, a 2-byte length (which counts itself), and the contents.
    The compressed picture starts at the "start of scan" segment and runs
    to the end of the file, so everything from there is copied as is.
    """
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("not a JPEG")
    out = bytearray(b"\xff\xd8")
    i = 2
    while True:
        if i + 4 > len(data) or data[i] != 0xFF:
            raise ValueError("malformed JPEG")
        marker = data[i + 1]
        if marker == 0xFF:  # padding byte before a marker
            i += 1
            continue
        if marker == _START_OF_SCAN:
            out += data[i:]
            return bytes(out)
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if length < 2 or i + 2 + length > len(data):
            raise ValueError("malformed JPEG")
        if marker not in _METADATA_MARKERS:
            out += data[i : i + 2 + length]
        i += 2 + length


@cache
def _bucket() -> storage.Bucket:
    return storage.Client().bucket(settings.photo_bucket)


def photo_path(student_id: str, exercise_id: str, name: str) -> str:
    return f"{student_id}/{exercise_id}/{name}.jpg"


def upload(path: str, data: bytes) -> None:
    _bucket().blob(path).upload_from_string(data, content_type="image/jpeg")


def download(path: str) -> bytes:
    return _bucket().blob(path).download_as_bytes()


def delete(path: str) -> None:
    _bucket().blob(path).delete()


def delete_folder(prefix: str) -> None:
    """Deletes every photo whose path starts with `prefix` - e.g. all of
    one student's photos, "{student_id}/"."""
    for blob in _bucket().list_blobs(prefix=prefix):
        blob.delete()


def signed_url(path: str) -> str:
    """A link that shows one photo for SIGNED_URL_LIFETIME, then stops
    working. On Cloud Run there is no private key file, so the URL is
    signed through the IAM API with the service's own identity (which
    needs roles/iam.serviceAccountTokenCreator on itself - see
    infra/setup_gcp.sh)."""
    credentials, _ = google.auth.default()
    credentials.refresh(Request())
    return _bucket().blob(path).generate_signed_url(
        version="v4",
        expiration=SIGNED_URL_LIFETIME,
        method="GET",
        service_account_email=credentials.service_account_email,
        access_token=credentials.token,
    )
