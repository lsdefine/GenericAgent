# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| latest  | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly.

**Do NOT open a public issue.**

Instead, please email: **security@aibubu.app**

Or use [GitHub Security Advisories](https://github.com/funAgent/ai-bubu/security/advisories/new) to report privately.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: within 48 hours
- **Assessment**: within 1 week
- **Fix**: as soon as possible, depending on severity

## Scope

The following are in scope:

- Tauri application security (IPC, CSP, file access)
- LAN social protocol (UDP broadcast on port 23456)
- Skin import and validation
- Data stored locally (SQLite, Tauri Store)

The marketing site (aibubu.app) is also in scope.

## Disclosure

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). We will credit reporters in the release notes unless they prefer to remain anonymous.
