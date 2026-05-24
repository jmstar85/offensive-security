"""dns_resolver entrypoint — emit A/AAAA/MX/TXT records as JSONL."""
from __future__ import annotations

import argparse
import json
import sys

import dns.resolver  # type: ignore


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    args = ap.parse_args()

    resolver = dns.resolver.Resolver()
    for rdtype in ("A", "AAAA", "MX", "TXT", "NS", "SOA", "CAA"):
        try:
            answers = resolver.resolve(args.domain, rdtype, raise_on_no_answer=False)
        except dns.resolver.NXDOMAIN:
            print(json.dumps({"domain": args.domain, "error": "nxdomain"}), flush=True)
            return 0
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"domain": args.domain, "type": rdtype, "error": str(exc)}), file=sys.stderr)
            continue
        for r in answers:
            print(json.dumps({"domain": args.domain, "type": rdtype, "value": r.to_text()}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
