import csv
import os

from fire_leadgen.models import Company
from fire_leadgen.output.sheets import SheetWriter

CONFIG = os.path.join(os.path.dirname(__file__), "..", "sectors", "fire-protection", "sheet_columns.yaml")


def test_csv_fallback_matches_template(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    out = tmp_path / "leads.csv"
    writer = SheetWriter(CONFIG, str(out))
    n = writer.upsert([
        Company(name="Acme Fire Protection", domain="acmefire.com",
                first_name="Jane", last_name="Doe", position="Owner",
                contact_email="jdoe@acmefire.com", msa="Bridgeport-Stamford-Norwalk",
                ppp_loan="325000", est_revenue="5005000", employees="28"),
    ])
    assert n == 1
    with open(out) as fh:
        rows = list(csv.reader(fh))
    header, row = rows[0], rows[1]
    # header must match the Clew template exactly, in order
    assert header == [
        "Company Name", "First Name", "Last Name", "Position", "Contact Email",
        "Contact Phone Number", "LinkedIn", "Owner Age", "Company - Domain",
        "Industry", "Customer Type", "City", "State", "MSA", "Google Reviews",
        "PPP Loan", "Est. Revenue", "Employees", "Locations", "Year Founded",
        "Notes", "Lead Source",
    ]
    assert row[header.index("Company Name")] == "Acme Fire Protection"
    assert row[header.index("Company - Domain")] == "acmefire.com"
    assert row[header.index("First Name")] == "Jane"
    assert row[header.index("Contact Email")] == "jdoe@acmefire.com"
    assert row[header.index("Est. Revenue")] == "5005000"
