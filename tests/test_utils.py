from fire_leadgen.utils import first_email, normalize_domain, normalize_phone


def test_normalize_domain():
    assert normalize_domain("https://www.acmefire.com/about") == "acmefire.com"
    assert normalize_domain("http://acmefire.co.uk") == "acmefire.co.uk"
    assert normalize_domain("acmefire.com") == "acmefire.com"
    assert normalize_domain("not a url") == ""
    assert normalize_domain("") == ""


def test_normalize_phone():
    assert normalize_phone("Call us at (212) 555-1234 today") == "(212) 555-1234"
    assert normalize_phone("212.555.1234") == "(212) 555-1234"
    assert normalize_phone("+1 212-555-1234") == "(212) 555-1234"
    assert normalize_phone("no phone here") == ""


def test_first_email_prefers_own_domain():
    text = "reach webmaster@wixpress.com or info@acmefire.com or bob@gmail.com"
    assert first_email(text, "acmefire.com") == "info@acmefire.com"
    assert first_email("only bob@gmail.com here", "acmefire.com") == "bob@gmail.com"
    assert first_email("nothing", "acmefire.com") == ""
