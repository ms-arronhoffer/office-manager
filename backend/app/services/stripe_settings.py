"""Resolve effective Stripe integration settings.

Precedence: values configured in the admin console (persisted in
:class:`~app.models.platform_stripe_config.PlatformStripeConfig`, secrets
encrypted at rest) take priority over the ``STRIPE_*`` environment variables.
When the DB row is absent or disabled, or a particular field is unset, the
environment value is used as a fallback. This keeps existing env-based
deployments working while allowing credentials to be established/rotated from
the console (mirroring the SMTP/Gemini "optional integration" convention).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as env_settings
from app.models.platform_stripe_config import PlatformStripeConfig
from app.utils.crypto import decrypt_secret


@dataclass(frozen=True)
class StripeSettings:
    secret_key: str
    webhook_secret: str
    price_id_starter: str
    price_id_pro: str
    # Enterprise is custom-priced per subscriber, so we track its Stripe Product
    # (which owns every subscriber's bespoke price) rather than a single price id.
    product_id_enterprise: str

    @property
    def configured(self) -> bool:
        return bool(self.secret_key)


async def get_stripe_config(db: AsyncSession) -> PlatformStripeConfig | None:
    """Return the singleton platform Stripe config row, if any."""
    return (await db.execute(select(PlatformStripeConfig))).scalars().first()


async def resolve_stripe_settings(db: AsyncSession) -> StripeSettings:
    """Resolve effective Stripe settings with DB-over-env precedence."""
    cfg = await get_stripe_config(db)

    secret_key = ""
    webhook_secret = ""
    price_starter = ""
    price_pro = ""
    product_enterprise = ""

    if cfg is not None and cfg.is_enabled:
        if cfg.secret_key_encrypted:
            secret_key = decrypt_secret(cfg.secret_key_encrypted)
        if cfg.webhook_secret_encrypted:
            webhook_secret = decrypt_secret(cfg.webhook_secret_encrypted)
        price_starter = cfg.price_id_starter or ""
        price_pro = cfg.price_id_pro or ""
        product_enterprise = cfg.product_id_enterprise or ""

    return StripeSettings(
        secret_key=secret_key or env_settings.STRIPE_SECRET_KEY,
        webhook_secret=webhook_secret or env_settings.STRIPE_WEBHOOK_SECRET,
        price_id_starter=price_starter or env_settings.STRIPE_PRICE_ID_STARTER,
        price_id_pro=price_pro or env_settings.STRIPE_PRICE_ID_PRO,
        product_id_enterprise=product_enterprise or env_settings.STRIPE_PRODUCT_ID_ENTERPRISE,
    )


async def resolve_stripe_secret_key(db: AsyncSession) -> str:
    """Convenience: resolve just the effective Stripe secret key."""
    return (await resolve_stripe_settings(db)).secret_key
