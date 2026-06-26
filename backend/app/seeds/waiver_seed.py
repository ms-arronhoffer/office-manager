"""Prebuilt digital-waiver template library.

These are seeded per organization (lazily, on first access) with
``is_prebuilt=True`` so an org always has a starting library it can send as-is
or copy/customise. Bodies support ``{{merge_field}}`` placeholders that are
substituted at send time (see ``app.services.waiver_service.render_body``).

Available merge fields:
  - ``{{recipient_name}}`` / ``{{signer_name}}``
  - ``{{organization_name}}``
  - ``{{date}}``
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.waiver import WaiverTemplate

PREBUILT_WAIVER_TEMPLATES: list[dict] = [
    {
        "prebuilt_key": "visitor_liability",
        "name": "Visitor Liability Waiver",
        "description": "General liability release for site visitors and guests.",
        "body": (
            "VISITOR LIABILITY WAIVER AND RELEASE\n\n"
            "This waiver is entered into on {{date}} between {{organization_name}} "
            "(\"the Company\") and {{recipient_name}} (\"the Visitor\").\n\n"
            "In consideration of being permitted to enter the Company's premises, "
            "the Visitor acknowledges and agrees to the following:\n\n"
            "1. The Visitor enters the premises at their own risk and assumes all "
            "risks of personal injury, illness, or property damage.\n"
            "2. The Visitor releases and holds harmless the Company, its employees, "
            "and agents from any and all liability arising from the Visitor's "
            "presence on the premises, except in cases of gross negligence or "
            "willful misconduct.\n"
            "3. The Visitor agrees to comply with all posted safety rules and the "
            "directions of Company personnel while on the premises.\n\n"
            "By signing below, the Visitor confirms they have read and understood "
            "this waiver and agree to its terms."
        ),
    },
    {
        "prebuilt_key": "contractor_site_access",
        "name": "Contractor Site Access Waiver",
        "description": "Site-access and safety acknowledgment for contractors and vendors.",
        "body": (
            "CONTRACTOR SITE ACCESS AGREEMENT\n\n"
            "This agreement is made on {{date}} between {{organization_name}} "
            "(\"the Company\") and {{recipient_name}} (\"the Contractor\").\n\n"
            "The Contractor agrees that:\n\n"
            "1. The Contractor is properly licensed and insured to perform the work "
            "for which access is granted.\n"
            "2. The Contractor will comply with all site safety requirements, "
            "applicable laws, and Company policies.\n"
            "3. The Contractor assumes responsibility for its personnel and "
            "equipment while on the premises and releases the Company from "
            "liability for loss or damage except in cases of the Company's gross "
            "negligence.\n"
            "4. The Contractor will report any incident, injury, or property damage "
            "to the Company immediately.\n\n"
            "By signing below, the Contractor acknowledges and accepts these terms."
        ),
    },
    {
        "prebuilt_key": "photo_consent",
        "name": "Photo & Media Consent",
        "description": "Consent to capture and use photographs or video on premises.",
        "body": (
            "PHOTOGRAPH AND MEDIA CONSENT\n\n"
            "On {{date}}, {{recipient_name}} grants {{organization_name}} permission "
            "to capture and use photographs, video, or audio recordings taken on the "
            "premises for internal documentation and promotional purposes.\n\n"
            "This consent may be withdrawn in writing at any time for future use. By "
            "signing below, {{signer_name}} agrees to the terms above."
        ),
    },
]


async def seed_prebuilt_templates_for_org(db: AsyncSession, organization_id) -> None:
    """Ensure the prebuilt template library exists for ``organization_id``.

    Idempotent: only inserts prebuilt templates whose ``prebuilt_key`` is not yet
    present for the org. Does not commit; the caller owns the transaction.
    """
    result = await db.execute(
        select(WaiverTemplate.prebuilt_key).where(
            WaiverTemplate.organization_id == organization_id,
            WaiverTemplate.is_prebuilt.is_(True),
        )
    )
    existing = {row for row in result.scalars().all() if row}
    for tpl in PREBUILT_WAIVER_TEMPLATES:
        if tpl["prebuilt_key"] in existing:
            continue
        db.add(
            WaiverTemplate(
                organization_id=organization_id,
                name=tpl["name"],
                description=tpl["description"],
                body=tpl["body"],
                is_prebuilt=True,
                prebuilt_key=tpl["prebuilt_key"],
                is_active=True,
            )
        )
