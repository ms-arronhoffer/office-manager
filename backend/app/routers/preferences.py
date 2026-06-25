from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.preferences import UserPreferences

router = APIRouter()


@router.get("/me/preferences", response_model=UserPreferences)
async def get_preferences(current_user: User = Depends(get_current_user)):
    if current_user.preferences:
        return UserPreferences(**current_user.preferences)
    return UserPreferences()


@router.put("/me/preferences", response_model=UserPreferences)
async def update_preferences(
    payload: UserPreferences,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.preferences = payload.model_dump()
    await db.commit()
    return payload
