import json

import pytest

from kora.scripts import export_openapi


def test_export_openapi_produit_un_schema_valide(capsys: pytest.CaptureFixture[str]) -> None:
    export_openapi.main()
    schema = json.loads(capsys.readouterr().out)
    assert schema["info"]["title"] == "Kora Finance API"
    assert "/health/ready" in schema["paths"]
