"""Initialise le Garage local (développement, CI) par son API d'administration.

Idempotent : à chaque démarrage de la pile, s'assure que le nœud a un rôle dans le
cluster, que la clé d'accès de l'API existe et que les buckets sont créés et
autorisés. Bibliothèque standard uniquement (exécuté dans l'image de l'API).

Variables : GARAGE_ADMIN_URL, GARAGE_ADMIN_TOKEN, S3_ACCESS_KEY_ID,
S3_SECRET_ACCESS_KEY, S3_BUCKETS (noms séparés par des virgules).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

ADMIN_URL = os.environ["GARAGE_ADMIN_URL"].rstrip("/")
TOKEN = os.environ["GARAGE_ADMIN_TOKEN"]
KEY_ID = os.environ["S3_ACCESS_KEY_ID"]
SECRET = os.environ["S3_SECRET_ACCESS_KEY"]
BUCKETS = [b.strip() for b in os.environ["S3_BUCKETS"].split(",") if b.strip()]
# Capacité déclarée du nœud unique (indicative : elle sert au placement des données).
CAPACITY_BYTES = 10 * 1024**3


class AdminError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status} : {body}")
        self.status = status


def call(endpoint: str, body: dict[str, Any] | None = None, **query: str) -> Any:
    url = f"{ADMIN_URL}/v2/{endpoint}"
    if query:
        url += "?" + "&".join(f"{k}={urllib.request.quote(v)}" for k, v in query.items())
    request = urllib.request.Request(  # noqa: S310  (URL d'administration fixée par la pile)
        url,
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raise AdminError(exc.code, exc.read().decode(errors="replace")) from exc


def wait_for_admin() -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while True:
        try:
            return call("GetClusterStatus")
        except (urllib.error.URLError, ConnectionError, AdminError) as exc:
            if time.monotonic() > deadline:
                raise SystemExit(f"Garage injoignable : {exc}") from exc
            time.sleep(1)


def ensure_layout(status: dict[str, Any]) -> None:
    node = status["nodes"][0]
    if node.get("role"):
        return
    call(
        "UpdateClusterLayout",
        {"roles": [{"id": node["id"], "zone": "local", "capacity": CAPACITY_BYTES, "tags": []}]},
    )
    call("ApplyClusterLayout", {"version": status["layoutVersion"] + 1})
    print("Garage : rôle du nœud attribué.")


def ensure_key() -> None:
    try:
        call("GetKeyInfo", id=KEY_ID)
    except AdminError as exc:
        if exc.status not in (400, 404):
            raise
        call("ImportKey", {"accessKeyId": KEY_ID, "secretAccessKey": SECRET, "name": "kora-api"})
        print("Garage : clé d'accès de l'API importée.")


def ensure_bucket(alias: str) -> None:
    try:
        bucket = call("GetBucketInfo", globalAlias=alias)
    except AdminError as exc:
        if exc.status not in (400, 404):
            raise
        bucket = call("CreateBucket", {"globalAlias": alias})
        print(f"Garage : bucket {alias} créé.")
    call(
        "AllowBucketKey",
        {
            "bucketId": bucket["id"],
            "accessKeyId": KEY_ID,
            "permissions": {"read": True, "write": True, "owner": False},
        },
    )


def wait_for_health() -> None:
    deadline = time.monotonic() + 60
    while True:
        try:
            with urllib.request.urlopen(f"{ADMIN_URL}/health", timeout=5):  # noqa: S310
                return
        except (urllib.error.URLError, ConnectionError) as exc:
            if time.monotonic() > deadline:
                raise SystemExit(f"Garage ne devient pas disponible : {exc}") from exc
            time.sleep(1)


def main() -> None:
    ensure_layout(wait_for_admin())
    ensure_key()
    for alias in BUCKETS:
        ensure_bucket(alias)
    wait_for_health()
    print(f"Garage prêt : buckets {', '.join(BUCKETS)}.")


if __name__ == "__main__":
    main()
    sys.exit(0)
