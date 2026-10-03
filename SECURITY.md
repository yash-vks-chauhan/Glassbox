# Security policy

GlassBox is built to keep an audit trail that can be trusted, so security
reports are very welcome.

## Reporting a vulnerability

Please report it privately through GitHub:
**[Report a vulnerability](https://github.com/yash-vks-chauhan/Glassbox/security/advisories/new)**
(the repository's Security tab → "Report a vulnerability"). Don't open a
public issue for it.

Include what you found, how to reproduce it, and what an attacker could
do with it. You should hear back within a few days.

## In scope

- The code in this repository: the API, the web app, migrations,
  deployment files.
- The live demo at <https://glassbox.15-252-203-137.sslip.io>. Test against
  the shared demo accounts only. No denial-of-service or load testing,
  please, and don't put real personal or client data into it.

Especially interesting: crossing tenant boundaries, getting around a role,
changing or deleting audit records without verification noticing, getting
at the shared demo accounts' sign-in settings, and leaking secrets or
model keys.

## How GlassBox handles security

[docs/threat-model.md](docs/threat-model.md) maps each known threat to the
code that mitigates it and the test that keeps it fixed.
[docs/SECURITY-IMPLEMENTATION.md](docs/SECURITY-IMPLEMENTATION.md) describes
the controls. Dependencies are checked for known vulnerabilities on every
pull request.
