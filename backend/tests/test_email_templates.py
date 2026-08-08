"""Tests for email customisation: merge fields, branding and fallbacks."""

import uuid

import pytest

from app.models.email_branding import (
    DEFAULT_ACCENT_COLOR,
    DEFAULT_HEADER_COLOR,
    EmailBranding,
    EmailTemplate,
)
from app.services import email_catalog, email_template_service


# ─── Merge field substitution ────────────────────────────────────────────────

def test_substitute_replaces_known_fields():
    result = email_template_service.substitute(
        "Hello {{recipient_name}}, {{lease_name}} expires soon.",
        {"recipient_name": "Dana", "lease_name": "Suite 400"},
    )
    assert result == "Hello Dana, Suite 400 expires soon."


def test_substitute_tolerates_whitespace_in_placeholder():
    assert (
        email_template_service.substitute("Hi {{  recipient_name  }}", {"recipient_name": "Dana"})
        == "Hi Dana"
    )


def test_substitute_blanks_missing_values_rather_than_raising():
    """A missing value must never crash a send; it renders as empty."""
    assert email_template_service.substitute("Hi {{nobody}}!", {}) == "Hi !"


def test_substitute_handles_empty_source():
    assert email_template_service.substitute("", {"a": "b"}) == ""


# ─── Editor safety net ───────────────────────────────────────────────────────

def test_unknown_fields_flags_a_typo():
    unknown = email_template_service.unknown_fields(
        "{{lease_name}} and {{leese_name}}", "lease_expiration"
    )
    assert unknown == ["leese_name"]


def test_unknown_fields_accepts_common_fields():
    assert (
        email_template_service.unknown_fields(
            "{{organization_name}} {{recipient_name}} {{today}}", "lease_expiration"
        )
        == []
    )


def test_unknown_fields_for_unknown_template_flags_everything():
    assert email_template_service.unknown_fields("{{x}}", "no_such_template") == ["x"]


# ─── Catalog integrity ───────────────────────────────────────────────────────

def test_every_catalog_default_only_uses_declared_fields():
    """A shipped default that references an undeclared field would render blank."""
    for key, definition in email_catalog.TEMPLATE_CATALOG.items():
        combined = f"{definition.default_subject}\n{definition.default_body}"
        assert email_template_service.unknown_fields(combined, key) == [], (
            f"{key} references undeclared merge fields"
        )


def test_sample_context_covers_all_merge_fields():
    for key, definition in email_catalog.TEMPLATE_CATALOG.items():
        context = email_catalog.sample_context(key)
        for merge_field in definition.merge_fields:
            assert merge_field.name in context


def test_sample_render_leaves_no_placeholders():
    """A preview must look like an email, not a page of braces."""
    for key, definition in email_catalog.TEMPLATE_CATALOG.items():
        rendered = email_template_service.substitute(
            definition.default_body, email_catalog.sample_context(key)
        )
        assert "{{" not in rendered


def test_catalog_categories_are_known():
    for definition in email_catalog.TEMPLATE_CATALOG.values():
        assert definition.category in email_catalog.CATEGORIES


def test_get_returns_none_for_unknown_key():
    assert email_catalog.get("does_not_exist") is None


# ─── Branding wrapper ────────────────────────────────────────────────────────

def _branding(**kwargs) -> EmailBranding:
    defaults = dict(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        header_color=DEFAULT_HEADER_COLOR,
        accent_color=DEFAULT_ACCENT_COLOR,
        is_active=True,
    )
    defaults.update(kwargs)
    return EmailBranding(**defaults)


def test_wrap_without_branding_uses_neutral_defaults():
    html = email_template_service.wrap("<p>Body</p>", branding=None, org_name="Acme")

    assert "<p>Body</p>" in html
    assert DEFAULT_HEADER_COLOR in html
    # Falls back to the org name as the masthead when no logo is configured.
    assert "Acme" in html


def test_wrap_applies_logo_and_colors():
    html = email_template_service.wrap(
        "<p>Body</p>",
        branding=_branding(
            logo_url="https://cdn.example.com/logo.png",
            header_color="#112233",
            accent_color="#445566",
        ),
        org_name="Acme",
    )

    assert "https://cdn.example.com/logo.png" in html
    assert "#112233" in html
    assert "#445566" in html


