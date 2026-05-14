// Entry file for the mynodelib fixture. Exposes a small public API via
// both ESM-style named exports AND CommonJS shapes so the discoverer's
// every pattern fires at least once.

function greet(name) {
  return "hello, " + String(name);
}

class Greeter {
  constructor(prefix) {
    this.prefix = String(prefix);
  }

  say(name) {
    return this.prefix + " " + String(name);
  }
}

function _internalHelper(x) {
  // Underscore-prefixed — must NOT appear as a library export.
  return x + 1;
}

module.exports = { greet, Greeter };
