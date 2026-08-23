"""仅用于开发/测试 PostgreSQL 的记忆 Schema 前向迁移。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

SCHEMA_PATH = Path(__file__).with_name("memory_schema.sql")
ALLOWED_ROLES = {"user", "tenant_admin", "worker"}
LOGIN_ROLE_ENV = {
    "shopping_memory_migrator_login": (
        "shopping_memory_migrator",
        "MEMORY_MIGRATOR_DB_PASSWORD",
    ),
    "shopping_memory_api_login": (
        "shopping_memory_api",
        "MEMORY_API_DB_PASSWORD",
    ),
    "shopping_memory_worker_login": (
        "shopping_memory_worker",
        "MEMORY_WORKER_DB_PASSWORD",
    ),
    "shopping_memory_poller_login": (
        "shopping_memory_poller",
        "MEMORY_POLLER_DB_PASSWORD",
    ),
    "shopping_memory_maintenance_login": (
        "shopping_memory_maintenance",
        "MEMORY_MAINTENANCE_DB_PASSWORD",
    ),
}


def database_name(dsn: str) -> str:
    """解析 PostgreSQL DSN，并拒绝没有显式数据库名的地址。"""
    name = urlparse(dsn).path.lstrip("/").split("?", 1)[0]
    if not name:
        raise ValueError("数据库 URL 必须包含数据库名")
    return name


def require_development_database(dsn: str) -> str:
    """迁移器只允许操作名称以 _dev 或 _test 结尾的数据库。"""
    name = database_name(dsn)
    if not name.endswith(("_dev", "_test")):
        raise ValueError("只允许迁移 *_dev 或 *_test 数据库")
    return name


def set_local_context(
    cursor,
    tenant_id: str,
    user_id: str | None,
    app_role: str,
    worker_id: str | None = None,
) -> None:
    """在当前事务安全设置 RLS 上下文；调用方必须先验证 JWT/job。"""
    tenant = str(UUID(tenant_id))
    user = "" if user_id is None else str(UUID(user_id))
    worker = "" if worker_id is None else str(UUID(worker_id))
    if app_role not in ALLOWED_ROLES:
        raise ValueError(f"不支持的 app_role: {app_role}")
    cursor.execute(
        """
        SELECT
            set_config('app.tenant_id', %s, true),
            set_config('app.user_id', %s, true),
            set_config('app.role', %s, true),
            set_config('app.worker_id', %s, true)
        """,
        (tenant, user, app_role, worker),
    )


def required_login_passwords() -> dict[str, str]:
    """从环境读取开发 LOGIN 密码；SQL 和日志均不包含这些值。"""
    passwords = {}
    missing = []
    for login_role, (_, env_name) in LOGIN_ROLE_ENV.items():
        password = os.getenv(env_name, "")
        if len(password) < 16:
            missing.append(env_name)
        else:
            passwords[login_role] = password
    if missing:
        raise ValueError(f"以下开发数据库密码缺失或短于 16 字符: {', '.join(missing)}")
    return passwords


def configure_login_roles(connection, passwords: dict[str, str]) -> None:
    """创建固定开发 LOGIN，并授予对应的最小 NOLOGIN group role。"""
    from psycopg import sql

    unknown = set(passwords) - set(LOGIN_ROLE_ENV)
    if unknown:
        raise ValueError(f"不支持的 LOGIN role: {', '.join(sorted(unknown))}")
    with connection.cursor() as cursor:
        for login_role, password in passwords.items():
            if len(password) < 16:
                raise ValueError(f"{login_role} 密码不能短于 16 字符")
            group_role = LOGIN_ROLE_ENV[login_role][0]
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login_role,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(
                        sql.Identifier(login_role)
                    )
                )
            cursor.execute(
                sql.SQL(
                    "ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "INHERIT NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(login_role), sql.Literal(password))
            )
            cursor.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(group_role), sql.Identifier(login_role)
                )
            )


def migrate(dsn: str, login_passwords: dict[str, str] | None = None) -> None:
    """执行一份幂等前向 SQL；不提供生产或 down migration。"""
    require_development_database(dsn)
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - 由部署镜像提供依赖
        raise RuntimeError("迁移需要 psycopg 3") from exc

    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, prepare=False)
        if login_passwords:
            configure_login_roles(connection, login_passwords)


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化开发记忆数据库")
    parser.add_argument(
        "--database-url",
        default=os.getenv("MEMORY_DATABASE_URL"),
        help="仅接受数据库名以 _dev 或 _test 结尾的 PostgreSQL URL",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("请提供 --database-url 或 MEMORY_DATABASE_URL")
    migrate(args.database_url, required_login_passwords())


if __name__ == "__main__":
    main()
