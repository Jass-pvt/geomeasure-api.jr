import json
from datetime import datetime

import numpy as np
import pandas as pd

from app.services.serialization import sanitize_properties, to_json_safe


def test_unexpected_error_hides_internals(client, upload, sample_kml):
    async def explode(_upload):
        raise RuntimeError("secret internal detail at /srv/private/path")

    client.app.state.processor.process = explode
    response = upload(client, "sample.kml", sample_kml)
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "An unexpected internal error occurred."}
    }
    assert "secret" not in response.text and "Traceback" not in response.text


def test_unknown_route_uses_structured_error(client):
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_wrong_method_uses_structured_error(client):
    response = client.delete("/api/files/")
    assert response.status_code == 405
    assert set(response.json()["error"]) == {"code", "message"}


def test_numpy_and_pandas_values_become_json_native():
    values = {
        "int": np.int64(7),
        "float": np.float64(1.5),
        "bool": np.bool_(True),
        "nan": float("nan"),
        "inf": float("inf"),
        "none": None,
        "ts": pd.Timestamp("2026-01-02T03:04:05"),
        "nat": pd.NaT,
        "dt": datetime(2026, 1, 2),
        "bytes": b"abc",
        "nested": {"a": [np.int32(1), np.float32(2.5)]},
        "obj": object,
    }
    safe, warnings = sanitize_properties(values)
    json.dumps(safe, allow_nan=False)
    assert safe["int"] == 7 and isinstance(safe["int"], int)
    assert safe["nan"] is None and safe["inf"] is None and safe["nat"] is None
    assert safe["ts"] == "2026-01-02T03:04:05"
    assert safe["nested"] == {"a": [1, 2.5]}
    assert warnings == []


def test_unserialisable_property_is_omitted_with_warning(monkeypatch):
    def fail(value):
        if value == "bad":
            raise RecursionError
        return to_json_safe(value)

    monkeypatch.setattr("app.services.serialization.to_json_safe", fail)
    safe, warnings = sanitize_properties({"good": 1, "bad": "bad"})
    assert safe == {"good": 1}
    assert "bad" in warnings[0]
