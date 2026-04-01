from dataclasses import dataclass


@dataclass
class BootstrapAdminSpec:
    username: str
    password: str


def get_bootstrap_admin_spec(cfg) -> BootstrapAdminSpec | None:
    username = (getattr(cfg, "bootstrap_admin_username", "") or "").strip()
    password = (getattr(cfg, "bootstrap_admin_password", "") or "").strip()
    if not username or not password:
        return None
    return BootstrapAdminSpec(username=username, password=password)


def format_bootstrap_admin_log(spec: BootstrapAdminSpec) -> str:
    masked_password = "*" * 3
    return (
        "初始化默认管理员用户. "
        f"用户名: {spec.username}, 密码: {masked_password}"
    )
