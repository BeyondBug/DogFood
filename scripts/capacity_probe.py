#!/usr/bin/env python3
"""Read-only local capacity probe for a running BeyondBug portal.

Example: python3 scripts/capacity_probe.py --requests 500 --workers 20
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def one(url: str, timeout: float) -> tuple[int, float, int, str]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read()
            return response.status, time.perf_counter() - started, len(body), ""
    except urllib.error.HTTPError as error:
        return error.code, time.perf_counter() - started, 0, str(error)
    except Exception as error:
        return 0, time.perf_counter() - started, 0, f"{type(error).__name__}: {error}"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8080")
    parser.add_argument("--path", default="/projects?event=evt_01")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    if args.requests < 1 or args.workers < 1:
        parser.error("requests and workers must be positive")
    url = args.base.rstrip("/") + args.path
    preflight = one(url, args.timeout)
    if preflight[0] != 200:
        print(f"Preflight failed: HTTP {preflight[0]} {preflight[3]}", file=sys.stderr)
        raise SystemExit(1)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(one, url, args.timeout) for _ in range(args.requests)]
        results = [future.result() for future in as_completed(futures)]
    elapsed = time.perf_counter() - started
    latencies = [item[1] for item in results]
    statuses: dict[str, int] = {}
    errors: dict[str, int] = {}
    for status, _, _, error in results:
        statuses[str(status)] = statuses.get(str(status), 0) + 1
        if error:
            errors[error] = errors.get(error, 0) + 1
    print(json.dumps({
        "url": url, "requests": args.requests, "workers": args.workers,
        "elapsed_seconds": round(elapsed, 3),
        "requests_per_second": round(args.requests / elapsed, 1),
        "p50_ms": round(percentile(latencies, .50) * 1000, 1),
        "p95_ms": round(percentile(latencies, .95) * 1000, 1),
        "max_ms": round(max(latencies) * 1000, 1),
        "statuses": statuses, "errors": errors,
        "response_bytes": sum(item[2] for item in results),
    }, indent=2))
    if any(status != 200 for status, _, _, _ in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
