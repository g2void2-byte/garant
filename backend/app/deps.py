from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import async_session
from .models import User
from .security import InitDataError, verify_init_data


async def get_session():
    async with async_session() as session:
        yield session


async def get_current_user(
    authorization: Annotated[str, Header()],
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization.lower().startswith("tma "):
        raise HTTPException(401, "Invalid Authorization header")

    init_data = authorization[4:]
    try:
        tg_user = verify_init_data(init_data)
    except InitDataError as e:
        raise HTTPException(401, str(e))

    tg_user_id = tg_user.get("id")
    if not tg_user_id:
        raise HTTPException(401, "User ID not found in init data")

    stmt = select(User).where(User.tg_user_id == tg_user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            tg_user_id=tg_user_id,
            username=tg_user.get("username"),
            display_name=tg_user.get("first_name", ""),
            photo_url=tg_user.get("photo_url"),
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    elif tg_user.get("username") and user.username != tg_user["username"]:
        user.username = tg_user["username"]
        await session.commit()
        await session.refresh(user)

    return user


SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
