import json
import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def to_json_safe(value: Any) -> Any:
    """Convert NumPy/pandas/other values to JSON-native types (NaN and NaT become None)."""
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_json_safe(item) for item in value]
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        value = value.item()
        if value is None:
            return None
    if isinstance(value, bool | str | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def sanitize_properties(properties: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Make feature properties JSON-safe; a bad property is omitted with a warning."""
    safe: dict[str, Any] = {}
    warnings: list[str] = []
    for key, value in properties.items():
        try:
            converted = to_json_safe(value)
            json.dumps(converted, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            warnings.append(f"Property '{key}' was omitted because it could not be serialised.")
            continue
        safe[str(key)] = converted
    return safe, warnings
