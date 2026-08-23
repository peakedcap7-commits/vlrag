"""仅供开发部署使用的本地 JWT 信任边界。"""

import argparse
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, Request, status

ALLOWED_ROLES = frozenset({"user", "tenant_admin"})
REQUIRED_CLAIMS = ("iss", "aud", "sub", "tenant_id", "roles", "iat", "exp", "jti")


@dataclass(frozen=True)
class Identity:
    tenant_id: UUID
    user_id: UUID | None
    roles: frozenset[str]

    @property
    def is_admin(self):
        return "tenant_admin" in self.roles


class LocalJWTAuthenticator:
    """固定 HS256、issuer 和 audience，拒绝请求体身份。"""

    def __init__(self, secret, issuer="shopping-qna-dev", audience="shopping-qna-api"):
        if not secret or len(secret.encode()) < 32:
            raise ValueError("DEV_JWT_SECRET 至少需要 32 个字节")
        self.secret = secret
        self.issuer = issuer
        self.audience = audience

    def decode(self, token):
        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": list(REQUIRED_CLAIMS)},
            )
            roles = claims["roles"]
            if not isinstance(roles, list) or not roles:
                raise ValueError("roles 必须是非空列表")
            role_set = frozenset(roles)
            if role_set - ALLOWED_ROLES:
                raise ValueError("包含未知角色")
            return Identity(
                tenant_id=UUID(str(claims["tenant_id"])),
                user_id=UUID(str(claims["sub"])),
                roles=role_set,
            )
        except (jwt.PyJWTError, TypeError, ValueError, KeyError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的访问令牌",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    def authenticate(self, request: Request):
        value = request.headers.get("Authorization", "")
        scheme, _, token = value.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少 Bearer 令牌",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return self.decode(token)

    def issue(self, tenant_id, user_id, roles=("user",), lifetime_minutes=60):
        tenant_id = str(UUID(str(tenant_id)))
        user_id = str(UUID(str(user_id)))
        roles = list(dict.fromkeys(roles))
        if not roles or set(roles) - ALLOWED_ROLES:
            raise ValueError("roles 只能包含 user/tenant_admin")
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "iss": self.issuer,
                "aud": self.audience,
                "sub": user_id,
                "tenant_id": tenant_id,
                "roles": roles,
                "iat": now,
                "exp": now + timedelta(minutes=lifetime_minutes),
                "jti": str(uuid4()),
            },
            self.secret,
            algorithm="HS256",
        )


def configured_authenticator():
    from src.config import DEV_JWT_AUDIENCE, DEV_JWT_ISSUER, DEV_JWT_SECRET

    return LocalJWTAuthenticator(DEV_JWT_SECRET, DEV_JWT_ISSUER, DEV_JWT_AUDIENCE)


def main():
    parser = argparse.ArgumentParser(description="生成本地开发 JWT（不用于生产）")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--role", action="append", choices=sorted(ALLOWED_ROLES), default=[])
    parser.add_argument("--minutes", type=int, default=60)
    args = parser.parse_args()
    if args.minutes < 1:
        parser.error("--minutes 必须大于零")
    secret = os.getenv("DEV_JWT_SECRET")
    if secret is None:
        parser.error("必须设置 DEV_JWT_SECRET")
    auth = configured_authenticator()
    print(auth.issue(args.tenant_id, args.user_id, args.role or ["user"], args.minutes))


if __name__ == "__main__":
    main()
