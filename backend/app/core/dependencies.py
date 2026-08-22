from collections.abc import Callable

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Role, User, UserRole
from app.core.security import get_subject

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    subject = get_subject(token)
    user = db.scalar(select(User).where(User.email == subject)) if subject else None
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def user_roles(user: User, db: Session) -> set[str]:
    rows = db.execute(select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)).scalars()
    return set(rows)


def require_roles(*allowed: str) -> Callable[..., User]:
    def dependency(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if not user_roles(user, db).intersection(allowed):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return dependency


require_admin = require_roles("ADMIN")
require_manager = require_roles("ADMIN", "MANAGER")
require_agent = require_roles("ADMIN", "MANAGER", "AGENT")
