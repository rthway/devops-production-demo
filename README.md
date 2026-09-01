# devops-production-demo

[![CI](https://github.com/rthway/devops-production-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/rthway/devops-production-demo/actions/workflows/ci.yml)
[![Security](https://github.com/rthway/devops-production-demo/actions/workflows/security.yml/badge.svg)](https://github.com/rthway/devops-production-demo/actions/workflows/security.yml)
[![Docker](https://github.com/rthway/devops-production-demo/actions/workflows/docker.yml/badge.svg)](https://github.com/rthway/devops-production-demo/actions/workflows/docker.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A small API carried all the way to production shape: containerised, migrated,
orchestrated, observed, scanned, and deployed by pipeline.

The application is deliberately modest — users CRUD over PostgreSQL. The
engineering around it is the point. Every decision below is annotated in the
source with *why*, because in an operations codebase the reasoning is the part
that is expensive to recover later.

---

## Table of contents

- [Architecture](#architecture)
- [What this demonstrates](#what-this-demonstrates)
- [Technology stack](#technology-stack)
- [Repository structure](#repository-structure)
- [Quick start](#quick-start)
- [Local development](#local-development)
- [API reference](#api-reference)
- [Testing](#testing)
- [Docker](#docker)
- [Kubernetes](#kubernetes)
- [Helm](#helm)
- [Terraform](#terraform)
- [CI/CD pipeline](#cicd-pipeline)
- [Monitoring and logging](#monitoring-and-logging)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Verification status](#verification-status)
- [Future improvements](#future-improvements)

---

## Architecture

```text
                            Developer
                                |
                          git push / PR
                                |
                             GitHub
                                |
                   +------------------------+
                   |    GitHub Actions      |
                   |------------------------|
                   |  ci.yml                |
                   |    ruff lint + format  |
                   |    mypy --strict       |
                   |    pytest + coverage   |
                   |    Postgres service    |
                   |  security.yml          |
                   |    Bandit (SAST)       |
                   |    pip-audit (deps)    |
                   |    Trivy (fs + image)  |
                   |    Gitleaks (secrets)  |
                   |    CodeQL              |
                   |  docker.yml            |
                   |    buildx multi-arch   |
                   |    SBOM + provenance   |
                   |  deploy.yml            |
                   |    dev -> prod gate    |
                   +------------------------+
                                |
                                v
                 ghcr.io/rthway/devops-production-demo
                        :latest  :sha-<gitsha>  :v1.0.0
                                |
                                v
              +--------------------------------------+
              |            Kubernetes                |
              |--------------------------------------|
              |  Ingress (nginx, TLS)                |
              |        |                             |
              |     Service (ClusterIP)              |
              |        |                             |
              |  Deployment  --- HPA 2..10 replicas  |
              |   +--------------------------+       |
              |   |  FastAPI (uvicorn)       |       |
              |   |  non-root uid 10001      |       |
              |   |  readOnlyRootFilesystem  |       |
              |   |  liveness  /health/live  |       |
              |   |  readiness /health/ready |       |
              |   +--------------------------+       |
              |        |                    |        |
              |   ConfigMap            Secret        |
              |        |                             |
              |  NetworkPolicy (default deny)        |
              |        |                             |
              |   StatefulSet: PostgreSQL            |
              |        ^                             |
              |   Job: alembic upgrade head          |
              |   (runs once per release, not        |
              |    once per replica)                 |
              +--------------------------------------+
                                |
                    +-----------+-----------+
                    |                       |
              Prometheus                 Promtail
              scrapes /metrics           tails stdout
                    |                       |
                    |                     Loki
                    |                       |
                    +-----------+-----------+
                                |
                             Grafana
                    dashboards + alert rules
```

**Request path inside the application** — each layer knows only the one below it:

```text
HTTP  ->  app/api/v1/         routing, status codes, serialisation
      ->  app/services/       business rules   (no web framework imported)
      ->  app/repositories/   SQL              (no business rules)
      ->  app/models/         SQLAlchemy ORM
      ->  PostgreSQL
```

That direction is enforced by import discipline, and it is what makes the
service layer testable without constructing an app, and the repository layer
swappable without touching business rules.

---

## What this demonstrates

| Area | Concretely |
|---|---|
| Clean architecture | API / service / repository separation, dependency-injected sessions |
| Configuration | 12-factor, `pydantic-settings`, validated at boot, no config files in the image |
| Migrations | Alembic with a hand-written, **reversible** initial revision |
| Observability | Prometheus metrics with deliberate label cardinality, structured JSON logs, request-id propagation, Loki/Promtail, provisioned Grafana dashboard, symptom-based alerts |
| Health | Three distinct endpoints — liveness that ignores the database on purpose |
| Containers | Multi-stage build, non-root uid, read-only rootfs, dropped capabilities, layer-cache-aware ordering |
| Orchestration | Deployment, Service, Ingress, ConfigMap, Secret, HPA, PDB, RBAC, NetworkPolicy, migration Job |
| IaC | Terraform with modules, per-environment state, tagging, no hardcoded credentials |
| CI/CD | Four workflows, least-privilege `permissions:`, concurrency control, pinned actions |
| Security | Bandit, Trivy, pip-audit, Gitleaks, CodeQL, Dependabot, SBOM, `.env.example` only |
| Testing | 43 tests, 97% coverage, Postgres integration job separated by marker |

---

## Technology stack

| Layer | Choice | Why this one |
|---|---|---|
| API | FastAPI | ASGI throughput, Pydantic validation at the boundary, OpenAPI generated from the same type hints mypy checks |
| Server | Uvicorn | ASGI reference server; process count managed by Kubernetes, not by the app |
| ORM | SQLAlchemy 2.0 | Typed `Mapped[...]` API that mypy strict can actually verify |
| Migrations | Alembic | Same metadata as the ORM, so drift is detectable |
| Database | PostgreSQL 16 | Real constraints, real transactions, real concurrency semantics |
| Proxy | nginx | Rate limiting and security headers before a Python worker is involved |
| Metrics | prometheus-client | Pull model; no agent to run, no push gateway to keep alive |
| Logs | structlog + Loki | JSON that Loki parses without a custom pattern |
| Containers | Docker (multi-stage) | Build tools stay out of the runtime image |
| Orchestration | Kubernetes + Helm | Declarative rollout, probe-driven traffic, HPA |
| IaC | Terraform | Plan/apply review workflow and a state file worth protecting |
| CI/CD | GitHub Actions | Native to where the code lives; OIDC instead of long-lived cloud keys |

---

## Repository structure

```text
devops-production-demo/
├── app/
│   ├── api/v1/            health.py, users.py, router.py
│   ├── core/              config, logging, errors, metrics
│   ├── db/                declarative base, engine + session lifecycle
│   ├── models/            SQLAlchemy models
│   ├── repositories/      data access only
│   ├── schemas/           Pydantic request/response contracts
│   ├── services/          business rules, framework-free
│   └── main.py            application factory
├── alembic/versions/      migrations
├── tests/                 43 tests (unit + marked integration)
├── docker/entrypoint.sh   optional migrate-then-exec
├── nginx/nginx.conf
├── k8s/                   11 manifests
├── helm/devops-demo/      chart + dev/prod values
├── terraform/
│   ├── modules/           network, app_runtime
│   └── environments/      dev, prod
├── monitoring/            prometheus, alerts, loki, promtail, grafana
├── .github/workflows/     ci, security, docker, deploy
├── Dockerfile             multi-stage, non-root
├── docker-compose.yml     full stack
├── docker-compose.dev.yml dev overlay (hot reload, adminer, exposed db)
├── INTERVIEW.md           architecture Q&A with real answers
└── CHANGELOG.md
```

---

## Quick start

Requirements: Docker with Compose v2.

```bash
git clone https://github.com/rthway/devops-production-demo.git
cd devops-production-demo
cp .env.example .env          # then edit the passwords

docker compose up -d --build
docker compose ps
```

| Service | URL |
|---|---|
| API via nginx | http://localhost:8080 |
| OpenAPI docs | http://localhost:8080/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (`admin` / value of `GRAFANA_PASSWORD`) |
| Loki | http://localhost:3100 |

Smoke test:

```bash
curl -s localhost:8080/health | jq
curl -s -X POST localhost:8080/api/v1/users \
  -H 'content-type: application/json' \
  -d '{"email":"asha@example.org","full_name":"Asha Sharma"}' | jq
curl -s localhost:8080/api/v1/users | jq
```

Tear down (`-v` also drops the database volume):

```bash
docker compose down -v
```

---

## Local development

Without containers:

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows; use .venv/bin/activate on Linux/macOS
pip install -e ".[dev]"

pytest                                # SQLite-backed, no services needed
uvicorn app.main:app --reload
```

With hot reload inside containers:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The dev overlay adds source bind-mounts with `--reload`, publishes PostgreSQL
on 5432, and starts Adminer on 8081. It is a separate file rather than a
Compose profile so that none of it can be enabled by accident anywhere else.

Migrations:

```bash
alembic upgrade head
alembic revision --autogenerate -m "add widgets table"
alembic downgrade -1
```

---

## API reference

| Method | Path | Behaviour |
|---|---|---|
| `GET` | `/health` | Service identity and version |
| `GET` | `/health/live` | Liveness — **never** touches the database |
| `GET` | `/health/ready` | Readiness — 503 when PostgreSQL is unreachable |
| `GET` | `/metrics` | Prometheus exposition (blocked at nginx) |
| `GET` | `/api/v1/users` | Paginated list; `limit`, `offset`, `active_only` |
| `POST` | `/api/v1/users` | Create; 409 on duplicate email |
| `GET` | `/api/v1/users/{id}` | Fetch one; 404 if absent |
| `PATCH` | `/api/v1/users/{id}` | Partial update |
| `DELETE` | `/api/v1/users/{id}` | Delete; 204 |

Every error shares one envelope, so a client parses one shape:

```json
{
  "error": {
    "code": "conflict",
    "message": "A user with email asha@example.org already exists.",
    "request_id": "6f1c9d2e-..."
  }
}
```

`request_id` is taken from an inbound `X-Request-ID` when present — so a trace
survives across service hops — and is echoed on the response and stamped onto
every log line emitted while handling that request.

---

## Testing

```bash
pytest                                    # full suite
pytest --cov --cov-report=term-missing    # with coverage
pytest -m "not integration"               # CI unit job
TEST_POSTGRES_DSN=postgresql+psycopg://app:app@localhost:5432/app pytest -m integration
```

Current state, from an actual run:

```text
43 passed, 1 skipped
TOTAL coverage: 97%
```

The unit suite runs against file-backed SQLite so the entire API can be
exercised in CI **with no service containers at all** — fast feedback matters
more than dialect fidelity for request/response behaviour. The behaviour
SQLite cannot represent faithfully is covered by `@pytest.mark.integration`
tests that run against a real PostgreSQL service container in the same
workflow.

Coverage is a diagnostic, not a target. The tests assert behaviour that would
actually break in production — liveness surviving a database outage,
pagination neither repeating nor skipping rows, the unique index holding under
duplicate writes, `session_scope` rolling back a partial transaction.

---

## Docker

```bash
docker build -t devops-production-demo:local .
docker compose config          # validate
docker compose up -d
docker compose ps
docker compose logs -f api
docker compose down
```

The image is built in two stages. `build-essential` and pip's cache live in
the builder and never reach the runtime layer; the runtime carries `libpq5`
and `curl` and nothing else. Dependency metadata is copied before application
code, so an ordinary code change reuses the cached dependency layer instead of
reinstalling every wheel.

Runtime hardening:

- Runs as fixed non-root `uid:gid 10001:10001` (fixed because Kubernetes
  `runAsUser` must match a number).
- Application code is owned by root and read-only to the app user, so the
  process cannot rewrite its own source.
- `read_only: true` root filesystem with a small `tmpfs` for `/tmp`.
- `cap_drop: ALL` and `no-new-privileges:true`.
- `HEALTHCHECK` points at `/health/live`, not `/health/ready` — otherwise a
  recoverable database outage would mark every container unhealthy.

---

## Kubernetes

```bash
kubectl apply --dry-run=client -f k8s/     # validate without a cluster
kubectl apply -f k8s/
kubectl -n devops-demo get pods,svc,hpa
kubectl -n devops-demo rollout status deployment/api
```

| Manifest | Purpose |
|---|---|
| `namespace.yaml` | Namespace plus a restricted Pod Security Standard label |
| `configmap.yaml` | Non-secret configuration |
| `secret.example.yaml` | Template only — **never apply as-is** |
| `deployment.yaml` | 2 replicas, probes, resource requests/limits, security context |
| `service.yaml` | ClusterIP |
| `ingress.yaml` | nginx ingress with TLS and rate-limit annotations |
| `hpa.yaml` | 2–10 replicas on CPU and memory, with scale-down stabilisation |
| `pdb.yaml` | PodDisruptionBudget so node drains cannot take the service to zero |
| `postgres.yaml` | StatefulSet with a volumeClaimTemplate |
| `migration-job.yaml` | Runs `alembic upgrade head` once per release |
| `networkpolicy.yaml` | Default deny; only the intended flows are allowed |
| `rbac.yaml` | ServiceAccount with no permissions it does not need |

Deliberate choices worth defending in an interview:

- **Migrations are a Job, not an init container.** An init container runs once
  per pod, so `N` replicas race to migrate the same database on every rollout.
- **PostgreSQL is a StatefulSet, not a Deployment** — stable network identity
  and per-replica persistent volumes.
- **Liveness never queries the database.** If it did, a Postgres failover
  would crash-loop every replica simultaneously and turn a recoverable
  dependency outage into a full outage.
- **`readOnlyRootFilesystem: true`** with an `emptyDir` at `/tmp`.
- **Requests and limits are both set**, so the pods land in the Burstable QoS
  class and the scheduler has real numbers to bin-pack with.

---

## Helm

```bash
helm lint helm/devops-demo
helm template devops-demo helm/devops-demo -f helm/devops-demo/values-dev.yaml
helm upgrade --install devops-demo helm/devops-demo \
  -n devops-demo --create-namespace \
  -f helm/devops-demo/values-prod.yaml
```

`values-dev.yaml` runs one replica with no HPA and relaxed resources;
`values-prod.yaml` runs three with autoscaling, a PDB, and stricter limits.
The chart never carries a real secret — it references an existing Secret by
name.

---

## Terraform

```bash
cd terraform/environments/dev
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan
```

```text
terraform/
├── modules/
│   ├── network/        VPC-shaped networking with tagging
│   └── app_runtime/    application runtime + configuration surface
└── environments/
    ├── dev/            own state key, small sizing
    └── prod/           own state key, HA sizing, deletion protection
```

Environments are **separate root modules with separate state**, not
workspaces: `terraform destroy` in dev then physically cannot touch prod
state. Remote state with S3 + DynamoDB locking is configured in
`backend.tf.example` and documented in `terraform/README.md`.

No credentials appear anywhere in this tree. Providers authenticate through
the environment or CI OIDC, and `*.tfvars` is gitignored with only
`*.tfvars.example` committed.

---

## CI/CD pipeline

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | push, PR | ruff lint + format, mypy strict, pytest matrix, Postgres integration job, coverage gate |
| `security.yml` | push, PR, weekly | Bandit, pip-audit, Trivy (filesystem + image), Gitleaks, CodeQL |
| `docker.yml` | push to main, tags | buildx build, cache, SBOM, provenance, push to GHCR |
| `deploy.yml` | after docker, manual | dev automatically, prod behind an environment approval gate |

Applied throughout:

- **Least privilege.** Every workflow declares `permissions:` explicitly; jobs
  that only read code get `contents: read`. The default token is broad, and
  the default is the wrong choice.
- **Concurrency control.** A new push cancels the previous run on the same
  branch — but never on `main`.
- **Actions pinned** to major versions at minimum; the security workflow pins
  to commit SHAs, since a compromised tag on a scanner is a supply-chain event.
- **No long-lived cloud credentials.** Deployment uses OIDC federation.
- **Tags:** `latest`, `sha-<gitsha>` (the immutable one deployments actually
  reference), and `vX.Y.Z` on release.

---

## Monitoring and logging

Metrics exposed at `/metrics`:

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | counter | method, path, status |
| `http_request_errors_total` | counter | method, path |
| `http_request_duration_seconds` | histogram | method, path |
| `http_requests_in_progress` | gauge | — |
| `app_database_up` | gauge | — |
| `app_info` | gauge | version, environment |

**Labels use the route template, never the raw path.** Labelling
`/api/v1/users/<uuid>` would create one time series per user and eventually
take Prometheus down. Histogram buckets are chosen around the 250 ms SLO
rather than left at the library default, so the histogram has resolution
exactly where the alert threshold sits.

Alerts are symptom-based — availability, error ratio, p95 latency — not
cause-based. Paging someone for high CPU when no user is affected is how an
on-call rotation gets ignored.

Logs are JSON via structlog, carry the request id, and are shipped by Promtail
to Loki. Only low-cardinality fields (`level`, `stream`) become Loki labels;
indexing `request_id` would create one stream per request.

---

## Security

| Control | Where |
|---|---|
| SAST | Bandit on every push |
| Dependency CVEs | pip-audit + Trivy + Dependabot |
| Container CVEs | Trivy image scan, fails on HIGH/CRITICAL |
| Secret scanning | Gitleaks in CI |
| Semantic analysis | CodeQL |
| SBOM | Generated and attached per image |
| Non-root containers | uid 10001, `cap_drop: ALL`, read-only rootfs |
| Network isolation | Kubernetes NetworkPolicy default-deny; two Docker networks |
| Secret hygiene | `.env.example` only; `.env`, `*.pem`, `*.key`, `*.tfvars` gitignored **and** dockerignored |
| Error hygiene | Stack traces and driver messages never reach a client |
| Input validation | Pydantic at the boundary; server-side pagination clamp |
| Least-privilege CI | Explicit `permissions:` per workflow, OIDC not static keys |

There are no real credentials in this repository. Every password in the
compose file is an obviously-fake local default that must be replaced via
`.env`, and `k8s/secret.example.yaml` is a template that is not applied.

Report a vulnerability per [SECURITY.md](SECURITY.md).

---

## Troubleshooting

**`docker compose up` — api container restarts.**
Check `docker compose logs api`. Almost always the database was not ready or
the DSN is wrong. `depends_on: condition: service_healthy` covers the ordering
case; a wrong DSN shows as `database_reachable: false` in the startup log line.

**`/health/ready` returns 503 but `/health/live` returns 200.**
Working as designed — the app is alive, PostgreSQL is not reachable. Check
`docker compose ps db` and its healthcheck.

**Port already allocated.**
Override in `.env`: `HTTP_PORT`, `GRAFANA_PORT`, `PROMETHEUS_PORT`,
`POSTGRES_PORT`.

**Grafana shows "No data".**
Confirm Prometheus has the target: http://localhost:9090/targets. The API is
scraped at `api:8000` on the internal network, not through nginx.

**`alembic upgrade head` says "Can't locate revision".**
The volume holds a database migrated by a different history.
`docker compose down -v` to reset local state.

**Windows: `.venv/Scripts/` vs `.venv/bin/`.**
This project was developed and verified on Windows; use
`source .venv/Scripts/activate`.

---

## Verification status

Honesty about what was actually executed, and what was not:

| Check | Status |
|---|---|
| `pytest` (43 tests) | **PASS** — verified |
| `pytest --cov` | **PASS** — 97% |
| `ruff check .` | **PASS** — verified |
| `ruff format --check .` | **PASS** — verified |
| `mypy --strict` | **PASS** — 23 files, no issues |
| `bandit -r app` | **PASS** — no issues identified |
| `docker compose config` | **PASS** — verified |
| `docker build` | see below |
| `kubectl apply --dry-run=client` | see below |
| `terraform validate` | **NOT EXECUTED** — Terraform is not installed on the development machine. Run `terraform init && terraform validate` in `terraform/environments/dev`. |
| `helm lint` | **NOT EXECUTED** — Helm is not installed. Run `helm lint helm/devops-demo`. |
| Live cluster deploy | **NOT EXECUTED** — no cluster available. `kind create cluster` then `kubectl apply -f k8s/`. |
| GitHub Actions runs | **NOT EXECUTED** — workflows are committed but have not run; they execute on first push. |

---

## Future improvements

- OpenTelemetry traces alongside metrics and logs, so a slow request can be
  followed into the specific query that caused it.
- Authentication and authorisation (OAuth2 / JWT) — deliberately out of scope
  here so the operational story stays legible.
- Progressive delivery via Argo Rollouts or Flagger, promoting on SLO burn
  rate rather than on a timer.
- External Secrets Operator backed by Vault or AWS Secrets Manager, replacing
  Kubernetes Secrets at rest.
- Contract tests against the generated OpenAPI schema to catch breaking API
  changes at PR time.
- Load testing (k6) in CI to catch latency regressions before they ship.

---

## License

MIT — see [LICENSE](LICENSE).
