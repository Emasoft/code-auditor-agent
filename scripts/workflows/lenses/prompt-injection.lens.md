# prompt-injection lens

## key
prompt-injection

## fire-when
Code that builds prompts for an LLM or consumes LLM output. Greppable signals: LLM-client deps (`openai`, `anthropic`, `@anthropic-ai`, `langchain`, `langchain_openai`, `google.generativeai`, `genai`, `mistralai`, `cohere`, `ollama`, `litellm`); prompt-template / message-array construction (`messages=[`, `role:`/`"role"`, `system_prompt`, `system=`, `ChatPromptTemplate`, `PromptTemplate`, f-string/`.format()`/`${}`/`{{ }}` template substitution into a prompt string); `max_tokens` / `completion`/`chat.completions`/`generate`/`invoke` calls. Step-0 equivalent: `domains.prompt_templates.detected = true`. Skip the file if no LLM-client / prompt-template usage is present.

## checklist
Audit ONE file that builds an LLM prompt or consumes LLM output. Core question: can a hostile user re-route the model via input the code treats as data, or can the LLM's output cause harm downstream? All findings are Layer=`structural`. Trace every prompt-template construction, paying special attention to f-string / template-substitution boundaries, and every downstream consumption of LLM output.

- system-prompt-injection (MUST-FIX): user-controlled content concatenated into the SYSTEM prompt (vs. a user-role message). The system prompt must NEVER contain user-provided data without sandwich-style isolation. A `f"{user_message}"` in the SYSTEM role is the single most severe finding — always MUST-FIX, no exceptions.
- tool-allowlist (MUST-FIX): when the LLM has tool/function-calling capability, the server must validate the requested tool name against a small allowlist. Open-ended dispatch on `tool_name` → MUST-FIX.
- output-validation (MUST-FIX): when the LLM returns JSON, it must be validated against a schema (Pydantic / zod) before being consumed. Missing → MUST-FIX.
- xss-via-llm (MUST-FIX): LLM output rendered as HTML / markdown in a browser without sanitisation (DOMPurify / bleach / rehype-sanitize) → MUST-FIX (XSS via prompt injection).
- code-injection-via-llm (MUST-FIX, no exceptions): LLM output passed to `os.system`, `exec`, `eval`, `child_process.exec`, or raw SQL — even via "templates" → MUST-FIX. Fix is parameterisation OR a strict regex+allowlist.
- length-cap (SHOULD-FIX): LLM output must be bounded (`max_tokens` set AND truncated downstream). Missing → SHOULD-FIX.
- privacy-leak (SHOULD-FIX): logs / error messages echo the prompt body (and thus user input) without redaction → SHOULD-FIX.
- sandwich-isolation (SHOULD-FIX): when user content MUST appear inside the prompt, it must be wrapped in clearly delimited markers (e.g. `<user_input>...</user_input>`) AND the model instructed to ignore directives inside those tags. Missing → SHOULD-FIX.

Confidence calibration: HIGH / MEDIUM / LOW; phrase LOW-confidence findings as a question. Categories (use verbatim): system-prompt-injection | tool-allowlist | length-cap | output-validation | xss-via-llm | code-injection-via-llm | privacy-leak | sandwich-isolation.
