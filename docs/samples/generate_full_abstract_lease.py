"""Generate a sample commercial lease PDF that exercises the *Lease Abstract*.

``sample_full_abstract_lease.pdf`` is a long-form, realistic commercial office
lease whose articles map 1:1 onto every category in the Lease Abstract catalog
(``backend/app/services/lease_abstract_catalog.py``). It is intended to be
uploaded on a lease's **Abstract** screen ("Suggest with AI") so that
``POST /ai/leases/{id}/abstract/suggest`` can populate *all* 35 clause
categories — not just the handful of headline fields covered by
``sample_commercial_lease.pdf``.

The article text deliberately mentions the concrete figures behind the
structured fields each category captures (square footage, dates, dollar
amounts, percentages, notice periods, etc.) so the extraction has real content
to summarise for every category.

Regenerate with::

    pip install reportlab
    python docs/samples/generate_full_abstract_lease.py

The generator imports the catalog from the backend package so the document
stays in lock-step with the canonical category list: every category key is
asserted to have prose, and each renders as its own numbered article.
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

# Import the canonical catalog so the sample stays aligned with the schema.
_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.lease_abstract_catalog import CLAUSE_CATEGORIES  # noqa: E402

OUTPUT = Path(__file__).with_name("sample_full_abstract_lease.pdf")

# Narrative prose for each abstract category, keyed by the catalog ``key``.
# Every key in CLAUSE_CATEGORIES MUST appear here (asserted in build()).
CLAUSE_PROSE: dict[str, str] = {
    "square_footage": (
        "The Premises consist of Suite 1200 containing <b>8,500 rentable square "
        "feet</b> and <b>7,400 usable square feet</b>, yielding a common-area "
        "(load) factor of <b>14.86%</b>, measured in accordance with the "
        "<b>BOMA 2017</b> standard. Tenant's proportionate share of the Building "
        "(212,500 rentable square feet) is <b>4.0%</b>. The Premises include a "
        "separately demised <b>500 square foot storage area</b> in the basement."
    ),
    "commencement_expiration": (
        "The term is <b>sixty (60) months</b>. The <b>Commencement Date</b> is "
        "<b>January 1, 2025</b> and the <b>Expiration Date</b> is "
        "<b>December 31, 2029</b>. <b>Rent Commencement</b> occurs "
        "<b>March 1, 2025</b> following a two-month abatement period, and "
        "Tenant's anticipated <b>move-in date</b> is <b>February 15, 2025</b>."
    ),
    "rent_expiration": (
        "Base Rent is <b>$28,500.00 per month</b> ($342,000 annually, or $40.24 "
        "per rentable square foot) payable <b>monthly</b> in advance. Base Rent "
        "escalates <b>three percent (3.0%)</b> on each anniversary of the "
        "Commencement Date. The final lease-year rent expires with the term on "
        "<b>December 31, 2029</b>."
    ),
    "expense_schedule": (
        "This is a <b>modified gross</b> lease with a <b>2024 base year</b> for "
        "Operating Expenses and Real Estate Taxes. Estimated first-year operating "
        "expenses are <b>$12.50 per rentable square foot</b>, reconciled annually "
        "within 120 days after each calendar year-end."
    ),
    "expense_recoverables": (
        "Tenant pays its <b>4.0% pro-rata share</b> of increases in Operating "
        "Expenses and Taxes over the base year. Controllable operating expenses "
        "are subject to an annual <b>cumulative cap of 5%</b>. Management fees are "
        "capped at <b>3% of gross revenues</b> and capital expenditures are "
        "amortized over their useful life with interest at <b>6%</b>."
    ),
    "cpi": (
        "Where applicable, adjustments reference the <b>CPI-U, All Urban "
        "Consumers, U.S. City Average (1982-84=100)</b> published by the Bureau "
        "of Labor Statistics, applied annually with a <b>floor of 2%</b> and a "
        "<b>ceiling of 5%</b>."
    ),
    "improvements": (
        "Landlord provides a <b>Tenant Improvement Allowance of $50.00 per "
        "rentable square foot</b> ($425,000 total). Landlord delivers the "
        "Premises in <b>warm-shell</b> condition. Any unused allowance, up to "
        "<b>$5.00 per rentable square foot</b>, may be applied to moving costs."
    ),
    "force_majeure": (
        "Neither party is liable for delays caused by acts of God, war, "
        "terrorism, governmental restrictions, pandemics, labor disputes, or "
        "other causes beyond its reasonable control. Force majeure <b>does not</b> "
        "excuse the timely payment of Rent."
    ),
    "lease_options": (
        "Tenant holds <b>one (1) option to renew</b> for an additional "
        "<b>five (5) years</b> at <b>95% of fair market rent</b>, exercisable by "
        "written notice not less than <b>nine (9) months</b> before expiration. "
        "Tenant also holds a one-time <b>right of first offer</b> on contiguous "
        "Suite 1250."
    ),
    "signage_exclusivity": (
        "Tenant is entitled to <b>building-standard suite-entry signage</b>, one "
        "listing on the lobby directory, and, so long as it leases at least "
        "<b>7,500 rentable square feet</b>, <b>non-exclusive eyebrow signage</b> "
        "on the building exterior, subject to Landlord and municipal approval."
    ),
    "relocation_right": (
        "Landlord may relocate Tenant to comparable space of substantially equal "
        "size within the Building on <b>sixty (60) days'</b> prior written notice, "
        "with Landlord bearing all reasonable moving, build-out, and stationery "
        "reprinting costs."
    ),
    "holdover": (
        "Holding over without Landlord's consent constitutes a tenancy at "
        "sufferance at <b>150% of the then-current Base Rent</b> for the first "
        "two months and <b>200% thereafter</b>, plus consequential damages after "
        "thirty (30) days."
    ),
    "late_fees": (
        "Rent not received within <b>five (5) days</b> of its due date incurs a "
        "late charge equal to <b>5% of the overdue amount</b>, with a "
        "<b>$250 minimum</b>. A $35 fee applies to each dishonored payment."
    ),
    "interest": (
        "Past-due amounts bear interest from the due date until paid at the "
        "lesser of <b>12% per annum</b> or the maximum rate permitted by law."
    ),
    "brokerage_fees": (
        "Landlord shall pay the brokerage commission to <b>CBRE</b> (Landlord's "
        "broker) and <b>JLL</b> (Tenant's broker) pursuant to separate written "
        "agreements. Each party indemnifies the other against claims by brokers "
        "it engaged."
    ),
    "landlord_restriction": (
        "Landlord covenants not to lease any other premises in the Building to a "
        "<b>direct competitor data-analytics business</b> while Tenant is not in "
        "default, and warrants Tenant's <b>quiet enjoyment</b> of the Premises."
    ),
    "indemnification": (
        "Tenant indemnifies, defends, and holds Landlord harmless from claims "
        "arising in the Premises or from Tenant's negligence; Landlord provides a "
        "<b>reciprocal indemnity</b> for the common areas, in each case excluding "
        "the indemnitee's gross negligence or willful misconduct."
    ),
    "rooftop_telecom_antenna": (
        "Tenant may install, at its cost, <b>one (1) satellite dish and "
        "supplemental telecom antennae</b> in a designated rooftop area, with "
        "screened access and a license fee of <b>$500 per month</b>, removable at "
        "the end of the term."
    ),
    "go_dark_co_tenancy": (
        "Tenant may <b>cease operations (go dark)</b> while continuing to pay "
        "Rent. If Building occupancy falls below <b>70%</b> for more than "
        "<b>twelve (12) consecutive months</b>, Tenant may pay <b>50% reduced "
        "rent</b> or terminate on ninety (90) days' notice."
    ),
    "asc842_ifrs16_elections": (
        "For accounting purposes the parties acknowledge this is an "
        "<b>operating lease</b> under <b>ASC 842</b>. Tenant has elected the "
        "<b>short-term lease and low-value asset practical expedients where "
        "applicable</b> and uses an <b>incremental borrowing rate of 6.5%</b> to "
        "measure the lease liability."
    ),
    "notices": (
        "All notices must be in writing and delivered by hand, nationally "
        "recognized overnight courier, or certified mail to Landlord at 455 "
        "Market Plaza, Suite 100, San Francisco, CA 94105 and to Tenant at the "
        "Premises, with a courtesy copy by email. Notice is deemed given on "
        "receipt or refusal."
    ),
    "surrender_restoration": (
        "Upon expiration Tenant shall surrender the Premises in good condition, "
        "broom-clean, ordinary wear and tear excepted, and shall remove its "
        "trade fixtures and any <b>required-removal alterations</b> identified by "
        "Landlord at the time of approval, repairing any resulting damage."
    ),
    "security_deposit": (
        "Tenant has deposited a <b>security deposit of $57,000.00</b> (two "
        "months' Base Rent), held without interest, which may be provided as an "
        "<b>unconditional letter of credit</b>. The deposit burns down to "
        "<b>$28,500.00</b> after the 36th month absent any default."
    ),
    "exclusivity_permitted_use": (
        "The Premises shall be used <b>solely for general office and software-"
        "development purposes</b> and for no other use. Tenant's use must comply "
        "with all laws, the certificate of occupancy, and recorded covenants."
    ),
    "insurance": (
        "Tenant shall maintain <b>commercial general liability insurance of "
        "$2,000,000 per occurrence / $5,000,000 aggregate</b>, property insurance "
        "on its personal property and improvements at full replacement cost, "
        "workers' compensation, and <b>$5,000,000 umbrella</b> coverage, naming "
        "Landlord as additional insured, with a mutual <b>waiver of "
        "subrogation</b>."
    ),
    "estoppel_snda": (
        "Tenant shall deliver an <b>estoppel certificate within ten (10) "
        "business days</b> of request. This Lease is <b>subordinate</b> to "
        "current and future mortgages, conditioned on the lender delivering a "
        "commercially reasonable <b>subordination, non-disturbance and attornment "
        "(SNDA)</b> agreement."
    ),
    "sublease_assignment": (
        "Tenant may not assign or sublet without Landlord's <b>prior written "
        "consent, not to be unreasonably withheld</b>. Landlord shares <b>50% of "
        "net sublease profits</b>. Transfers to an <b>affiliate or successor by "
        "merger</b> are permitted without consent."
    ),
    "lease_audit_rights": (
        "Tenant may <b>audit Landlord's books for Operating Expenses within "
        "twelve (12) months</b> after receiving the annual reconciliation. If the "
        "audit reveals an <b>overcharge exceeding 4%</b>, Landlord pays the "
        "reasonable cost of the audit and refunds the overcharge."
    ),
    "hvac_additional_usage": (
        "Landlord furnishes <b>HVAC during Building hours (7:00 a.m. - 6:00 p.m. "
        "weekdays, 8:00 a.m. - 1:00 p.m. Saturdays)</b>. <b>After-hours HVAC</b> "
        "is available at <b>$75 per hour per zone</b>. Tenant maintains any "
        "supplemental units serving the Premises."
    ),
    "sublease_information": (
        "As of the Effective Date there is <b>no existing sublease</b> affecting "
        "the Premises. Any future sublease shall be reported to Landlord with the "
        "subtenant's name, demised area, term, and rent within ten (10) days of "
        "execution."
    ),
    "rea": (
        "The Building is subject to a recorded <b>Reciprocal Easement Agreement "
        "(REA)</b> dated June 1, 2008 governing shared parking, access drives, "
        "and common-area maintenance, to which this Lease is subordinate and with "
        "which Tenant shall comply."
    ),
    "maintenance_repairs": (
        "Landlord maintains the structure, roof, exterior, and building systems. "
        "<b>Tenant maintains the interior of the Premises</b>, including fixtures "
        "and non-structural elements, and pays for repairs caused by its acts. "
        "Tenant shall report needed repairs promptly."
    ),
    "hazardous_materials": (
        "Tenant shall not use, store, or dispose of <b>Hazardous Materials</b> "
        "except customary office supplies in compliance with law, and indemnifies "
        "Landlord for any contamination it causes. Landlord represents the "
        "Premises are <b>free of known hazardous materials</b> as of delivery."
    ),
    "utilities_services": (
        "Electricity to the Premises is <b>separately metered</b> and paid by "
        "Tenant. Landlord provides water, sewer, elevator, common-area lighting, "
        "and <b>five (5) days per week janitorial service</b>. Tenant pays for "
        "telephone, data, and any excess-capacity consumption."
    ),
    "other_critical_issues": (
        "Tenant is allotted <b>three (3) unreserved parking spaces per 1,000 "
        "rentable square feet</b> (26 spaces) at prevailing market rates and "
        "holds a one-time <b>early-termination option effective at the end of "
        "month 48</b> on nine (9) months' notice and payment of a termination fee "
        "equal to unamortized transaction costs plus four months' Base Rent."
    ),
}


def _intro_flow(styles) -> list:
    flow: list = []
    flow.append(Paragraph("COMMERCIAL OFFICE LEASE AGREEMENT", styles["TitleX"]))
    flow.append(Spacer(1, 6))
    flow.append(
        Paragraph(
            "This Commercial Office Lease Agreement (the &ldquo;Lease&rdquo;) is "
            "made as of <b>January 1, 2025</b> (the &ldquo;Effective Date&rdquo;) "
            "by and between <b>Greenfield Property Holdings, LLC</b>, a Delaware "
            "limited liability company (&ldquo;Landlord&rdquo;), and <b>Northwind "
            "Analytics, Inc.</b>, a California corporation (&ldquo;Tenant&rdquo;), "
            "for premises known as <b>Suite 1200, 455 Market Plaza, San "
            "Francisco, California 94105</b>. This Lease shall be identified for "
            "reference as <b>Northwind Analytics &ndash; Suite 1200</b>.",
            styles["BodyX"],
        )
    )
    flow.append(Spacer(1, 6))
    return flow


def _signature_flow(styles) -> list:
    return [
        Spacer(1, 10),
        Paragraph(
            "IN WITNESS WHEREOF, the parties have executed this Lease as of the "
            "Effective Date first written above.",
            styles["BodyX"],
        ),
        Spacer(1, 8),
        Paragraph(
            "LANDLORD: Greenfield Property Holdings, LLC<br/><br/>"
            "By: ______________________________<br/><br/>"
            "TENANT: Northwind Analytics, Inc.<br/><br/>"
            "By: ______________________________",
            styles["BodyX"],
        ),
    ]


def build() -> None:
    missing = [c["key"] for c in CLAUSE_CATEGORIES if c["key"] not in CLAUSE_PROSE]
    if missing:
        raise SystemExit(
            "Missing lease prose for abstract categories: " + ", ".join(missing)
        )

    base = getSampleStyleSheet()
    styles = base
    styles.add(ParagraphStyle("TitleX", parent=base["Title"], fontSize=16, spaceAfter=14))
    styles.add(
        ParagraphStyle("H2X", parent=base["Heading2"], fontSize=11.5, spaceBefore=10, spaceAfter=3)
    )
    styles.add(
        ParagraphStyle("BodyX", parent=base["BodyText"], fontSize=10, leading=14, spaceAfter=6)
    )

    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        title="Sample Commercial Lease (Full Abstract)",
        author="Portfolio Desk sample data",
    )

    flow = _intro_flow(styles)
    # Render one numbered article per catalog category, in catalog order
    # (financial → clauses → rights, each ordered by ``order``).
    ordered = sorted(
        CLAUSE_CATEGORIES,
        key=lambda c: ({"financial": 0, "clauses": 1, "rights": 2}.get(c["group"], 9), c["order"]),
    )
    for idx, cat in enumerate(ordered, start=1):
        flow.append(Paragraph(f"{idx}. {cat['name']}", styles["H2X"]))
        flow.append(Paragraph(CLAUSE_PROSE[cat["key"]], styles["BodyX"]))

    flow.extend(_signature_flow(styles))
    doc.build(flow)
    print(f"Wrote {OUTPUT} covering {len(ordered)} abstract categories")


if __name__ == "__main__":
    build()
