# solidity lens

## key
solidity

## fire-when
`*.sol` files; Solidity source (`pragma solidity`); smart-contract repos (Hardhat/Foundry/Truffle: `hardhat.config.*`, `foundry.toml`, `truffle-config.js`); upgradeable-proxy markers (OpenZeppelin `Initializable`, `UUPSUpgradeable`, `TransparentUpgradeableProxy`, `__gap`).

## checklist
- **Reentrancy (Category: reentrancy):** state updated AFTER an external call / `.transfer` / `.call` / `.send`; missing Checks-Effects-Interactions ordering or `nonReentrant` guard → MUST-FIX.
- **Integer overflow (Category: overflow):** Solidity `< 0.8` without SafeMath, OR any `unchecked { ... }` block doing arithmetic that could wrap → MUST-FIX (or document the safety argument).
- **tx.origin auth (Category: auth):** authorization gated on `tx.origin == owner` (phishing risk) → MUST-FIX; require `msg.sender` instead.
- **Unchecked external calls (Category: unchecked-call):** return value of `.call` / `.delegatecall` ignored / not checked → MUST-FIX.
- **Gas-limit DoS (Category: gas-dos):** loops over unbounded arrays / mappings, or unbounded `for` over a public function's input → MUST-FIX.
- **Storage slot collision (Category: storage-collision):** new/modified upgradeable proxy without a storage `__gap` or with reordered/inserted storage layout → MUST-FIX.
- **Pause / upgradeable (Category: pause):** significant new logic with no emergency-pause mechanism or upgrade path → SHOULD-FIX.
- **Missing events (Category: events):** state-changing functions that don't emit events for off-chain indexers → SHOULD-FIX.
- Reentrancy + tx.origin + unchecked external calls + unbounded-loop gas-DoS are MUST-FIX with NO exceptions.
- Severity = MUST-FIX | SHOULD-FIX | NIT; Confidence = HIGH | MEDIUM | LOW; Layer = `structural`.
- Do not re-flag findings already produced by slither / mythril if their linter output is available.
