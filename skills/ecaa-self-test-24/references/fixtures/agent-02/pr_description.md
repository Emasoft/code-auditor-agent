# Add retry-with-backoff to HTTP client

This PR adds exponential-backoff retry logic to the HTTP client
so transient network errors are recovered automatically. Closes #42
(which complained the client gives up after a single 500 response).
