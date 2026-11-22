"""Streamlit MCP Host. Every instrument operation crosses MCP."""
import json
import os
import re
import time
import streamlit as st
from clinical_mcp.client import run, payload, EXTERNAL_URL
from clinical_mcp.lifecycle import NetworkServer
from clinical_mcp.sanitizer import sanitize

st.set_page_config(page_title="Клинические инструменты · MCP", page_icon="⚕", layout="wide")


@st.cache_resource
def supervisor():
    return NetworkServer()


def remember(result):
    history = st.session_state.setdefault("rpc_history", [])
    history.append(result)
    del history[:-8]
    return result


def invoke(source, tool=None, arguments=None):
    with st.spinner("Соединяемся с MCP…" if not tool else "Вызываем инструмент через MCP…"):
        if source == "external":
            # Cache only this browser session; no persistent storage of clinical input.
            cache = st.session_state.setdefault("external_cache", {})
            key = json.dumps([tool, arguments, os.getenv("EXTERNAL_MCP_URL", EXTERNAL_URL)], sort_keys=True)
            if key in cache and time.monotonic() - cache[key][0] < 300:
                st.caption("Результат из кэша сеанса (TTL 5 минут). Нового протокольного обмена не было.")
                return cache[key][1]
            result = remember(run(source, tool, arguments))
            if result["ok"] and not result.get("response", {}).get("isError"):
                cache[key] = (time.monotonic(), result)
                if len(cache) > 20:
                    del cache[next(iter(cache))]
        else:
            result = remember(run(source, tool, arguments))
    if not result["ok"]:
        st.error(result["error"]["message"])
    return result


def show_result(result):
    if not result.get("ok"):
        return
    data = payload(result)
    if result.get("response", {}).get("isError"):
        st.error(data.get("error", {}).get("message", "Ошибка инструмента"))
        st.json(data)
        return
    if isinstance(data, dict) and "value" in data:
        st.metric(data["method"], f'{data["value"]} {data["unit"]}')
        st.write(data["interpretation"])
        st.info(data["limitations"])
        st.json(data["components"])
        st.link_button("Первоисточник методики", data["source"])
    else:
        st.json(data)
        # External content remains untrusted data. Only expose actual HTTPS source links.
        if isinstance(data, dict):
            for pmid in data.get("pmids", [])[:15]:
                if str(pmid).isdigit():
                    st.link_button("PubMed · " + str(pmid), "https://pubmed.ncbi.nlm.nih.gov/" + str(pmid) + "/")
            for article in data.get("articles", [])[:15]:
                ids = article.get("identifiers", {})
                if str(ids.get("pmid", "")).isdigit():
                    st.link_button("PubMed · " + ids["pmid"], "https://pubmed.ncbi.nlm.nih.gov/" + ids["pmid"] + "/")
                if ids.get("doi"):
                    st.link_button("DOI · " + ids["doi"], "https://doi.org/" + ids["doi"])
        text = json.dumps(data, ensure_ascii=False)
        for url in list(dict.fromkeys(re.findall(r'https://[^\s"<>\\]+', text)))[:15]:
            st.link_button("Открыть источник", url.rstrip(".,)"))


def dynamic_form(tool):
    schema = tool["inputSchema"]
    values = {}
    with st.form("tool_" + tool["name"]):
        for key, spec in schema.get("properties", {}).items():
            description = spec.get("description", spec.get("title", key))
            label = description if len(description) < 180 else key + " — " + description.splitlines()[0][:100]
            if key in schema.get("required", []):
                label += " *"
            options = spec.get("enum")
            kind = spec.get("type")
            if options:
                values[key] = st.selectbox(label, options, index=None, key="arg_" + tool["name"] + key)
            elif kind == "boolean":
                values[key] = st.checkbox(label, value=False, key="arg_" + tool["name"] + key)
            elif kind in {"number", "integer"}:
                values[key] = st.number_input(label, value=None, step=1 if kind == "integer" else 0.1,
                    key="arg_" + tool["name"] + key)
                st.caption(f"Допустимо: {spec.get('minimum', '−∞')} … {spec.get('maximum', '∞')}")
            else:
                values[key] = st.text_area(label, key="arg_" + tool["name"] + key) if kind in {"object", "array"} else st.text_input(label, key="arg_" + tool["name"] + key)
        confirm = st.checkbox("Подтверждаю введённые данные, единицы и значения всех флажков (снятый = нет)")
        submitted = st.form_submit_button("Выполнить", type="primary")
    if submitted:
        if not confirm:
            st.warning("Проверьте данные и подтвердите их перед вызовом.")
            return None
        for key, spec in schema.get("properties", {}).items():
            if spec.get("type") in {"object", "array"} and values.get(key):
                values[key] = json.loads(values[key])
        return sanitize(values, schema)
    return None


