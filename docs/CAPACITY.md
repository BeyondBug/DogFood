# Local capacity check

BeyondBug currently runs one Uvicorn process and one SQLite database on a
single host. This is a deliberate deployment limit. A load balancer in front
of multiple copies would not remove SQLite write contention or give the copies
safe, shared operational state.

## Reproducible read probe

On 27 September 2026, against a local Compose portal seeded with the DOGFOOD
fixture event, we requested its public 41-project gallery using the standard
library probe:

```sh
python3 scripts/capacity_probe.py --requests 500 --workers 20
python3 scripts/capacity_probe.py --requests 1000 --workers 50
```

| Requests | Workers | HTTP 200 | Throughput | p50 | p95 | Maximum |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 20 | 500 | 359.5 requests/s | 55.1 ms | 63.4 ms | 70.5 ms |
| 1,000 | 50 | 1,000 | 336.6 requests/s | 145.5 ms | 176.2 ms | 221.9 ms |

These are short runs on one development laptop, one route, and a warm local
database. They are **not** a simultaneous-user rating or a production service
level. The probe exits nonzero on a failed preflight or any non-200 response;
it prints status and error counts. An earlier attempt found that the portal
container was stopped; its connection failures were discarded, not counted as
throughput.

## Capacity boundary

The gallery is mainly a read workload. This probe does not measure concurrent
registration, score submission, voting, backups, or long-running events. The
SQLite WAL and 10-second busy timeout allow readers beside one writer, but a
burst of writes can still queue or time out. Monitor p95 latency, 5xx and 429
rates, database lock time, CPU, memory, and disk space on the actual host.

If measured write load exceeds the single-host design, move transactional
state to a shared database, move rate-limit counters and background jobs to
shared services, then test multiple application instances behind a reverse
proxy. Such a deployment is outside this release; `docker compose up` remains
the supported offline setup.
