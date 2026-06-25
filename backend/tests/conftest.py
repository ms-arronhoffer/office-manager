import asyncio
import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Point at the test database BEFORE importing app code
os.environ["POSTGRES_DB"] = "office_manager_test"
os.environ["DATABASE_URL"] = ""
os.environ["DATABASE_URL_SYNC"] = ""

from app.auth.jwt_handler import create_access_token  # noqa: E402
from app.auth.password import hash_password  # noqa: E402
from app.config import Settings  # noqa: E402
from app.database import get_db  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.office import Manager, Office  # noqa: E402
from app.models.maintenance_ticket import TicketCategory, MaintenanceTicket  # noqa: E402


# Build test settings (picks up POSTGRES_DB=office_manager_test)
_settings = Settings()

_test_engine = create_async_engine(_settings.DATABASE_URL, echo=False)
_test_session = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Create all tables once per test session."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _test_engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Per-test database session with rollback."""
    async with _test_session() as session:
        yield session
        # Clean up data after each test
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))
        await session.commit()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTPX async client wired to the test database."""
    from app.main import app

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ─── Seed data helpers ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin@test.com",
        display_name="Test Admin",
        password_hash=hash_password("admin123"),
        auth_provider="internal",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def editor_user(db_session: AsyncSession) -> User:
    user = User(
        email="editor@test.com",
        display_name="Test Editor",
        password_hash=hash_password("editor123"),
        auth_provider="internal",
        role="editor",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def viewer_user(db_session: AsyncSession) -> User:
    user = User(
        email="viewer@test.com",
        display_name="Test Viewer",
        password_hash=hash_password("viewer123"),
        auth_provider="internal",
        role="viewer",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    """Generate Authorization header for a user."""
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def sample_office(db_session: AsyncSession) -> Office:
    office = Office(
        office_number=100,
        region_number=1,
        location_type="office",
        location_name="Test Office",
        is_active=True,
    )
    db_session.add(office)
    await db_session.commit()
    await db_session.refresh(office)
    return office


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> TicketCategory:
    cat = TicketCategory(name="Plumbing")
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    return cat
