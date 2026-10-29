# Security policy

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/shreyescodes/Invoice-Intelligence-Platform/security/advisories/new)
with a description, the affected version or commit, and steps to reproduce. You'll get an
acknowledgement within three working days.

## Scope notes

- The demo accounts and the `DEMO_MODE` login hints exist only for local showcases. The application
  refuses to start with `ENVIRONMENT=production` and `DEMO_MODE=true`, or with the default JWT secret.
- The mock ERP (`erp-mock/`) is a development stand-in and is not hardened for internet exposure.
- The design of the main controls (upload handling, authorisation, the SQL guard, secrets) is described
  in [docs/architecture.md](docs/architecture.md#security).
