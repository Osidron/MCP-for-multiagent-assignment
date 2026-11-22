"""Deterministic methods; no model inference or prescribing decisions."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class BMI(Input):
    weight_kg: float = Field(ge=20, le=400, description="Фактическая масса, кг")
    height_cm: float = Field(ge=100, le=250, description="Рост, см")


class Renal(Input):
    age: int = Field(ge=18, le=120, description="Полных лет; только взрослые")
    sex: Literal["male", "female"] = Field(description="Пол в исходной формуле: male / female")
    creatinine: float = Field(ge=0.1, le=2652, description="Креатинин сыворотки: 0.1–30 mg/dL или 8.84–2652 umol/L; единицы выберите явно")
    creatinine_unit: Literal["mg/dL", "umol/L"] = Field(description="Единицы креатинина; 1 mg/dL = 88.4 umol/L")


class Cockcroft(Renal):
    weight_kg: float = Field(ge=20, le=400, description="Фактическая измеренная масса, кг; не идеальная/скорректированная")


class CHA(Input):
    age: int = Field(ge=18, le=120, description="Полных лет")
    female: bool = Field(description="Женский пол")
    heart_failure: bool = Field(description="Сердечная недостаточность / дисфункция ЛЖ")
    hypertension: bool = Field(description="Артериальная гипертензия")
    diabetes: bool = Field(description="Сахарный диабет")
    stroke_tia: bool = Field(description="Инсульт, ТИА или тромбоэмболия в анамнезе")
    vascular_disease: bool = Field(description="Сосудистое заболевание: ИМ, периферические артерии, бляшка аорты")


class GCS(Input):
    eyes: Literal[1, 2, 3, 4] = Field(description="E: 1 нет; 2 на давление; 3 на звук; 4 спонтанно")
    verbal: Literal[1, 2, 3, 4, 5] = Field(description="V: 1 нет; 2 звуки; 3 слова; 4 спутанная; 5 ориентирован")
    motor: Literal[1, 2, 3, 4, 5, 6] = Field(description="M: 1 нет; 2 разгибание; 3 патологическое сгибание; 4 нормальное сгибание; 5 локализация; 6 команды")


METHODS = {
    "bmi": (BMI, "ИМТ BMI", "Антропометрия", "https://www.cdc.gov/growth-chart-training/hcp/using-bmi/calculating-bmi.html",
            "Масса / рост². Для взрослых; при беременности, отёках и выраженной мышечной массе интерпретация ограничена. Диапазоны ввода — технические ограничения приложения."),
    "ckd_epi_2021": (Renal, "СКФ CKD-EPI 2021 (креатинин)", "Нефрология", "https://doi.org/10.1056/NEJMoa2102953",
                     "Inker 2021, без расового коэффициента. Только ≥18 лет, стабильный IDMS-креатинин; не при ОПП, беременности или диализе. Один результат не устанавливает ХБП."),
    "cockcroft_gault": (Cockcroft, "Клиренс Cockcroft–Gault 1976", "Нефрология", "https://pubmed.ncbi.nlm.nih.gov/1244564/",
                        "Фактическая масса тела. Не индексирован на 1.73 м²; не равен СКФ. Исходная выборка 18–92 лет; вне неё и при ожирении/отёках применимость ограничена. Не при нестабильном креатинине."),
    "cha2ds2_vasc": (CHA, "CHA₂DS₂-VASc CHA2DS2-VASc", "Кардиология", "https://pubmed.ncbi.nlm.nih.gov/19762550/",
                     "Lip 2010, для взрослых с фибрилляцией предсердий; историческая шкала, не CHA2DS2-VA. Балл не является назначением антикоагулянта; абсолютный риск зависит от популяции."),
    "gcs": (GCS, "Шкала комы Глазго GCS", "Реанимация", "https://www.glasgowcomascale.org/downloads/GCS-Assessment-Aid-English.pdf?v=2",
            "Структурированная E/V/M, 3–15. При интубации, седации и невозможности оценки компонента отмечают NT и не вычисляют сумму; не вводите фиктивный балл 1."),
}


def calculate(name: str, args: dict) -> dict:
    model, title, group, source, limits = METHODS[name]
    x = model.model_validate(args)
    components = x.model_dump()
    interpretation = ""
    if name == "bmi":
        value, unit = x.weight_kg / (x.height_cm / 100) ** 2, "кг/м²"
        interpretation = "Отношение массы к квадрату роста; не прямая оценка жировой массы."
    elif name in {"ckd_epi_2021", "cockcroft_gault"}:
        scr = x.creatinine / 88.4 if x.creatinine_unit == "umol/L" else x.creatinine
        if not 0.1 <= scr <= 30:
            raise ValueError("Креатинин вне поддерживаемого диапазона 0.1–30 mg/dL (8.84–2652 umol/L). Проверьте единицы.")
        components["creatinine_mg_dl"] = scr
        if name == "ckd_epi_2021":
            k, alpha = (0.7, -0.241) if x.sex == "female" else (0.9, -0.302)
            components.update(k=k, alpha=alpha)
            value = 142 * min(scr / k, 1) ** alpha * max(scr / k, 1) ** -1.2 * 0.9938 ** x.age * (1.012 if x.sex == "female" else 1)
            unit = "мл/мин/1.73 м²"
        else:
            value = (140 - x.age) * x.weight_kg / (72 * scr) * (0.85 if x.sex == "female" else 1)
            unit = "мл/мин"
            components["weight_basis"] = "actual (фактическая)"
        interpretation = "Оценка функции почек; не устанавливает диагноз и не определяет допустимость препарата."
    elif name == "cha2ds2_vasc":
        components = {"C": int(x.heart_failure), "H": int(x.hypertension), "A2/A": 2 if x.age >= 75 else int(x.age >= 65),
                      "D": int(x.diabetes), "S2": 2 * int(x.stroke_tia), "V": int(x.vascular_disease), "Sc": int(x.female)}
        value, unit = sum(components.values()), "баллов (0–9)"
        interpretation = "Более высокий балл связан с более высокой частотой тромбоэмболий в исходной когорте. Процент риска и лечение здесь не выводятся."
    else:
        value, unit = x.eyes + x.verbal + x.motor, "баллов (3–15)"
        interpretation = "Меньший балл отражает более выраженное нарушение сознания; оцените E, V и M отдельно и учитывайте помехи обследованию."
    return {"value": round(value, 2), "unit": unit, "method": title, "group": group, "components": components,
            "limitations": limits, "interpretation": interpretation, "source": source}


def catalog() -> dict:
    return {name: {"name": title, "group": group, "source": source, "limitations": limits,
                   "parameters": model.model_json_schema()} for name, (model, title, group, source, limits) in METHODS.items()}
