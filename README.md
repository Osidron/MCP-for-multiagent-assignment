# Лекарства и клинические инструменты через MCP

Практическая работа № 2 курса «Программная инженерия мультиагентных систем клинической медицины». Продолжение первой работы: поиск противопоказаний DailyMed / Drugs@FDA и клинические калькуляторы с тремя настоящими MCP-подключениями. Платный API LLM не требуется. Координатор детерминированный; автономный консилиум LLM не реализуется.

## Запуск одной командой

Python **3.12** (проверено 3.12.14). Первоначальная установка из корня репозитория:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Дальнейший запуск всей системы:

```powershell
.\run.ps1
```

Либо `.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py`. Обычно интерфейс доступен на http://localhost:8501. Остановка: Ctrl+C; управляемый SSE-процесс закрывается через atexit. На Linux используйте `.venv/bin/python`.

Независимый запуск SSE: `python -m clinical_mcp.server --sse --port 8000`. Readiness: `http://127.0.0.1:8000/health`. Подписка `/sse`, POST `/messages/?session_id=...` (завершающий slash соответствует SDK). Stdio: `python -m clinical_mcp.server`; stdout обслуживает только SDK, логи направлены в stderr.

## Архитектура

```mermaid
flowchart LR
  H[Streamlit MCP Host] --> C[Клиентский роутер и инспектор]
  C -->|stdin/stdout| S[Дочерний stdio MCP]
  C -->|HTTP SSE| N[Независимый SSE процесс :8000]
  C -->|TLS Streamable HTTP| E[Удалённый PubMed MCP Anthropic]
  S --> F[Общие формулы и Pydantic]
  N --> F
  N --> D[Координатор лекарственного поиска]
  D --> A[DailyMed]
  D --> B[Drugs@FDA]
```

Host отвечает за формы и сеанс. Client выполняет initialize, notifications/initialized, tools/list с пагинацией и tools/call. Server валидирует параметры и считает кодом. Координатор параллельно ищет кандидатов и сопоставляет состав, форму, путь введения и заявку FDA. Интерфейс не импортирует формулы или лекарственные адаптеры.

| Подключение | Адрес / процесс | Инструменты | Жизненный цикл |
|---|---|---|---|
| stdio | дочерний Python на узле Host | 3 расчёта и каталог | процесс на операцию, закрытие контекстом SDK |
| локальный SSE | 127.0.0.1:8000/sse | 5 расчётов, каталог, 4 лекарственных инструмента | cache_resource, lock, readiness, atexit |
| внешний | https://pubmed.mcp.claude.com/mcp | фактический tools/list, search_articles, get_article_metadata и другие | общий deadline 12 с, TTL 300 с в текущем сеансе |

SSE допускает 2 попытки в общем бюджете. Для внешнего сервиса одна попытка. Локальные расчёты ограничены 15 с, загрузка инструкций — 75 с. Каждый вызов UI проходит MCP. Закрытие сессий предусмотрено SDK; вымышленный JSON-RPC метод shutdown не посылается.

Инспектор прозрачно наблюдает SDK SessionMessage на send/receive, а не собирает запрос из формы. Показывает направление, id, ответ, источник, инструмент и время. Это нормализованная SDK JSON-модель, не побайтовый сетевой дамп. История ограничена 8 операциями по 80 сообщений, только в памяти текущего сеанса; заголовки HTTP не собираются, поля секретов редактируются. Попадание в кэш не создаёт фиктивного нового обмена.

## Методики и контракты

