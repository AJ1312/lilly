from lilly.engine.intent import Intent, classify_intent


def test_intent_classifies_outcomes_instead_of_tool_phrases() -> None:
    assert classify_intent("What is the capital of France?") is Intent.ANSWER
    assert classify_intent("Search the web for current train times") is Intent.WEB_RETRIEVE
    assert classify_intent("Open https://example.com") is Intent.NAVIGATE
    assert classify_intent("Open YouTube Music and play Fortnight") is Intent.ACTION


def test_intent_normalizes_whitespace() -> None:
    assert classify_intent("  go   to   example.com  ") is Intent.NAVIGATE
