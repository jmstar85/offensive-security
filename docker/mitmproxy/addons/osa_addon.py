"""mitmproxy addon — emit request/response events as JSON lines on stdout.

Each flow event is a single JSON object written to stdout so the
MitmProxyAdapter can consume it as a structured event stream.
Authorization and Cookie headers are redacted before emission.
"""
import json
import sys

_REDACT = frozenset({"authorization", "cookie"})


def _scrub(headers) -> dict:
    return {
        k: ("[REDACTED]" if k.lower() in _REDACT else v)
        for k, v in headers.items()
    }


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def request(flow):
    _emit({
        "event": "request",
        "flow_id": flow.id,
        "url": flow.request.pretty_url,
        "method": flow.request.method,
        "headers": _scrub(dict(flow.request.headers)),
    })


def response(flow):
    _emit({
        "event": "response",
        "flow_id": flow.id,
        "url": flow.request.pretty_url,
        "status_code": flow.response.status_code,
        "headers": _scrub(dict(flow.response.headers)),
    })