st.title("Клинические инструменты MCP")
st.caption("Практическая работа № 2 · MCP Host / Client / Server · без платного LLM API")
st.info("Учебный справочник. Расчёты и публикации не заменяют клиническую оценку и не формируют назначения.")
try:
    if os.getenv("MCP_AUTO_START", "1") == "1":
        supervisor().ensure()
except Exception as exc:
    st.error(str(exc))

st.subheader("Клинические инструменты")
source = st.radio("Источник MCP", ["stdio", "sse", "external"], horizontal=True,
    format_func=lambda x: {"stdio": "Локальный stdio", "sse": "Локальный сетевой SSE", "external": "Внешний PubMed MCP"}[x])
st.caption({"stdio": "Дочерний процесс Python", "sse": "127.0.0.1:8000/sse · отдельный процесс", "external": os.getenv("EXTERNAL_MCP_URL", EXTERNAL_URL)}[source])
if st.button("Обнаружить инструменты (tools/list)"):
    st.session_state["discovery_" + source] = invoke(source)
discovery = st.session_state.get("discovery_" + source, {})
if discovery.get("ok"):
    st.caption(f"Подключено · MCP {discovery['protocol']} · {len(discovery['tools'])} инструментов")
    tools = discovery["tools"]
    def tool_group(t):
        return "Доказательная медицина" if source == "external" else t.get("description", "").split(" · ")[0]
    def tool_label(t):
        return t.get("annotations", {}).get("title", t["name"]) if source == "external" else t.get("description", t["name"]).split(". ")[0]
    groups = sorted({tool_group(t) for t in tools})
    group = st.selectbox("Направление", ["Все", *groups])
    term = st.text_input("Поиск по русскому или английскому названию", placeholder="ИМТ, BMI, СКФ, GCS, PubMed")
    filtered = [t for t in tools if (group == "Все" or tool_group(t) == group) and term.casefold() in (t["name"] + " " + t.get("description", "") + (" публикации поиск статьи пабмед" if source == "external" else "")).casefold()]
    if filtered:
        name = st.selectbox("Инструмент (подсказки при вводе)", [t["name"] for t in filtered], format_func=lambda n: next(tool_label(t) for t in filtered if t["name"] == n))
        tool = next(t for t in filtered if t["name"] == name)
        st.write(tool.get("description", name).split("\n\n")[0])
        try:
            args = dynamic_form(tool)
            if args is not None:
                st.session_state["last_calculation"] = invoke(source, name, args)
        except (ValueError, TypeError) as exc:
            st.error("Ошибка ввода: " + str(exc))
    else:
        st.info("Нет инструментов по этому фильтру.")
if "last_calculation" in st.session_state:
    show_result(st.session_state["last_calculation"])

with st.expander("Инспектор фактического JSON-RPC · последние 8 операций"):
    st.caption("Только память текущего сеанса. Направления sent/received; поля message взяты на границе транспорта SDK. Клинические данные не записываются на диск.")
    if st.button("Очистить историю и кэш сеанса"):
        st.session_state["rpc_history"] = []
        st.session_state["external_cache"] = {}
    for operation in reversed(st.session_state.get("rpc_history", [])):
        st.write(f"{operation['source']} · {operation.get('tool') or 'tools/list'} · {operation['duration_ms']} мс")
        st.json(operation["history"])
