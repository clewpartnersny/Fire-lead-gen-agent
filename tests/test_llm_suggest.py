from fire_leadgen.discovery.llm_suggest import enabled, parse_names


def test_parse_names_cleans_llm_output():
    text = """Here are some companies:
1. Acme Fire Protection
2. Reliable Sprinkler Systems
- Tri-State Fire & Safety
* Alarm Masters
Note: verify these independently.
"""
    names = parse_names(text)
    assert "Acme Fire Protection" in names
    assert "Reliable Sprinkler Systems" in names
    assert "Tri-State Fire & Safety" in names
    assert "Alarm Masters" in names
    assert all("Note:" not in n and "Here" not in n for n in names)


def test_parse_names_empty():
    assert parse_names("") == []
    assert parse_names("I could not find any companies.") == []


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not enabled()
