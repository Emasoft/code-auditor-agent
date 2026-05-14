// ESM-flavoured named exports — covered by pattern 1 of the discoverer.

export function trim(s) {
  return String(s).trim();
}

export const join = (a, b) => String(a) + String(b);

export class Counter {
  constructor() {
    this.n = 0;
  }
  tick() {
    this.n += 1;
    return this.n;
  }
}

function _private() {
  // Must NOT be exported.
  return null;
}
