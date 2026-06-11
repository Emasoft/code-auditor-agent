# logging lens

## key
logging

## fire-when
Files containing logging statements: calls to a logger (`logger.`/`log.`/`logging.`, `console.log`/`console.error`, `slf4j`/`Log4j`/`logback`, `zap`/`logrus`/`zerolog`, `tracing::`, `print`/`println` used as logging) AND a logging framework is detected in the codebase. Common content markers: `logger`, `logging`, `log.info`, `log.error`, `log.debug`, `log.warn`, `console.log`, `exc_info`, `LoggerFactory`, structured-logging key=value/JSON emitters. SKIP if no logging framework is detected.

## checklist
Audit each logging statement in this file:
1. **PII in logs (pii).** Email / phone / address / national-ID / payment-card fragments emitted in a log line. MUST-FIX. Redact at the boundary.
2. **Secrets in logs (secrets).** API keys / JWTs / passwords / refresh tokens echoed — including indirectly by interpolating a full request/object that contains them. MUST-FIX.
3. **Log level appropriateness (level).** Routine events logged at `error`/`warn`; developer-only events at `info`; per-request lifecycle at `debug`. Severity inflation = SHOULD-FIX.
4. **Correlation IDs (correlation-id).** Request-handler log lines must carry a request-id / trace-id / correlation-id. Missing in a new endpoint = SHOULD-FIX.
5. **Structured vs unstructured consistency (structured-consistency).** New code should use structured logging (key=value, JSON) matching the codebase convention. String-concatenated single-blob messages in a structured-logging codebase = SHOULD-FIX.
6. **Over-logging in hot paths (hot-path).** New log inside a per-iteration loop / per-request body path that fires >100×/s in steady state = MUST-FIX unless deliberately rate-limited.
7. **Exception logging (exception-trace).** `except: logger.error(e)` without traceback / `exc_info=True` / `logger.exception(...)` loses the stack = SHOULD-FIX.
8. **Log injection (log-injection).** User input concatenated into a log line without newline / control-char sanitisation allows log forgery = SHOULD-FIX.

Severity values: MUST-FIX | SHOULD-FIX | NIT. Confidence: HIGH | MEDIUM | LOW. Layer is always `structural`. PII/secrets in logs and per-request-body hot-path logs are MUST-FIX.
