# Security policy

## Reporting a vulnerability

Please report privately, never as a public issue:

- GitHub Security Advisories (preferred):
  https://github.com/rthway/devops-production-demo/security/advisories/new

Please include what you found, how to reproduce it, and the impact you believe
it has. I will acknowledge within 5 working days.

This is a demonstration repository and is not deployed anywhere public, so
there is no production system at risk — but the patterns here are meant to be
copied, and a flaw in a pattern propagates.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | yes |
| < 1.0 | no |

## Automated controls

| Control | Tool | When |
|---|---|---|
| Static analysis | Bandit | every push and PR |
| Semantic analysis | CodeQL (python, actions) | every push and PR |
| Dependency CVEs | pip-audit, Dependabot | push, PR, weekly |
| Container CVEs | Trivy (fs + image + published digest) | push, PR, weekly |
| Secret scanning | Gitleaks (full history) | every push |

HIGH and CRITICAL findings with an available fix fail the build.

## Deliberate security decisions

- Containers run as non-root uid 10001, `cap_drop: ALL`, read-only root
  filesystem, `no-new-privileges`, `seccompProfile: RuntimeDefault`.
- The Kubernetes namespace enforces the `restricted` Pod Security Standard, so
  a future careless manifest cannot regress the hardening above.
- NetworkPolicy is default-deny; only required flows are allowed.
- Error responses never contain stack traces or driver messages.
- The Terraform database password is generated in-provider and stored in
  Secrets Manager. It is never a variable and never in this repository.
- No secret is committed. `.env.example` and `secret.example.yaml` are
  templates with obvious placeholders.

## Known limitations

Stated plainly rather than left for a reader to discover:

- There is no authentication or authorisation on the API. It is out of scope
  for this demonstration.
- A Kubernetes Secret is base64, not encryption. Without encryption at rest on
  etcd it is plaintext to anyone who can read etcd.
- The Terraform-generated database password is recorded in Terraform state,
  which is why the backend must be encrypted and access controlled.
- The Compose stack mounts the Docker socket read-only into Promtail for
  service discovery. Read access to the Docker socket is effectively root on
  the host. This is acceptable for a local stack and is not how the Kubernetes
  deployment works.
