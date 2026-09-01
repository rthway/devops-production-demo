# Interview notes

Answers grounded in this repository. Where a claim was measured, the measurement
is quoted. Where something was not verified, it says so — a confident answer
about something you never ran is the fastest way to lose a technical interview.

---

## Architecture

### Why this architecture?

Four layers, each importing only the one below it:

```text
api/ -> services/ -> repositories/ -> models/
```

The payoff is concrete, not aesthetic. `app/services/user.py` imports no web
framework, so `TestService` in `tests/test_database.py` constructs it with a
session and tests business rules with no app, no client, no HTTP. The
repository owns SQL and nothing else, so the same service code runs against
PostgreSQL in production and SQLite in the unit suite — which is why the full
API test suite runs in CI with **no service containers at all** and finishes in
about 1.4 seconds.

The cost is more files for a CRUD app. I would not build this for a throwaway
script. It earns its keep the moment a second developer needs to change a
business rule without understanding the ORM.

### Why FastAPI?

- Validation happens at the boundary. `UserCreate` rejects a malformed email
  before any application code runs.
- The OpenAPI schema is generated from the same type hints `mypy --strict`
  checks, so documentation cannot drift from the code.
- ASGI, so I/O-bound request handling scales without a thread per request.

Django would have brought an ORM, admin and auth I do not need here; Flask
would have meant assembling validation and schema generation by hand.

### Why PostgreSQL?

The application depends on guarantees, not just storage. The duplicate-email
rule is enforced by a **unique index**, not by the application check in
`UserService.create` — that check only produces a friendlier message. Two
concurrent POSTs both pass it; only the index stops them. Add real
transactions, `ON CONFLICT`, and mature operational tooling, and there is no
argument for anything else at this scale.

### Why Docker?

So the artifact that passed CI is bit-for-bit the artifact that runs. Note that
the same image runs under Compose, under Kubernetes, and as an ECS Fargate task
definition in `terraform/modules/app_runtime` — one build, three runtimes.

### Why Kubernetes — and when would you not use it?

Kubernetes buys probe-driven traffic management, declarative rollout with
automatic rollback, and horizontal autoscaling. For this service I would
honestly reach for ECS Fargate first — which is exactly why the Terraform
targets Fargate rather than EKS. A single service does not justify a control
plane and the operational surface that comes with it. Kubernetes earns its
complexity at roughly a dozen services, or when you need workload primitives
(DaemonSets, operators, CRDs) that a task scheduler does not have.

---

## DevOps

### Explain your CI/CD pipeline.

Four workflows, 15 jobs.

**ci.yml** — `static-analysis` (ruff lint, ruff format, mypy strict) runs first
because a typo should not wait behind a test matrix. `unit-tests` runs on 3.11
and 3.12 with `fail-fast: false`, then enforces an 85% coverage **floor** —
measured at 96.83% today. `integration-tests` brings up a real PostgreSQL
service container and does three things beyond running tests: applies
migrations from empty, proves them reversible (`downgrade base` then `upgrade
head`), and checks for **model/migration drift** by running autogenerate and
failing if it produces any operations. `validate-manifests` runs hadolint,
`helm lint`, `kubeconform` against both the raw manifests and the rendered
chart, and `terraform fmt -check` + `validate` for both environments.
`ci-passed` aggregates everything into one required status check, so adding a
job does not mean editing the branch protection rule.

**security.yml** — Bandit, pip-audit, Trivy filesystem, Trivy image, Gitleaks
with `fetch-depth: 0`, and CodeQL for both `python` and `actions`. It also runs
weekly on a schedule, because a dependency that was clean at merge time does
not stay clean.

**docker.yml** — buildx for amd64 and arm64, GHA layer cache, SBOM and
provenance attestation, push to GHCR, then a scan of the published image **by
digest** rather than by tag, so there is no window where the tag could move
between publish and scan.

**deploy.yml** — dev automatically on a green build of main, production behind
a GitHub environment with required reviewers.

Cross-cutting: every workflow declares `permissions:` explicitly starting from
`contents: read`; concurrency cancels superseded runs except on main and except
during a publish; the Trivy action is pinned to a **commit SHA** because a
moved tag on a security scanner is a supply-chain event.

### How would you perform a rollback?

Three layers, and they are not equally easy.

