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
        for source, name, args, expected in [
            ("stdio", "bmi", {"weight_kg":70.0,"height_cm":175.0},22.86),
            ("sse", "gcs", {"eyes":4,"verbal":5,"motor":6},15),
        ]:
            result = run(source, name, args)
            print(source, result["ok"], payload(result))
            assert result["ok"] and payload(result).get("value") == expected
        assert external["ok"], external.get("error")
    finally:
        server.close()


if __name__ == "__main__":
    main()
