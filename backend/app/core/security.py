from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: str


ROLE_CAPABILITIES: dict[str, set[str]] = {
    "admin": {"read", "create", "run", "review", "publish", "manage_networks"},
    "analyst": {"read", "create", "run"},
    "reviewer": {"read", "review", "publish"},
    "reader": {"read"},
}


def get_actor(
    x_user_id: str | None = Header(default="local-user"),
    x_user_role: str | None = Header(default="admin"),
) -> Actor:
    role = (x_user_role or "reader").lower()
    if role not in ROLE_CAPABILITIES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unknown role")
    return Actor(user_id=x_user_id or "local-user", role=role)


def require_capability(actor: Actor, capability: str) -> None:
    if capability not in ROLE_CAPABILITIES.get(actor.role, set()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Role {actor.role} cannot {capability}")
