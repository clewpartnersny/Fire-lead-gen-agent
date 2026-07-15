from fire_leadgen.enrichment import reviews


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload

    def post(self, url, **kwargs):
        return FakeResp(self.payload)


PLACES = {"places": [
    {"title": "Fire Protection Team", "rating": 4.7, "ratingCount": 109,
     "address": "1701 Highland Ave, Cheshire, CT 06410"},
    {"title": "Some Other Business", "rating": 3.0, "ratingCount": 5},
]}


def test_lookup_reviews_matches_name(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    rating, count, address = reviews.lookup_reviews("Fire Protection Team", "Cheshire", "CT", FakeHttp(PLACES))
    assert rating == "4.7"
    assert count == "109"
    assert "Cheshire, CT" in address


def test_lookup_reviews_no_match(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    assert reviews.lookup_reviews("Unrelated Fire Co", "Dallas", "TX", FakeHttp(PLACES)) == ("", "", "")


def test_lookup_reviews_disabled_without_key(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    assert reviews.lookup_reviews("Fire Protection Team", "", "", FakeHttp(PLACES)) == ("", "", "")
