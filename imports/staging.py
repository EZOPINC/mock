"""Private expiring JSON staging; never placed under static/media or in sessions."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
import time
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import Http404


def root():
    path = settings.IMPORT_STAGING_ROOT
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def path_for(token):
    try:
        token = uuid.UUID(str(token))
    except (ValueError, TypeError, AttributeError):
        raise Http404
    return root() / f"{token}.json"


def cleanup():
    removed = 0
    for path in root().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["expires_at"] < time.time():
                path.unlink(missing_ok=True)
                removed += 1
        except (OSError, ValueError, KeyError):
            continue
    for pattern in ("*.tmp", "*.lock"):
        for path in root().glob(pattern):
            try:
                if path.stat().st_mtime < time.time() - settings.IMPORT_STAGE_SECONDS:
                    path.unlink(missing_ok=True)
            except OSError:
                continue
    return removed


def save(data):
    serialized = json.dumps(data, ensure_ascii=False)
    if len(serialized.encode()) > 20 * 1024 * 1024:
        raise ValidationError("Preview exceeds the 20 MB staging limit. Split the file.")
    path = path_for(data["token"])
    temporary = path.with_suffix(f".{uuid.uuid4()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            os.chmod(temporary, 0o600)
            handle.write(serialized)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def create(user, data):
    cleanup()
    data = {**data, "token": str(uuid.uuid4()), "owner": user.pk, "expires_at": time.time() + settings.IMPORT_STAGE_SECONDS}
    save(data)
    return data


def load(token, user):
    path = path_for(token)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        raise Http404
    if data["owner"] != user.pk:
        raise Http404
    if data["expires_at"] < time.time():
        path.unlink(missing_ok=True)
        raise ValidationError("This preview expired. Upload the file again.")
    return data


def digest(data):
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@contextmanager
def locked(token):
    path = path_for(token).with_suffix(".lock")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValidationError("This preview is being processed. Please try again shortly.")
    try:
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)