**Application:** `helm rollback devops-demo <revision>`. The deploy job
captures the current revision *before* upgrading (`steps.current`), because
working out what to roll back to during an incident is exactly the wrong time
to run `helm history`. `--atomic` also rolls back automatically if the release
does not become healthy inside the timeout.

**Image:** every deploy references an immutable `sha-<gitsha>` tag. Both deploy
jobs actively **refuse** to deploy `latest` — rolling back to a mutable tag is
meaningless because you cannot know what it points at.

**Database: this is the one that does not roll back.** Helm rollback reverts
pods, not schema. So migrations must be backwards compatible with the currently
deployed code. Dropping a column is a three-deploy sequence: stop writing it,
deploy; stop reading it, deploy; drop it, deploy. `alembic downgrade` exists
and is tested in CI, but downgrading a migration that dropped data does not
bring the data back. That is why the PR template has an explicit "is the
migration backwards compatible" checkbox.

### How would you scale this?

Horizontally first. The application is stateless — no session state, no local
files, `readOnlyRootFilesystem: true` makes that structural rather than
aspirational — so the HPA takes it from 2 to 10 replicas on CPU and memory.

The database is the real ceiling. In order: connection pooling is already
configured (`pool_size`, `max_overflow`, `pool_pre_ping`); then pgbouncer,
because Postgres connections are processes and a few hundred is a lot; then
read replicas for read-heavy traffic; then caching; then partitioning or
sharding, which I would defer as long as possible.

I would not guess at any of this. `http_request_duration_seconds` and
`http_requests_in_progress` are the signals — a rising floor on in-flight
requests means workers are not keeping up, which is a different fix from rising
p95 with flat concurrency.

### How would you handle secrets?

Layered, and no layer keeps a secret in git:

- **Local:** `.env`, gitignored *and* dockerignored. Only `.env.example` is
  committed, with `CHANGE-ME` placeholders.
- **CI:** GitHub secrets; cloud access via **OIDC federation**, so no long-lived
  AWS key exists to leak. Gitleaks scans full history on every push.
- **Kubernetes:** `secret.example.yaml` is a template that is never applied.
  The chart references an existing Secret by name and never contains a value,
  so `helm get values` cannot disclose a password.
- **Terraform:** the database password is **not an input variable**. It is
  generated by `random_password` and stored in Secrets Manager; the ECS task
  reads it via `secrets:` rather than `environment:`, so it does not appear in
  the task definition.

The honest caveat I would raise unprompted: that generated password **is** in
Terraform state. That is why the backend is encrypted with a CMK and access
controlled. Removing it from state entirely means `manage_master_user_password`
and letting RDS own it.

### How would you monitor this?

Symptoms, not causes. The four alerts in `monitoring/alerts.yml` are
availability, database reachability, error ratio above 5%, and p95 above the
250 ms SLO. There is deliberately no "CPU above 80%" alert — paging someone for
high CPU when no user is affected is how an on-call rotation learns to ignore
alerts.

Two instrumentation details I would defend in detail:

1. **Label cardinality.** Metrics are labelled with the route *template*
   (`/api/v1/users/{user_id}`), never the concrete path. Labelling the raw path
   would create one time series per user and eventually take Prometheus down.
   Unrouted requests collapse into a single `__unmatched__` bucket so a scanner
   probing random URLs cannot inflate cardinality. There are three tests
   asserting exactly this, because I shipped this bug once — see below.
2. **Histogram buckets** are chosen around the 250 ms SLO rather than left at
   the library default, so the histogram has resolution where the alert
   threshold actually sits.

Logs are JSON via structlog, carry the request id (accepted from an inbound
`X-Request-ID` so a trace survives service hops), and are shipped by Promtail
to Loki. `request_id` is extracted but deliberately **not** promoted to a Loki
label — one stream per request is how a Loki install falls over.

---

## Kubernetes

### Deployment vs StatefulSet?

A Deployment treats pods as interchangeable: random names, shared or no
storage, any replacement is as good as any other. A StatefulSet gives stable
ordinal identity (`postgres-0`), stable DNS via a headless Service, ordered
rollout, and a `volumeClaimTemplate` so each replica gets its own PVC.

In this repo the API is a Deployment and PostgreSQL is a StatefulSet. If
PostgreSQL were a Deployment it would get a random name on every reschedule
and, with a ReadWriteOnce volume, could fail to attach storage at all.

I verified the volume actually persists: I scaled the StatefulSet to zero, then
back up, and the row created before the outage was still there.

