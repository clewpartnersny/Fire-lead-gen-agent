"""Rules from the Clew research manual: name cleaning, generic-email ban,
MSA assignment, PPP indexing/lookup and the revenue multiplier."""

import sqlite3

from fire_leadgen.enrichment import ppp
from fire_leadgen.enrichment.msa import assign_msa
from fire_leadgen.utils import clean_company_name, is_generic_email, split_person_name


def test_clean_company_name():
    assert clean_company_name("Acme Fire Protection, LLC") == "Acme Fire Protection"
    assert clean_company_name("Acme Fire Protection Inc.") == "Acme Fire Protection"
    assert clean_company_name("Acme Fire & Safety Corp") == "Acme Fire & Safety"
    assert clean_company_name("Acme Sprinkler Co., Inc.") == "Acme Sprinkler"
    assert clean_company_name("Acme Fire") == "Acme Fire"
    assert clean_company_name("") == ""


def test_generic_emails_rejected():
    assert is_generic_email("info@acmefire.com")
    assert is_generic_email("Sales@acmefire.com")
    assert is_generic_email("front.desk@acmefire.com")
    assert not is_generic_email("jsmith@acmefire.com")
    assert not is_generic_email("john.smith@acmefire.com")


def test_split_person_name():
    assert split_person_name("John Smith") == ("John", "Smith")
    assert split_person_name("John A. Smith") == ("John", "Smith")
    assert split_person_name("Cher") == ("Cher", "")
    assert split_person_name("") == ("", "")


def test_msa_assignment():
    assert assign_msa("Stamford", "CT") == "Bridgeport-Stamford-Norwalk"
    assert assign_msa("Brooklyn", "NY") == "New York-Newark-Jersey City"
    assert assign_msa("Frederick", "MD") == "Washington-Arlington-Alexandria"
    assert assign_msa("Nowheresville", "MD") == "MD (Other)"
    assert assign_msa("", "TX") == "TX (Other)"
    assert assign_msa("Boston", "") == ""


def test_ppp_import_and_lookup(tmp_path):
    csv_path = tmp_path / "ppp.csv"
    csv_path.write_text(
        "BorrowerName,BorrowerCity,BorrowerState,CurrentApprovalAmount,JobsReported\n"
        "ACME FIRE PROTECTION LLC,STAMFORD,CT,325000.00,28\n"
        "ACME FIRE PROTECTION LLC,STAMFORD,CT,180000.00,28\n"
        "TINY SPRINKLER CO,DALLAS,TX,40000.00,3\n"
    )
    conn = sqlite3.connect(":memory:")
    assert ppp.import_csvs(conn, [str(csv_path)]) == 3

    hit = ppp.lookup(conn, "Acme Fire Protection", "CT")
    assert hit["amount"] == 325000.0  # largest draw wins
    assert hit["jobs"] == 28
    # revenue estimate with the fire-protection multiplier from the manual
    assert int(hit["amount"] * 15.4) == 5005000

    assert ppp.lookup(conn, "Tiny Sprinkler", "TX")["amount"] == 40000.0
    assert ppp.lookup(conn, "Unknown Fire Co", "CT") == {}
