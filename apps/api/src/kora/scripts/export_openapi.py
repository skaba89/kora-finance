"""Écrit le schéma OpenAPI de l'API sur stdout (contrat consommé par apps/web)."""

import json
import sys

from kora.main import create_app


def main() -> None:
    schema = create_app().openapi()
    json.dump(schema, sys.stdout, indent=2, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