### Readiness and liveness probes — and why does it matter here?

- **Liveness** answers "should the kubelet restart me?"
- **Readiness** answers "should I receive traffic?"

The single most important design decision in this service is that
**`/health/live` does not touch the database and `/health/ready` does.** If
liveness queried PostgreSQL, a database failover would fail liveness on every
replica simultaneously, restart them all, and turn a recoverable dependency
outage into a total one.

**I tested this on a real cluster rather than asserting it.** I scaled
PostgreSQL to zero and observed:

```text
NAME                   READY   STATUS    RESTARTS
api-7bb754d466-dbn4b   0/1     Running   0
api-7bb754d466-nbjw8   0/1     Running   0

endpoint ready flags: false false
/health/live     200 {"status":"alive"}
/health/ready    503 {"status":"not_ready","checks":{"database":false}}
```

Pods stayed `Running` with **zero restarts** and were removed from the Service
endpoints. Restoring PostgreSQL returned them to `1/1 Ready`, still with zero
restarts, and the data survived.

There is also a `startupProbe` (30 × 2s), so a slow first boot gets up to 60
seconds without liveness killing it — which lets liveness itself stay fast.

### How does the HPA work?

The HPA compares actual utilisation to `averageUtilization` and adjusts
replicas. The critical detail: **utilisation is a percentage of the
request**, so a Deployment with no `resources.requests` gives the HPA no
denominator and it never scales.

`behavior` is asymmetric on purpose: 30 s stabilisation scaling up (react to
load), 300 s scaling down (aggressive scale-in causes flapping — capacity
leaves, latency rises, it scales up again).

There is a Helm subtlety worth knowing: when `autoscaling.enabled` is true the
chart **omits** `replicas` from the Deployment entirely. If it set it, every
`helm upgrade` would reset the replica count and undo the autoscaler's
decision. I verified both branches render correctly with `helm template`.

CPU and memory need metrics-server. Scaling on request rate or queue depth
needs Prometheus Adapter or KEDA — usually the better signal, since CPU is a
proxy for load rather than load itself.

### How does service discovery work?

CoreDNS. `postgres` resolves to `postgres.devops-demo.svc.cluster.local`. The
API Service is ClusterIP, and kube-proxy load balances across the endpoints
whose readiness condition is true — which is the mechanism that makes the
readiness probe actually do something.

PostgreSQL uses a **headless** Service (`clusterIP: None`) so DNS returns pod
IPs directly, giving the StatefulSet stable per-pod addressing.

I verified DNS resolution from inside a pod under a default-deny NetworkPolicy
(`socket.gethostbyname('postgres') -> 10.244.0.11`), which also proves the
explicit DNS egress rule is doing its job.

### Why is the migration a Job and not an initContainer?

An initContainer runs **once per pod**. With 2+ replicas, every pod would race
to migrate the same database on every rollout. A Job runs **once per release**.
Alembic's version table makes concurrent runs survivable, but "survivable" is
not "correct".

In Helm it is a `pre-upgrade` hook with
`hook-delete-policy: before-hook-creation`, because Job specs are immutable and
without that every upgrade fails with "field is immutable".

Verified on the cluster: the Job completed and logged
`Running upgrade -> 0001_create_users`, and the API pods then started against
the migrated schema.

### What do your NetworkPolicies actually do?

`default-deny-all` denies all ingress and egress in the namespace, then two
policies allow only the required flows. The most commonly forgotten rule is
**DNS egress to kube-system** — omit it and the application hangs in a way that
looks like an application bug rather than a network one.

Verified on a live cluster with the policies applied:

```text
readiness (app -> postgres:5432)  ->  200 ready      (allowed)
DNS (app -> kube-system:53)       ->  resolved       (allowed)
pod-to-pod API call on :80        ->  TimeoutError   (denied)
```

That last one is correct: nothing in the allow-list permits pod-to-pod API
traffic, only the ingress controller and Prometheus.

---

## Docker

### Why multi-stage builds?

`build-essential` and pip's cache exist only in the builder stage. The runtime
carries `libpq5` and `curl` and nothing else. Beyond size, it is a security
argument: a compiler in a production image is a tool an attacker can use.

### How did you reduce image size?

- `python:3.12-slim-bookworm` rather than the full image.
- Build toolchain confined to the builder stage; only `/opt/venv` is copied.
- `--no-install-recommends` and `rm -rf /var/lib/apt/lists/*` in the same layer
  as `apt-get install` — a separate `RUN` would leave the lists in the earlier
  layer and delete nothing.
