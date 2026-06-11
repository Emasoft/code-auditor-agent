# frontend lens

## key
frontend

## fire-when
Web-frontend framework detected. Fire on these file/content signals:
- Extensions: `*.jsx`, `*.tsx`, `*.vue`, `*.svelte`, `*.astro`
- React/Solid: `.jsx`/`.tsx` containing JSX, `dangerouslySetInnerHTML`, `import ... from "react"`/`"solid-js"`
- Vue: `*.vue` single-file components, `v-html`, `import ... from "vue"`
- Svelte: `*.svelte`, `{@html ...}`
- Angular: `*.component.ts`/`*.component.html`, `[innerHTML]`
- Markers: `<img`, `<button`, `onClick`, `onKeyDown`, CSP headers (`Content-Security-Policy`, `unsafe-inline`, `unsafe-eval`), heavy imports (lodash, moment, monaco-editor, chart.js, three.js)
- Do NOT fire on pure backend/non-UI source.

## checklist
Audit this web-frontend file for accessibility, XSS, CSP, and runtime-perf concerns. Apply each check; cite file:line evidence; assign Severity (MUST-FIX | SHOULD-FIX | NIT), Confidence (HIGH | MEDIUM | LOW — phrase LOW as a question), Layer `structural`, and the exact Category id in brackets.

- [a11y-semantic] New interactive controls use `<button>`/`<a>`/form elements, NOT `<div onClick>` / `<span onClick>`. Wrong → MUST-FIX.
- [a11y-alt] `<img>` / `<Image>` without `alt`, or `alt=""` on a meaningful image → SHOULD-FIX.
- [a11y-aria] Icon-only `<button>` without an accessible name (aria-label) → SHOULD-FIX.
- [a11y-keyboard] Custom widgets handle `onKeyDown` for Enter/Space/Esc/Arrow where applicable; missing → SHOULD-FIX.
- [a11y-focus] Modals trap focus; route changes move focus to the new region heading; missing → NIT.
- [xss-html] `dangerouslySetInnerHTML` (React) / `v-html` (Vue) / `{@html ...}` (Svelte) / `[innerHTML]` (Angular) with input NOT sanitised via DOMPurify / `Sanitizer.sanitize` → MUST-FIX. No exceptions, even for "trusted" sources.
- [xss-eval] `document.write` / `eval` / `new Function` / `setTimeout("...string...")` → MUST-FIX.
- [xss-href] `href={userInput}` / `src={userInput}` (risk of `javascript:` scheme leak) → SHOULD-FIX.
- [csp-inline] Inline scripts without nonce/hash where CSP is enabled → SHOULD-FIX.
- [csp-unsafe] `unsafe-inline` / `unsafe-eval` added to CSP → MUST-FIX (defeats the policy).
- [bundle-size] Heavy new import in the critical bundle (lodash, moment, monaco-editor, chart.js, three.js full bundle) without dynamic-import splitting → SHOULD-FIX.
- [web-vitals-lazy] Large below-the-fold image without `loading="lazy"` → NIT.
- [web-vitals-cls] New components rendering images/iframes without explicit width/height (layout shift) → NIT.
- Compare against sibling components for established convention before flagging.
- If an eslint/biome a11y plugin (eslint-plugin-jsx-a11y, @vue/eslint-config-typescript) already covered a finding, do NOT re-flag it.
