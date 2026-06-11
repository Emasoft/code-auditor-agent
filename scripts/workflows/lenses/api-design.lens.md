# api-design lens

## key
api-design

## fire-when
REST or GraphQL endpoints present in the file. Greppable signals: route/handler decorators (`@app.route`, `@router.get`/`.post`/`.put`/`.delete`/`.patch`, `@RestController`, `@RequestMapping`, `@GetMapping`/`@PostMapping`, `app.get(`/`router.post(`, `@Get(`/`@Post(` NestJS, `func (.*) ServeHTTP`, Flask/FastAPI/Express/Spring/Rails routes); GraphQL resolvers/`type Query`/`type Mutation`/`.graphql`/`*.gql`; OpenAPI/Swagger spec files (`openapi.yaml`/`.json`, `swagger.*`). Skip files with no HTTP endpoint or GraphQL schema/resolver.

## checklist
- HTTP method semantics: GET safe + idempotent; PUT idempotent; POST creates; DELETE idempotent in effect. Method/behavior mismatch → MUST-FIX (category: http-method).
- Status code correctness per RFC 7231: 200 vs 201 vs 204 vs 404 vs 409 vs 422 used correctly. Wrong code → SHOULD-FIX (category: status-code).
- Pagination: list endpoints accept `?page` / `?cursor` / `?limit` AND return `next` / `prev` / `total`. Missing on an unbounded list → MUST-FIX (category: pagination).
- Idempotency: non-GET endpoints accept an `Idempotency-Key` header OR are inherently idempotent. Missing → SHOULD-FIX (category: idempotency).
- Versioning: new endpoints follow the codebase's existing versioning convention (URL path / Accept header / query param). Inconsistent → SHOULD-FIX (category: versioning).
- OpenAPI / spec consistency: if the repo has an OpenAPI/schema file and an endpoint is added, the spec MUST be updated to match. Missing/stale → MUST-FIX (category: spec-drift).
- Error envelope shape: errors return `{error: {code, message}}` (or the project's established convention). A new endpoint using a different error shape → SHOULD-FIX (category: error-envelope).
- Response-shape stability: a new endpoint that returns a field sibling endpoints in the same domain DON'T return, or omits a field they DO return → SHOULD-FIX (category: response-shape).
- Consistency findings (versioning, error-envelope, response-shape, spec-drift) require BOTH a cite of the endpoint's own code AND a cite of the sibling/established convention it diverges from.
- Layer for all findings is `structural`. Confidence HIGH / MEDIUM / LOW, with LOW phrased as a question. Every finding cites file:line evidence.
