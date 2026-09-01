## What and why

<!-- What changes, and what problem it solves. Link the issue. -->

Closes #

## Type

- [ ] feat - new capability
- [ ] fix - bug fix
- [ ] security - hardening or vulnerability fix
- [ ] infra - Terraform / Kubernetes / Helm
- [ ] ci - pipeline
- [ ] docs
- [ ] refactor - no behaviour change

## How it was verified

<!-- What you actually ran, not what you intended to run. -->

- [ ] `pytest` passes locally
- [ ] `ruff check .` and `ruff format --check .` clean
- [ ] `mypy` clean
- [ ] `docker compose up -d` and the stack is healthy
- [ ] Manifests validated (`kubeconform` / `helm template`)
- [ ] `terraform validate` (if infrastructure changed)

## Operational impact

- [ ] Includes a database migration
  - [ ] The migration is **backwards compatible** with the currently deployed code
  - [ ] `alembic downgrade -1` was tested
- [ ] Changes configuration (ConfigMap / Secret / env var)
- [ ] Changes resource requests or limits
- [ ] Changes a health probe
- [ ] Requires a coordinated deploy or a specific ordering

## Security

- [ ] No secret, key, token or credential is added to the repository
- [ ] New dependencies were checked for known CVEs
- [ ] New endpoints validate their input
- [ ] Errors do not leak internal detail to clients

## Rollback plan

<!-- How to undo this if it goes wrong in production. "Revert the PR" is only
     a real answer when there is no migration and no data change. -->
