from fire_leadgen.enrichment.size import estimate_size


def test_hunter_headcount_wins():
    bucket, basis = estimate_size(hunter_headcount="11-50", team_count=2)
    assert bucket == "26-50"
    assert "Hunter headcount" in basis


def test_no_signals():
    assert estimate_size() == ("", "")


def test_heuristic_small_shop():
    bucket, basis = estimate_size(team_count=2, google_reviews="12")
    assert bucket == "1-10"
    assert "2 leadership/team members" in basis


def test_heuristic_multi_location():
    bucket, basis = estimate_size(team_count=8, locations="4", google_reviews="300", email_count=9)
    assert bucket in ("51-100", "101-250")
    assert "4 locations" in basis
