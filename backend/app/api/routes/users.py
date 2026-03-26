from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.deps import CurrentUser

router = APIRouter(prefix="/me", tags=["me"])


class MeOut(BaseModel):
    id: str
    email: str


@router.get("", response_model=MeOut)
async def me(user: CurrentUser) -> MeOut:
    return MeOut(id=str(user.id), email=user.email)
