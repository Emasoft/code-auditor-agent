# jwt lens

## key
jwt

## fire-when
Content markers (greppable, any language): `jwt.sign`, `jwt.verify`, `jsonwebtoken`, `jwt.decode`, `jwt.encode`, `PyJWT`, `import jwt`, `jose`, `jws`, `algorithms=`, `alg`, `HS256`/`RS256`/`ES256`, `Bearer `, `Authorization` header issuance, `exp`/`iss`/`aud`/`sub` claim handling, `refresh_token`/`refreshToken` rotation, `decode_token`/`verify_token`. Languages: any (JS/TS, Python, Go, Java, etc.). Also Step-0 gate `domains.jwt.detected = true`.

## checklist
Audit JWT issuance/verification in this file (Layer: structural; categories: key-handling | algorithm | claim-validation | clock-skew | refresh-rotation | storage | transport):

- **Signing key not hardcoded:** a hardcoded HMAC secret or RSA/EC private key in source → MUST-FIX (remediation: rotate the key + move to a secret manager).
- **Algorithm accept-list:** verification accepts only an explicit allow-list of algorithms. `algorithms=None` (PyJWT), `alg: 'none'`, or no algorithm pinning at verify → MUST-FIX (no exceptions).
- **`exp` issued:** token signed/issued WITHOUT an `exp` claim → MUST-FIX.
- **`exp` validated:** verification ignores expiry (e.g. `options={ignoreExpiration: True}`, `verify_exp=False`) → MUST-FIX (no exceptions).
- **`iss` validated:** verification does not pin the expected issuer → SHOULD-FIX.
- **`aud` validated:** verification does not pin the expected audience → SHOULD-FIX.
- **Clock-skew:** `leeway` / `clockTolerance` set to a sane bound (≤ 60s). Missing → NIT (do not flag if no skew tolerance is configured at all only when verification is otherwise correct).
- **Refresh-token rotation:** a refresh operation issues a NEW refresh token AND revokes/invalidates the old one. Missing rotation (reusable refresh token) → MUST-FIX.
- **Client storage:** browser/client code stores the JWT in `localStorage`/`sessionStorage` (XSS-exfiltration risk) → SHOULD-FIX (recommend httpOnly cookie, `SameSite=strict`).
- **Token in URL:** JWT passed as a query parameter (leaks via access logs + Referer header) → MUST-FIX.

Severity rule: hardcoded signing keys, `alg=none`, and `ignoreExpiration` are always MUST-FIX. Confidence HIGH/MEDIUM/LOW; phrase LOW as a question. Every finding cites `file:line` evidence with the snippet and a specific remediation.
