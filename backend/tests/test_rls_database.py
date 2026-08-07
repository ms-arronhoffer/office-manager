import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.customer_invoice import Customer
from app.models.organization import Organization


_ROLE = "office_manager_rls_test"
_POLICY = "customers_org_isolation_test"
_PREDICATE = """
current_setting('app.rls_bypass', true) = 'on'
OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
"""


@pytest.mark.asyncio
async def test_database_rls_fail_closed_write_check_and_bypass(db_session) -> None:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    customer_a = uuid.uuid4()
    customer_b = uuid.uuid4()

    db_session.add_all(
        [
            Organization(id=org_a, name="RLS A", slug=f"rls-a-{org_a}"),
            Organization(id=org_b, name="RLS B", slug=f"rls-b-{org_b}"),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            Customer(id=customer_a, organization_id=org_a, name="A"),
            Customer(id=customer_b, organization_id=org_b, name="B"),
        ]
    )
    await db_session.commit()

    await db_session.execute(text(f'DROP ROLE IF EXISTS "{_ROLE}"'))
    await db_session.execute(text(f'CREATE ROLE "{_ROLE}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
    await db_session.execute(text(f'GRANT USAGE ON SCHEMA public TO "{_ROLE}"'))
    await db_session.execute(
        text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON customers TO "{_ROLE}"')
    )
    await db_session.execute(text(f'DROP POLICY IF EXISTS "{_POLICY}" ON customers'))
    await db_session.execute(text("ALTER TABLE customers ENABLE ROW LEVEL SECURITY"))
    await db_session.execute(text("ALTER TABLE customers FORCE ROW LEVEL SECURITY"))
    await db_session.execute(
        text(
            f'CREATE POLICY "{_POLICY}" ON customers '
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )
    )
    await db_session.commit()

    try:
        await db_session.execute(text(f'SET ROLE "{_ROLE}"'))

        # Unset context fails closed.
        assert (await db_session.scalar(text("SELECT count(*) FROM customers"))) == 0

        await db_session.execute(
            text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_a)}
        )
        assert (await db_session.scalar(text("SELECT count(*) FROM customers"))) == 1

        # WITH CHECK rejects a cross-tenant write at the database boundary.
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(
                        "INSERT INTO customers "
                        "(id, organization_id, name, created_at, updated_at) "
                        "VALUES (:id, :org, 'blocked', now(), now())"
                    ),
                    {"id": uuid.uuid4(), "org": org_b},
                )

        await db_session.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))
        assert (await db_session.scalar(text("SELECT count(*) FROM customers"))) == 2

        # Both settings are transaction-local and disappear after commit.
        await db_session.commit()
        await db_session.execute(text(f'SET ROLE "{_ROLE}"'))
        assert (await db_session.scalar(text("SELECT count(*) FROM customers"))) == 0
    finally:
        await db_session.rollback()
        await db_session.execute(text("RESET ROLE"))
        await db_session.execute(text(f'DROP POLICY IF EXISTS "{_POLICY}" ON customers'))
        await db_session.execute(text("ALTER TABLE customers NO FORCE ROW LEVEL SECURITY"))
        await db_session.execute(text("ALTER TABLE customers DISABLE ROW LEVEL SECURITY"))
        await db_session.execute(text(f'DROP OWNED BY "{_ROLE}"'))
        await db_session.execute(text(f'DROP ROLE IF EXISTS "{_ROLE}"'))
        await db_session.commit()
