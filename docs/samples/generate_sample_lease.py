"""Generate a sample commercial lease PDF for testing AI lease ingestion.

This produces ``sample_commercial_lease.pdf`` — a short but realistic
commercial office lease that contains every field the AI lease parser
(``backend/app/services/ai_service.py::parse_lease_document``) tries to
extract:

    lease_name, lessor_name, lease_commencement_date, lease_expiration,
    lease_notice_date, notice_period, notice_period_days, payment_amount,
    payment_frequency, annual_escalation_rate, expiration_year

Regenerate with::

    pip install reportlab
    python docs/samples/generate_sample_lease.py

The committed PDF can be uploaded on the Lease create form ("AI assist —
extract from document") to exercise ``POST /api/v1/ai/leases/parse``.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

OUTPUT = Path(__file__).with_name("sample_commercial_lease.pdf")

BODY = [
    ("COMMERCIAL OFFICE LEASE AGREEMENT", "Title"),
    (
        "This Commercial Office Lease Agreement (the &ldquo;Lease&rdquo;) is "
        "made and entered into as of January 1, 2025, by and between "
        "<b>Greenfield Property Holdings, LLC</b>, a Delaware limited "
        "liability company (the &ldquo;Lessor&rdquo; or &ldquo;Landlord&rdquo;), "
        "and <b>Northwind Analytics, Inc.</b>, a California corporation "
        "(the &ldquo;Lessee&rdquo; or &ldquo;Tenant&rdquo;).",
        "Body",
    ),
    ("1. Premises", "H2"),
    (
        "Landlord hereby leases to Tenant Suite 1200, comprising approximately "
        "8,500 rentable square feet, located at 455 Market Plaza, San "
        "Francisco, California 94105 (the &ldquo;Premises&rdquo;). This lease "
        "shall be identified for reference as <b>Northwind Analytics &ndash; "
        "Suite 1200</b>.",
        "Body",
    ),
    ("2. Term", "H2"),
    (
        "The term of this Lease shall be sixty (60) months. The "
        "<b>Commencement Date</b> shall be <b>January 1, 2025</b>, and the "
        "Lease shall expire at 11:59 p.m. on the <b>Expiration Date</b> of "
        "<b>December 31, 2029</b>, unless sooner terminated or extended in "
        "accordance with the terms hereof.",
        "Body",
    ),
    ("3. Base Rent", "H2"),
    (
        "Tenant shall pay to Landlord base rent in the amount of "
        "<b>$28,500.00 per month</b>, payable <b>monthly</b> in advance on "
        "the first (1st) day of each calendar month, without demand, setoff, "
        "or deduction.",
        "Body",
    ),
    ("4. Rent Escalation", "H2"),
    (
        "Commencing on the first anniversary of the Commencement Date and on "
        "each anniversary thereafter, the base rent shall increase by "
        "<b>three percent (3.0%)</b> over the base rent payable during the "
        "immediately preceding twelve (12) month period.",
        "Body",
    ),
    ("5. Renewal and Notice", "H2"),
    (
        "Tenant shall have one (1) option to renew this Lease for an "
        "additional five (5) year term. To exercise this option, or to notify "
        "Landlord of its intent not to renew, Tenant must deliver written "
        "notice to Landlord no later than <b>ninety (90) days</b> prior to the "
        "Expiration Date. Accordingly, the <b>notice deadline is October 2, "
        "2029</b>. Time is of the essence with respect to the delivery of "
        "such notice.",
        "Body",
    ),
    ("6. Permitted Use", "H2"),
    (
        "The Premises shall be used and occupied by Tenant solely for general "
        "office and software-development purposes, and for no other purpose "
        "without the prior written consent of Landlord.",
        "Body",
    ),
    ("7. Security Deposit", "H2"),
    (
        "Upon execution of this Lease, Tenant shall deposit with Landlord the "
        "sum of $57,000.00 as a security deposit for the faithful performance "
        "of Tenant&rsquo;s obligations hereunder.",
        "Body",
    ),
    (
        "IN WITNESS WHEREOF, the parties have executed this Lease as of the "
        "date first written above.",
        "Body",
    ),
    (
        "LANDLORD: Greenfield Property Holdings, LLC<br/><br/>"
        "By: ______________________________<br/><br/>"
        "TENANT: Northwind Analytics, Inc.<br/><br/>"
        "By: ______________________________",
        "Body",
    ),
]


def build() -> None:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "Title2",
            parent=styles["Title"],
            fontSize=16,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            "H2custom",
            parent=styles["Heading2"],
            fontSize=12,
            spaceBefore=10,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            "Bodycustom",
            parent=styles["BodyText"],
            fontSize=10.5,
            leading=15,
            spaceAfter=8,
        )
    )
    style_map = {"Title": "Title2", "H2": "H2custom", "Body": "Bodycustom"}

    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        title="Sample Commercial Office Lease",
        author="Office Manager sample data",
    )
    flow = []
    for text, kind in BODY:
        flow.append(Paragraph(text, styles[style_map[kind]]))
        if kind == "Title":
            flow.append(Spacer(1, 6))
    doc.build(flow)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    build()