def test_wrap_includes_signature_and_footer():
    html = email_template_service.wrap(
        "<p>Body</p>",
        branding=_branding(
            signature="Acme Facilities Team",
            footer_text="You receive this because you manage a property with Acme.",
            postal_address="1 Harbor Way, Portland OR",
        ),
        org_name="Acme",
    )

    assert "Acme Facilities Team" in html
    assert "You receive this because you manage a property with Acme." in html
    assert "1 Harbor Way, Portland OR" in html


def test_wrap_escapes_branding_to_prevent_injection():
    """Branding is admin-supplied text, not markup."""
    html = email_template_service.wrap(
        "<p>Body</p>",
        branding=_branding(signature="<script>alert(1)</script>"),
        org_name="Acme",
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_wrap_sets_preheader_from_subject():
    html = email_template_service.wrap(
        "<p>Body</p>", branding=None, org_name="Acme", preheader="Lease expires soon"
    )
    assert "Lease expires soon" in html


# ─── Override resolution ─────────────────────────────────────────────────────

class _Session:
    """Returns a fixed override / branding / organization for resolution."""

    def __init__(self, override=None, branding=None, org_name="Acme Property Care"):
        self._override = override
        self._branding = branding
        self._org_name = org_name
        self._calls = 0

    async def execute(self, _stmt):
        # render() asks for the override first, then the branding.
        value = self._override if self._calls == 0 else self._branding
        self._calls += 1

        class _Result:
            def scalar_one_or_none(self):
                return value

        return _Result()

    async def get(self, _model, _pk):
        class _Org:
            name = self._org_name

        return _Org()


@pytest.mark.asyncio
async def test_render_uses_builtin_default_when_no_override():
    rendered = await email_template_service.render(
        _Session(),
        organization_id=uuid.uuid4(),
        template_key="lease_expiration",
        context={"lease_name": "Suite 400", "days_until": "90"},
    )

    assert rendered.customized is False
    assert "Suite 400" in rendered.html_body
    assert "90" in rendered.subject


@pytest.mark.asyncio
async def test_render_prefers_an_active_override():
    override = EmailTemplate(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        template_key="lease_expiration",
        subject_template="Renewal decision needed for {{lease_name}}",
        body_template="<p>{{lease_name}} needs a decision.</p>",
        is_active=True,
    )

    rendered = await email_template_service.render(
        _Session(override=override),
        organization_id=uuid.uuid4(),
        template_key="lease_expiration",
        context={"lease_name": "Suite 400"},
    )

    assert rendered.customized is True
    assert rendered.subject == "Renewal decision needed for Suite 400"
    assert "needs a decision" in rendered.html_body


@pytest.mark.asyncio
async def test_render_falls_back_when_override_is_inactive():
    """Deactivating a customisation reverts to the shipped copy, not to blank."""
    override = EmailTemplate(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        template_key="lease_expiration",
        subject_template="Custom subject",
        body_template="<p>Custom</p>",
        is_active=False,
    )

    rendered = await email_template_service.render(
        _Session(override=override),
        organization_id=uuid.uuid4(),
        template_key="lease_expiration",
        context={"lease_name": "Suite 400", "days_until": "90"},
    )

    assert rendered.customized is False
    assert "Custom" not in rendered.html_body


@pytest.mark.asyncio
async def test_render_injects_organization_name_automatically():
    rendered = await email_template_service.render(
        _Session(org_name="Northgate Capital"),
        organization_id=uuid.uuid4(),
        template_key="portal_invite",
        context={"portal_name": "Owner Portal", "invite_url": "https://x", "expires_at": "soon"},
    )

    assert "Northgate Capital" in rendered.subject


@pytest.mark.asyncio
async def test_render_rejects_an_unknown_template():
    with pytest.raises(ValueError, match="Unknown email template"):
        await email_template_service.render(
            _Session(),
            organization_id=uuid.uuid4(),
            template_key="not_a_template",
            context={},
        )


@pytest.mark.asyncio
async def test_render_can_skip_branding_for_embedding():
    rendered = await email_template_service.render(
        _Session(),
        organization_id=uuid.uuid4(),
        template_key="lease_expiration",
        context={"lease_name": "Suite 400", "days_until": "5"},
        apply_branding=False,
    )

    assert "<!DOCTYPE html>" not in rendered.html_body
