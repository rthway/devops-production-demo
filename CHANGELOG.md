# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-09-01

First release. A production-shaped FastAPI service with the full operational
surface around it.

### Added

**Application**
- FastAPI service with users CRUD over PostgreSQL, clean layering
  (api / services / repositories / models).
- Configuration via `pydantic-settings`, validated at boot, 12-factor.
- Alembic migrations with a hand-written, reversible initial revision.
- Structured JSON logging via structlog with request-id propagation, accepting
  an inbound `X-Request-ID` so traces survive across service hops.
- A single error envelope for the whole API.
- Three health endpoints: `/health`, `/health/live`, `/health/ready`.

**Containers**
- Multi-stage Dockerfile: non-root uid 10001, read-only root filesystem,
  dropped capabilities, cache-aware layer ordering. 349 MB.
- Compose stack with nginx, PostgreSQL, Prometheus, Grafana, Loki and Promtail.
- Development overlay with hot reload, exposed database and Adminer.

**Kubernetes**
- 16 objects: Deployment, Service, Ingress, ConfigMap, Secret template, HPA,
  PDB, RBAC, NetworkPolicy, PostgreSQL StatefulSet and a migration Job.
- Namespace enforcing the `restricted` Pod Security Standard.

**Helm**
- Chart with dev and prod value sets, config checksum annotation, and a
  pre-upgrade migration hook.

**Terraform**
- `network` and `app_runtime` modules; dev and prod as separate root modules
  with separate state.
- ALB, ECS Fargate, RDS PostgreSQL, Secrets Manager, tiered security groups.

**CI/CD**
- Four workflows, 15 jobs: CI, security, docker publish, deploy.
- Coverage floor, migration reversibility and model-drift checks.
- SBOM and provenance attestation on published images.

**Observability**
- Prometheus metrics with deliberate label cardinality control.
- Four symptom-based alert rules.
- Provisioned Grafana dashboard.

### Fixed

- Validation errors returned HTTP 500 instead of 422. `RequestValidationError.errors()`
  embeds a non-serialisable exception object under `ctx` when a custom
  validator raises; responses now expose only `loc`, `msg` and `type`, which
  also stops the rejected input being echoed back.
- Every metric series was labelled `path="__unmatched__"`. The route template
  was resolved before `call_next`, but Starlette only populates
  `scope["route"]` during routing. The template is now resolved after routing
  and rebuilt from the concrete path so a prefixed router keeps its full path.
- Promtail failed to start (`pipeline stage must contain only one key`) and,
  once started, shipped every container on the host including months-old logs
  that Loki rejected. Discovery is now scoped to this Compose project by label.

### Security

- Bandit, Trivy, pip-audit, Gitleaks, CodeQL and Dependabot wired into CI.
- OIDC federation for cloud deploys; no long-lived cloud credentials.
- Deploy jobs refuse a mutable `latest` tag.
- Security scanner actions pinned to commit SHAs.

[1.0.0]: https://github.com/rthway/devops-production-demo/releases/tag/v1.0.0
