# Security Policy

## Supported Versions

Only the `main` branch is actively maintained.

## Reporting a Vulnerability

If you believe you've found a security vulnerability in this project, please do **not** open a public GitHub issue. Instead, contact the maintainer directly:

- Email: henriquezbh5@gmail.com
- Subject line: `[SECURITY] LegalDataPlatform - <short description>`

Please include:

- A description of the vulnerability
- Steps to reproduce
- Affected component (extractor, migration, handler, etc.)
- Potential impact assessment if you have one

**Response timeline:**

- Acknowledgement within 72 hours
- Triage + preliminary assessment within 7 days
- Patch or mitigation plan within 30 days for high-severity issues

Credit for responsible disclosure will be given in the CHANGELOG unless you prefer to remain anonymous.

## Security practices in the project

- Dependencies audited on every push via `pip-audit` in CI
- Static analysis via `bandit` on every push
- Secrets detection via `gitleaks` in pre-commit hooks
- No credentials in the repo — `.env` is `.gitignore`d, production secrets live in AWS Secrets Manager
- Docker image runs as non-root (uid 1001)
- All S3 buckets default to SSE-KMS with key rotation enabled
- PostgreSQL connections use SCRAM-SHA-256 authentication