- A `.dockerignore` that excludes `.git`, `.venv`, caches, docs and `.env`.

Measured: **349 MB**. Honest assessment — that is fine but not impressive.
`psycopg[binary]` and the Python runtime dominate. Distroless or Alpine with
`psycopg[c]` would get it under 150 MB, at the cost of a harder build and no
shell for debugging. I would make that trade for a service running thousands of
replicas, not this one.

### Why a non-root user?

Container isolation is namespaces, not a security boundary. Root in a container
is uid 0 on the host, so a container escape or a kernel bug lands with root
privileges.

This image runs as fixed uid 10001 — fixed rather than random because
Kubernetes `runAsUser` must match a number. The application code is owned by
**root** and only readable by the app user, so the running process cannot
rewrite its own source, which removes a common persistence technique.

Verified in the built image:

```text
uid=10001(app) gid=10001(app)
drwxr-xr-x 10 root root /app/app
```

Plus `cap_drop: ALL`, `no-new-privileges`, `read_only` root filesystem with a
64 MB tmpfs for `/tmp`, and `seccompProfile: RuntimeDefault` in Kubernetes.

### Why does the HEALTHCHECK point at liveness rather than readiness?

Same reason as the Kubernetes probe split. A Docker `HEALTHCHECK` on
`/health/ready` would mark every container unhealthy during a database outage,
and with an orchestrator watching, that means restarting them.

---

## Terraform

### What is Terraform state?

The mapping between configuration and real resource IDs. It is how Terraform
knows `aws_vpc.this` is `vpc-0abc123` rather than something to create again.

Two consequences that matter: state contains **every value the configuration
touches, including secrets, in plain text**; and two concurrent applies without
locking interleave and corrupt it — the worst failure mode Terraform has.

Hence `backend.tf.example`: S3, `encrypt = true` with a customer-managed KMS
key, and locking.

### How do modules work here?

Two modules, `network` and `app_runtime`, each with explicit `variables.tf`,
`outputs.tf` and pinned `versions.tf`. Environments compose them:

```hcl
module "app_runtime" {
  source     = "../../modules/app_runtime"
  vpc_id     = module.network.vpc_id      # dependency via output, not a data source
  ...
}
```

Inputs carry **validation blocks that encode real operational rules**, not just
types:

- `private_subnet_ids` requires at least two, because an RDS subnet group spans
  AZs and a one-subnet list fails deep inside the apply.
- `db_backup_retention_days` must be ≥ 1, because 0 silently disables automated
  backups and point-in-time recovery.
- `container_image` **rejects a `:latest` tag outright.**

`terraform validate` passes for both environments.

### How would you manage production state?

- Remote S3 backend, versioning on, encrypted with a CMK, public access blocked.
- Locking, so concurrent applies queue instead of corrupting state.
- **Separate root modules per environment, not workspaces.** Workspaces share
  one backend key and one credential set, so a mistyped `destroy` in dev can
  reach prod. Separate roots with separate keys — ideally separate buckets and
  separate AWS accounts — make that physically impossible.
- CI runs `plan` on the PR and `apply` only after human approval.
- `prevent_destroy` / `deletion_protection` on stateful resources, and
  `skip_final_snapshot = false` in prod.
- `ignore_changes = [password]` on the RDS instance, so an out-of-band rotation
  does not show up as drift on every plan.

---

## Security

### How do you secure GitHub Actions?

- **Least privilege.** Every workflow sets `permissions:` explicitly starting
  from `contents: read`; jobs opt in to `packages: write`, `id-token: write`
  and so on individually. The default token is broad and the default is wrong.
- **No long-lived cloud credentials.** OIDC federation mints a short-lived
  token per run. There is no AWS key to leak.
- **Pinned actions.** The Trivy action is pinned to a commit SHA — a tag can be
  moved, and a moved tag on a security scanner is a supply-chain compromise.
- **Untrusted input.** Nothing interpolates `github.event.*` text into a `run:`
  block, which is the classic script-injection path.
- **Environment protection.** Production deploys require a reviewer.
- **Refusing `latest`.** Both deploy jobs fail rather than deploy a mutable tag.

### How do you detect container vulnerabilities?

