import socket
from clinical_mcp.client import run, payload
from clinical_mcp.lifecycle import NetworkServer


def assert_trace(result, tool):
    assert result["ok"], result.get("error")
    packets = result["history"]
    request = next(p["message"] for p in packets if p["direction"] == "sent" and p["message"].get("method") == "tools/call")
    response = next(p["message"] for p in packets if p["direction"] == "received" and p["message"].get("id") == request["id"])
    assert request["params"]["name"] == tool
    assert response["result"]["content"] == result["response"]["content"]
    assert any(p["message"].get("method") == "initialize" for p in packets)
    assert any(p["message"].get("method") == "tools/list" for p in packets)


def test_real_stdio_success_error_and_close():
    result = run("stdio", "bmi", dict(weight_kg=70.0, height_cm=175.0))
    assert_trace(result, "bmi")
    assert payload(result)["value"] == 22.86
    failed = run("stdio", "bmi", dict(weight_kg=-5.0, height_cm=0.0))
    assert_trace(failed, "bmi")
    assert failed["response"]["isError"]
    assert payload(failed)["error"]["code"] == "INVALID_INPUT"


def test_real_sse_and_refused_connection():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = NetworkServer(port)
    try:
        server.ensure()
        result = run("sse", "gcs", dict(eyes=4, verbal=5, motor=6), f"http://127.0.0.1:{port}/sse")
        assert_trace(result, "gcs")
        assert payload(result)["value"] == 15
        assert len(result["tools"]) >= 10
    finally:
        process = server.process
        server.close()
    assert process.poll() is not None
    failed = run("sse", url=f"http://127.0.0.1:{port}/sse")
    assert not failed["ok"]
    assert failed["duration_ms"] < 15000
