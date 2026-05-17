# ruff: noqa
# Intentionally contains the bugs each detector should catch.
def build_summary_prompt(user_input: str) -> str:
    return f"You are a summarizer. Summarize the following text:\n\n{user_input}"


def build_translation_prompt(user_input: str, target_lang: str) -> str:
    return (
        f"Translate the user's message into {target_lang}. "
        f"User says: {user_input}"
    )
