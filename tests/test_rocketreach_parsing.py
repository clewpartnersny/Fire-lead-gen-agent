from fire_leadgen.enrichment.rocketreach import _best_email, _pick_phones


def test_all_mobiles_recommended_first_capped_at_four():
    phones = [
        {"number": "+1 111", "type": "unknown", "validity": "valid"},
        {"number": "+1 222", "type": "mobile", "validity": "valid"},
        {"number": "+1 333", "type": "mobile", "validity": "valid", "recommended": True},
        {"number": "+1 444", "type": "mobile", "validity": "invalid"},
        {"number": "+1 555", "type": "cell", "validity": "valid"},
        {"number": "+1 666", "type": "mobile", "validity": "valid"},
    ]
    out = _pick_phones(phones)
    nums = out.split("; ")
    assert nums[0] == "+1 333"          # recommended first
    assert len(nums) == 4               # capped at 4
    assert "+1 111" not in nums         # office/unknown excluded when mobiles exist
    assert "+1 444" not in nums or nums.index("+1 444") == 3  # invalid ranked last


def test_fallback_to_first_number_when_no_mobiles():
    assert _pick_phones([{"number": "+1 999", "type": "unknown"}]) == "+1 999"
    assert _pick_phones([]) == ""


def test_dedupes_numbers():
    phones = [
        {"number": "+1 222", "type": "mobile"},
        {"number": "+1 222", "type": "cell"},
    ]
    assert _pick_phones(phones) == "+1 222"


def test_best_email_prefers_professional():
    emails = [
        {"email": "ned42@aol.com", "type": "personal"},
        {"email": "ned@fpteam.com", "type": "professional"},
    ]
    assert _best_email(emails) == "ned@fpteam.com"
    assert _best_email([{"email": "a@b.com", "type": "personal"}]) == "a@b.com"
    assert _best_email([]) == ""
