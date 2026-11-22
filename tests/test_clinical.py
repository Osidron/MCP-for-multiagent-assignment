import math
import pytest
from pydantic import ValidationError
from clinical_mcp.calculators import calculate, BMI, catalog
from clinical_mcp.sanitizer import sanitize


def renal(**kwargs):
    return dict(age=60, sex="male", creatinine=1.0, creatinine_unit="mg/dL", **kwargs)


def test_formula_reference_and_independent_cases():
    # CDC metric worked example: 16.6 kg / 99.1 cm -> 16.9.
    # Adult UI range excludes this child: test arithmetic independently, not applicability.
    assert round(16.6 / .991**2, 1) == 16.9
    assert calculate("bmi", dict(weight_kg=70.0, height_cm=175.0))["value"] == 22.86
    # NKF implementation knot examples: Scr=k; all min/max powers equal 1.
    for sex, scr, factor in [("male", .9, 1), ("female", .7, 1.012)]:
        args = dict(age=18, sex=sex, creatinine=scr, creatinine_unit="mg/dL")
        assert calculate("ckd_epi_2021", args)["value"] == round(142 * .9938**18 * factor, 2)
    assert calculate("cockcroft_gault", renal(weight_kg=72.0))["value"] == 80
    assert calculate("cockcroft_gault", {**renal(weight_kg=72.0), "sex": "female"})["value"] == 68


def test_units_and_limits():
    for name in ["ckd_epi_2021", "cockcroft_gault"]:
        a = renal(**({"weight_kg": 72.0} if name == "cockcroft_gault" else {}))
        assert calculate(name, a)["value"] == calculate(name, {**a, "creatinine": 88.4, "creatinine_unit": "umol/L"})["value"]
        for bad in [{"age": 17}, {"age": 120.1}, {"creatinine": 0.0}, {"creatinine": math.nan}, {"creatinine_unit": "unknown"}, {"sex": "unknown"}]:
            with pytest.raises(ValueError):
                calculate(name, a | bad)
    with pytest.raises(ValidationError):
        calculate("bmi", dict(weight_kg="70", height_cm=175.0))


def test_scales_components_boundaries():
    args = dict(age=74, female=False, heart_failure=False, hypertension=False, diabetes=False, stroke_tia=False, vascular_disease=False)
    assert calculate("cha2ds2_vasc", args)["value"] == 1
    assert calculate("cha2ds2_vasc", args | {"age": 75})["value"] == 2
    maximal = {k: True for k in args if k != "age"} | {"age": 80}
    assert calculate("cha2ds2_vasc", maximal)["value"] == 9
    assert calculate("gcs", dict(eyes=4, verbal=5, motor=6))["value"] == 15
    assert calculate("gcs", dict(eyes=1, verbal=1, motor=1))["value"] == 3
    with pytest.raises(ValueError):
        calculate("gcs", dict(eyes=0, verbal=5, motor=6))
    assert len(catalog()) == 5


def test_sanitizer_never_guesses():
    schema = BMI.model_json_schema()
    assert sanitize(dict(weight_kg=" 70,5 ", height_cm="175"), schema) == dict(weight_kg=70.5, height_cm=175.0)
    for values in [{"weight_kg": None}, {"weight_kg": "70 kg", "height_cm": "175"}]:
        with pytest.raises(ValueError):
            sanitize(values, schema)
