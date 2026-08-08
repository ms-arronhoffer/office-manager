"""Catalog of customisable emails, their merge fields, and built-in defaults.

This is the contract between the product and an administrator editing their
mail. Each entry declares:

* the copy the product ships with, so "reset to default" always has a target;
* the merge fields that are genuinely available for that message, so the editor
  can offer a palette instead of inviting the admin to guess; and
* a realistic sample value per field, so a preview looks like a real email
  rather than a page of ``{{placeholders}}``.

Adding a new customisable email means adding an entry here and calling
:func:`app.services.email_template_service.render` at the send site.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MergeField:
    """A placeholder an admin may use in a subject or body."""

    name: str
    label: str
    sample: str


@dataclass(frozen=True)
class TemplateDefinition:
    key: str
    label: str
    category: str
    description: str
    default_subject: str
    default_body: str
    merge_fields: list[MergeField] = field(default_factory=list)


# Fields every message can use, injected automatically alongside the
# message-specific ones below.
COMMON_FIELDS: list[MergeField] = [
    MergeField("organization_name", "Organization name", "Acme Property Care"),
    MergeField("recipient_name", "Recipient name", "Dana Whitfield"),
    MergeField("today", "Today's date", "August 8, 2026"),
]


def _defn(
    key: str,
    label: str,
    category: str,
    description: str,
    subject: str,
    body: str,
    fields: list[MergeField],
) -> TemplateDefinition:
    return TemplateDefinition(
        key=key,
        label=label,
        category=category,
        description=description,
        default_subject=subject,
        default_body=body,
        merge_fields=COMMON_FIELDS + fields,
    )


TEMPLATE_CATALOG: dict[str, TemplateDefinition] = {
    t.key: t
    for t in [
        _defn(
            "lease_expiration",
            "Lease expiration reminder",
            "Leases",
            "Sent to the recipients on your lease reminder rules as an expiration approaches.",
            "{{lease_name}} expires in {{days_until}} days",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>The lease <strong>{{lease_name}}</strong> at {{office_name}} expires on "
            "<strong>{{expiration_date}}</strong>, which is {{days_until}} day(s) away.</p>\n"
            "<p>Please confirm whether {{organization_name}} intends to renew, renegotiate "
            "or vacate so the notice deadline is not missed.</p>",
            [
                MergeField("lease_name", "Lease name", "Harbor View Tower - Suite 400"),
                MergeField("office_name", "Office / property", "Harbor View Tower"),
                MergeField("expiration_date", "Expiration date", "May 4, 2027"),
                MergeField("days_until", "Days until expiration", "90"),
                MergeField("manager_name", "Lease manager", "Marcus Delgado"),
            ],
        ),
        _defn(
            "lease_notice",
            "Lease notice deadline",
            "Leases",
            "Warns that the contractual notice date is approaching, which is the deadline that actually binds.",
            "Action required: notice for {{lease_name}} due {{notice_date}}",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>Written notice for <strong>{{lease_name}}</strong> must be served by "
            "<strong>{{notice_date}}</strong> ({{days_until}} day(s) from today).</p>\n"
            "<p>After this date the lease renews automatically under its existing terms.</p>",
            [
                MergeField("lease_name", "Lease name", "Cedar Ridge Commons - Floor 2"),
                MergeField("notice_date", "Notice due date", "September 6, 2026"),
                MergeField("days_until", "Days until notice due", "21"),
                MergeField("notice_period", "Notice period", "90 days"),
                MergeField("manager_name", "Lease manager", "Marcus Delgado"),
            ],
        ),
        _defn(
            "renewal_notice",
            "Renewal notice to landlord",
            "Leases",
            "The notice itself, sent to the landlord or their agent when you exercise or decline a renewal.",
            "Notice regarding {{lease_name}}",
            "<p>Dear {{recipient_name}},</p>\n"
            "<p>This letter constitutes formal notice from {{organization_name}} regarding the "
            "lease known as <strong>{{lease_name}}</strong>, currently expiring on "
            "{{expiration_date}}.</p>\n"
            "<p>{{notice_body}}</p>\n"
            "<p>Please acknowledge receipt of this notice.</p>",
            [
                MergeField("lease_name", "Lease name", "Meridian Plaza - Full Floor 12"),
                MergeField("expiration_date", "Current expiration", "December 29, 2031"),
                MergeField(
                    "notice_body",
                    "Notice wording",
                    "We intend to exercise our renewal option for a further 60 months.",
                ),
            ],
        ),
        _defn(
            "coi_expiration",
            "Insurance certificate expiring",
            "Compliance",
            "Chases a vendor or landlord whose certificate of insurance is about to lapse.",
            "Your certificate of insurance expires {{expiration_date}}",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>Our records show your <strong>{{certificate_type}}</strong> certificate "
            "(policy {{policy_number}}, {{insurer}}) expires on <strong>{{expiration_date}}</strong>.</p>\n"
            "<p>Please upload a current certificate to remain approved for work with "
            "{{organization_name}}.</p>",
            [
                MergeField("certificate_type", "Certificate type", "General Liability"),
                MergeField("policy_number", "Policy number", "GL-4471902"),
                MergeField("insurer", "Insurer", "Continental Mutual"),
                MergeField("expiration_date", "Expiration date", "September 30, 2026"),
                MergeField("days_until", "Days until expiry", "30"),
            ],
        ),
        _defn(
            "hvac_service",
            "HVAC service due",
            "Maintenance",
            "Reminds the responsible party that contracted HVAC service is due.",
            "HVAC service due at {{office_name}} in {{days_until}} days",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>Scheduled HVAC service for <strong>{{office_name}}</strong> is due on "
            "<strong>{{service_date}}</strong>.</p>\n"
            "<p>Contractor: {{vendor_name}} ({{frequency}} service).</p>",
            [
                MergeField("office_name", "Office / property", "Harbor View Tower"),
                MergeField("vendor_name", "Contractor", "Bluepeak HVAC & Mechanical"),
                MergeField("service_date", "Service date", "September 12, 2026"),
                MergeField("frequency", "Service frequency", "Quarterly"),
                MergeField("days_until", "Days until due", "14"),
            ],
        ),
        _defn(
            "ticket_created",
            "Maintenance request logged",
            "Maintenance",
            "Confirms to the requester and the assigned team that a work order exists.",
            "Work order {{ticket_number}}: {{subject}}",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>A maintenance request has been logged for <strong>{{office_name}}</strong>.</p>\n"
            "<p><strong>{{subject}}</strong><br/>Priority: {{priority}} &middot; "
            "Category: {{category}}</p>\n"
            "<p>{{description}}</p>",
            [
                MergeField("ticket_number", "Work order number", "WO-10482"),
                MergeField("subject", "Subject", "Rooftop unit short-cycling"),
                MergeField("office_name", "Office / property", "Harbor View Tower"),
                MergeField("priority", "Priority", "High"),
                MergeField("category", "Category", "HVAC"),
                MergeField(
                    "description",
                    "Description",
                    "Unit 3 is cycling every few minutes and not holding temperature.",
                ),
            ],
        ),
        _defn(
            "ticket_high_priority",
            "High-priority maintenance alert",
            "Maintenance",
            "Escalation sent immediately when a high-priority work order is raised.",
            "URGENT: {{subject}} at {{office_name}}",
            "<p>A high-priority maintenance issue has been reported.</p>\n"
            "<p><strong>{{subject}}</strong><br/>{{office_name}} &middot; {{category}}</p>\n"
            "<p>{{description}}</p>\n"
            "<p>Reported by {{created_by}}.</p>",
            [
                MergeField("subject", "Subject", "Water ingress in main lobby"),
                MergeField("office_name", "Office / property", "Meridian Plaza"),
                MergeField("category", "Category", "Plumbing"),
                MergeField("description", "Description", "Standing water near the lift lobby."),
                MergeField("created_by", "Reported by", "Ava Whitmore"),
            ],
        ),
        _defn(
            "work_order_assigned",
            "Work order assigned to vendor",
            "Maintenance",
            "Tells a vendor what they have been asked to do and where.",
            "New work order for {{office_name}}: {{subject}}",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>{{organization_name}} has assigned you a work order.</p>\n"
            "<p><strong>{{subject}}</strong><br/>{{office_name}}<br/>"
            "Priority: {{priority}}</p>\n"
            "<p>{{description}}</p>\n"
            "<p>Please confirm attendance and update the work order when complete: "
            "{{portal_url}}</p>",
            [
                MergeField("subject", "Subject", "Rooftop unit short-cycling"),
                MergeField("office_name", "Office / property", "Harbor View Tower"),
                MergeField("priority", "Priority", "High"),
                MergeField("description", "Description", "Compressor suspected faulty."),
                MergeField("portal_url", "Vendor portal link", "https://app.example.com/vendor-portal"),
            ],
        ),
        _defn(
            "portal_invite",
            "Portal invitation",
            "Portals",
            "Invites a landlord, vendor, resident or owner to activate their portal access.",
            "{{organization_name}} has invited you to the {{portal_name}}",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>{{organization_name}} has set up access for you to the "
            "<strong>{{portal_name}}</strong>, where you can review your documents and "
            "submit requests.</p>\n"
            "<p><a href=\"{{invite_url}}\">Activate your account</a></p>\n"
            "<p>This invitation expires on {{expires_at}}.</p>",
            [
                MergeField("portal_name", "Portal name", "Client Portal"),
                MergeField("invite_url", "Invitation link", "https://app.example.com/client-portal/signup"),
                MergeField("expires_at", "Invitation expiry", "August 22, 2026"),
            ],
        ),
        _defn(
            "weekly_summary",
            "Weekly portfolio summary",
            "Reporting",
            "The Monday digest of what needs attention across the portfolio.",
            "Portfolio summary for week of {{week_of}}",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>Here is the {{organization_name}} portfolio summary for the week of "
            "{{week_of}}.</p>\n"
            "<ul>\n"
            "  <li>Open work orders: {{open_tickets}}</li>\n"
            "  <li>Overdue work orders: {{overdue_tickets}}</li>\n"
            "  <li>Leases expiring within 30 days: {{leases_expiring}}</li>\n"
            "</ul>",
            [
                MergeField("week_of", "Week of", "August 3, 2026"),
                MergeField("open_tickets", "Open work orders", "12"),
                MergeField("overdue_tickets", "Overdue work orders", "3"),
                MergeField("leases_expiring", "Leases expiring (30d)", "2"),
            ],
        ),
        _defn(
            "approval_request",
            "Approval request",
            "Finance",
            "Asks a second reviewer to approve a bill, invoice or requisition.",
            "Approval needed: {{document_type}} {{document_number}}",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>{{prepared_by}} has submitted a {{document_type}} for your approval.</p>\n"
            "<p><strong>{{document_number}}</strong><br/>"
            "Amount: {{amount}}<br/>Vendor / customer: {{counterparty}}</p>\n"
            "<p><a href=\"{{review_url}}\">Review and approve</a></p>",
            [
                MergeField("document_type", "Document type", "vendor bill"),
                MergeField("document_number", "Document number", "BP-77301"),
                MergeField("amount", "Amount", "$18,500.00"),
                MergeField("counterparty", "Vendor / customer", "Bluepeak HVAC & Mechanical"),
                MergeField("prepared_by", "Prepared by", "Dana Preparer"),
                MergeField("review_url", "Review link", "https://app.example.com/finance/accounts-payable"),
            ],
        ),
        _defn(
            "waiver_request",
            "Signature request",
            "Documents",
            "Asks a visitor, contractor or tenant to sign a document electronically.",
            "Signature requested: {{document_name}}",
            "<p>Hello {{recipient_name}},</p>\n"
            "<p>{{organization_name}} has requested your signature on "
            "<strong>{{document_name}}</strong>.</p>\n"
            "<p><a href=\"{{sign_url}}\">Review and sign</a></p>\n"
            "<p>This request expires on {{expires_at}}.</p>",
            [
                MergeField("document_name", "Document name", "Contractor Site Access Waiver"),
                MergeField("sign_url", "Signing link", "https://app.example.com/sign/abc123"),
                MergeField("expires_at", "Expires", "August 22, 2026"),
            ],
        ),
    ]
}

# Grouping used by the UI to organise the template list.
CATEGORIES = ["Leases", "Compliance", "Maintenance", "Portals", "Finance", "Reporting", "Documents"]


def get(template_key: str) -> TemplateDefinition | None:
    return TEMPLATE_CATALOG.get(template_key)


def sample_context(template_key: str) -> dict[str, str]:
    """Realistic values for every merge field, used to render a preview."""
    definition = TEMPLATE_CATALOG.get(template_key)
    if definition is None:
        return {}
    return {f.name: f.sample for f in definition.merge_fields}
