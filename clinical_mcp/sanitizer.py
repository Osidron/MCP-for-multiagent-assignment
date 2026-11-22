"""Conservative conversion: no guessed measurements or units."""
import math
import re


def sanitize(values: dict, schema: dict) -> dict:
    out = {}
    properties = schema.get("properties", {})
    for name, value in values.items():
        spec = properties.get(name, {})
        if isinstance(value, str):
            value = " ".join(value.split())
            if spec.get("type") in {"number", "integer"}:
                raw = value.replace(",", ".")
                if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", raw):
                    raise ValueError(f"{name}: введите число без единиц; единицы указаны отдельно.")
                value = float(raw)
                if not math.isfinite(value):
                    raise ValueError(f"{name}: число должно быть конечным")
                if spec["type"] == "integer":
                    if not value.is_integer():
                        raise ValueError(f"{name}: требуется целое число")
                    value = int(value)
            elif spec.get("type") == "boolean":
                if value.casefold() not in {"true", "false", "да", "нет"}:
                    raise ValueError(f"{name}: требуется да/нет")
                value = value.casefold() in {"true", "да"}
        if value is None or value == "":
            if name in schema.get("required", []):
                raise ValueError(f"{name}: обязательное поле не заполнено")
            continue
        out[name] = value
    for name in schema.get("required", []):
        if name not in out:
            raise ValueError(f"{name}: обязательное поле не заполнено")
    return out