Trivy at three points: filesystem scan on the source, image scan on a build
that is loaded locally and **not pushed** (so nothing can be published before
it is scanned), and a scan of the published image by digest. HIGH and CRITICAL
fail the build, with `ignore-unfixed` — failing on a CVE with no available
patch gives the team no action to take, and a check nobody can act on is a
check everyone learns to ignore.

Alongside that: pip-audit for the resolved dependency tree (transitive
included, which is where most CVEs actually live), Dependabot grouped so a
routine week yields two reviewable PRs rather than fifteen, and SBOM plus
provenance attestation on every image so "is this affected by CVE-X?" is
answerable without a rebuild.

### How do you prevent secrets from being committed?

Defence in depth, because any single control fails:

1. `.gitignore` covers `.env`, `*.pem`, `*.key`, `*.tfvars`, `*.kubeconfig`.
2. `.dockerignore` repeats it, so a careless `COPY . .` cannot bake a secret
   into a layer.
3. Gitleaks in CI with `fetch-depth: 0` — a secret "removed" in a later commit
   is still in history forever.
4. Structural avoidance: the Terraform database password is generated, not
   supplied; the Helm chart references an existing Secret rather than holding a
   value; `secret.example.yaml` is a template that is never applied.
5. Every committed placeholder is obviously fake (`CHANGE-ME`,
   `local-dev-only-not-a-real-secret`).

If one *did* get committed, removing it from history is not enough — the
correct response is to rotate it, because it must be assumed compromised.

---

## Testing

### What are you actually testing?

46 tests, 96.83% line coverage, running in about 1.4 seconds. Coverage is a
diagnostic, not a target; the CI gate is a floor of 85% to catch a PR that
deletes tests.

The tests assert behaviour that would genuinely break in production: liveness
surviving a database outage, pagination neither repeating nor skipping rows
across pages, the unique index holding against a case-varied duplicate,
`session_scope` rolling back a partial transaction, the pagination limit being
clamped server-side, and metric labels never containing a UUID.

### Tell me about a bug your own tests caught.

Two, both real, both found during this build.

**A 422 that returned a 500.** `RequestValidationError.errors()` embeds the
original exception object under `ctx` when a custom validator raises
`ValueError`. That object is not JSON serialisable, so the error handler threw
while handling an error and the client got a 500. `_safe_validation_details`
now reduces each error to `loc`/`msg`/`type` — which also stops the rejected
input being mirrored back to the caller. There is a regression test.

**Metrics that were collected and useless.** Every series was labelled
`path="__unmatched__"`. The middleware resolved the route template *before*
`call_next`, but Starlette only populates `scope["route"]` during routing,
which happens downstream. The metrics endpoint looked healthy and the
dashboards drew lines — the data was simply meaningless, which is the worst
failure mode instrumentation has, because nothing alerts you to it.

The fix also had to rebuild the template from the concrete path rather than
reading `route.path`, because a router included under a prefix reports only its
relative path (`/users/{user_id}`, missing `/api/v1`). Three tests now cover
it, and I confirmed it on the running stack:

```text
GET   /api/v1/users/{user_id}   200
GET   /api/v1/users             200
GET   __unmatched__             404
uuid leaked into a label? False
```

I found that second one because I queried Prometheus after deploying instead of
assuming the code worked. That is the actual lesson: verify instrumentation
against the running system, because broken instrumentation is silent.

---

## Honest limitations

Worth raising before an interviewer finds them:

- **No authentication.** Deliberately out of scope so the operational story
  stays legible, but it is the first thing a real service needs.
- **PostgreSQL in Kubernetes is a demo.** Backups, PITR, failover and major
  version upgrades are the hard parts and a StatefulSet solves none of them.
  Production means RDS, Cloud SQL, or CloudNativePG.
- **No distributed tracing.** Metrics and logs, no traces. OpenTelemetry is
  the obvious next addition.
- **349 MB image.** Fine, not impressive. See above for the trade.
- **The Terraform has never been applied.** `fmt`, `init` and `validate` pass
  for both environments; `plan` and `apply` require AWS credentials I do not
  have. I would not claim a cloud deployment I did not perform.
- **CI has not run yet.** The workflows are committed and the YAML parses, but
  they execute for the first time on push. The individual gates that could be
  reproduced locally — ruff, mypy, bandit, pytest, the coverage floor, the
  migration drift check, `helm lint`, `terraform validate` — were all run and
  all pass.