| MCP tool | Метод / результат | Источник |
|---|---|---|
| bmi | фактическая масса кг / рост м² | [CDC](https://www.cdc.gov/growth-chart-training/hcp/using-bmi/calculating-bmi.html) |
| ckd_epi_2021 | CKD-EPI 2021 creatinine, без расового коэффициента, мл/мин/1.73 м² | [Inker 2021](https://doi.org/10.1056/NEJMoa2102953), [NKF implementation](https://www.kidney.org/recommendations-implementing-ckd-epi-2021-race-free-egfr-calculation-guidelines-clinical) |
| cockcroft_gault | Cockcroft–Gault 1976, фактическая масса, мл/мин | [Первичная публикация](https://pubmed.ncbi.nlm.nih.gov/1244564/) |
| cha2ds2_vasc | Lip 2010, 0–9, компоненты C/H/A/D/S/V/Sc | [Первичная публикация](https://pubmed.ncbi.nlm.nih.gov/19762550/) |
| gcs | структурированная E+V+M, 3–15 | [Glasgow assessment aid](https://www.glasgowcomascale.org/downloads/GCS-Assessment-Aid-English.pdf?v=2) |
| list_calculators | схемы, единицы, диапазоны, ограничения, источники | метаданные общих методов |
| search_medications | query ru/en → английский query и выдачи daily/fda | координатор первой работы |
| search_dailymed / search_fda | query → items, state, truncated | [DailyMed API](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm), [FDA API](https://open.fda.gov/apis/drug/drugsfda/) |
| get_contraindications | query/source/identifier/product_name/product_index → документы, версии, ссылки, fda_match | выбранный SPL / FDA PDF |

CKD-EPI: `142 × min(Scr/k,1)^alpha × max(Scr/k,1)^−1.200 × 0.9938^age × 1.012 [female]`; k=0.7/0.9, alpha=−0.241/−0.302. Scr mg/dL; umol/L делится на 88.4. Cockcroft: `(140−age) × weight / (72 × Scr) × 0.85 [female]`. Клиренс не индексирован и не равен СКФ.

Схемы содержат технические защитные диапазоны, не подтверждение клинической применимости. Почечные формулы только ≥18 лет и при стабильном креатинине; ограничения при ОПП, беременности, диализе и необычной мышечной массе. Cockcroft использует фактическую массу; исходная выборка 18–92 лет, ожирение и отёки ограничивают применимость. Для GCS при NT сумму не считают. CHA2DS2-VASc — историческая версия 2010, не CHA2DS2-VA; проценты риска и назначения не выводятся.

Формы строятся из фактического JSON Schema tools/list: number_input, enum, checkbox, текст, JSON для массивов. Обязательные поля помечены *. Измерения изначально пустые; флажки требуют подтверждения, что снятый означает «нет». Sanitizer обрабатывает пробелы, запятую и допустимые типы без подстановки отсутствующих измерений и угадывания единиц. Цветовой шкалы риска нет: нейтральная карточка, компоненты, справочная интерпретация и источник — согласно уточнению пользователя к PDF. Персональных назначений и автоматического разрешения препарата нет.

## Первая работа

`drug_search/` скопирован без изменения исходного репозитория первой работы. Сохранены Bergamot WASM, SPL-коды 34070-3/50570-1, разбор FDA PDF, выбор кандидата до загрузки документа, сопоставление формы/пути/состава/заявки и ссылки на версии. Для FDA повторная выдача сверяется по индексу, заявке и имени; при изменении списка требуется повторный выбор. Ограничения выдачи: 40 SPL и 30 заявок. Историческая инструкция не считается актуальной автоматически. Первый русский запрос скачивает проверенные SHA-256 ресурсы Mozilla в игнорируемую `.bergamot/`.

## Версии SDK и Python

На 22.11.2026 `pip index versions mcp` подтвердил **2.3.0**; установлен официальный `mcp==2.3.0`. Это удовлетворяет обоим указаниям PDF: 2.x и >=1.3.0. Проверены [исходники тега v2.3.0](https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0) и [миграция](https://py.sdk.modelcontextprotocol.io/migration/). Использован Server с on_list_tools/on_call_tool, не устаревшие декораторы FastMCP v1. SseServerTransport поддерживает буквальное SSE-требование. Согласованный протокол в проверках — 2025-11-25; версия SDK и протокола различаются.

Зависимости закреплены в requirements.txt. Полный снимок Windows — requirements-lock-windows.txt (содержит pywin32; не устанавливать целиком на Linux). Для облака переносимый requirements.txt. Выбран Python 3.12, совместимый с исходной первой работой и [Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## Внешний сервис и настройки

[Документация владельца PubMed-коннектора](https://academy.claude.com/tutorials/using-the-pubmed-connector-in-claude) указывает endpoint. initialize/list/search/metadata фактически работали без ключа и оплаты; это наблюдение текущего доступа, не гарантия SLA или будущих условий. Права на статьи определяет издатель. Сервер действительно удалённый, REST-адаптер не выдаётся за внешнюю MCP-интеграцию.

| Env | Значение по умолчанию | Назначение |
|---|---|---|
| MCP_AUTO_START | 1 | 0 для ручного запуска и демонстрации отказа SSE |
| LOCAL_MCP_URL | http://127.0.0.1:8000/sse | сетевой клиент |
| EXTERNAL_MCP_URL | https://pubmed.mcp.claude.com/mcp | удалённый Streamable HTTP |
| EXTERNAL_MCP_TOKEN | отсутствует | необязательный Bearer из env или верхнего уровня Streamlit Secrets |

`.cursor/mcp.json` рассчитан на IDE из корня репозитория и активированную .venv. При другом cwd задайте абсолютный command/cwd по настройкам IDE. Секреты в конфиг не добавлять.

## Проверки и материалы сдачи

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/live_check.py
```

Автономные тесты используют настоящие локальные транспорты. live_check требует Интернет. Регрессионные проверки разбора/сопоставления используют моки источников отдельно от живых соединений. [Отчёт](docs/verification.md), [защита и контрольные вопросы](docs/defense.md), [матрица требований](docs/requirements.md).

## Community Cloud

Новое приложение: этот репозиторий, main, `streamlit_app.py`, Python 3.12. [Процедура](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy). Секреты для проверенного PubMed не требуются. Loopback SSE относится к контейнеру Streamlit: Host запускает там отдельный процесс; адрес компьютера пользователя не используется. Supervisor предотвращает повторный запуск при rerun, проверяет readiness, перезапускает умерший процесс и завершает только свой процесс. Stdio запускается на том же узле через SDK. Порт SSE не публикуется наружу.

Локальные проверки не доказывают возможность запуска на фактическом хостинге. Фактический статус облачной сборки и проверки — в docs/verification.md. Возможны cold start, лимиты ресурсов, ограничения сети FDA и загрузка Bergamot; публичное развёртывание считается проверенным только после проверки сценариев на его URL.
