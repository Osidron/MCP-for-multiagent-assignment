"""Explicit opt-in live sources check; no mocks. Run from project root."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clinical_mcp.client import run, payload
from clinical_mcp.lifecycle import NetworkServer


def main():
    server = NetworkServer()
    try:
        server.ensure()
        external = run("external")
        print("EXTERNAL DISCOVERY", external["ok"], external.get("error", ""))
        print("TOOLS", [t['name'] for t in external.get('tools', [])])
        called = run("external", "search_articles", {"query": "10.1056/NEJMoa2102953", "max_results": 1})
        print("EXTERNAL CALL", called["ok"], called["duration_ms"], payload(called))
        assert called["ok"] and "34554658" in payload(called).get("pmids", [])
        drug = run("sse", "search_medications", {"query": "Fortamet"})
        print("DRUG SEARCH", json.dumps(payload(drug), ensure_ascii=False))
        data = payload(drug)
        if data.get("daily", {}).get("items"):
            selected = data["daily"]["items"][0]
            result = run("sse", "get_contraindications", {"query": "Fortamet", "source": "DailyMed", "identifier": selected["set_id"]})
            print("DOCUMENTS", json.dumps(payload(result), ensure_ascii=False))
        assert external["ok"], external.get("error")
        assert data["daily"]["state"] == "found"
    finally:
        server.close()


if __name__ == "__main__":
    main()
