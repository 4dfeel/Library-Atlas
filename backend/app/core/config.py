"""Service configuration: command-line options > environment > defaults."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

Profile = Literal["real", "test"]
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
TEST_MARKER = ".atlas-test-data"
DATABASE_NAME = "library.sqlite3"


class ConfigError(Exception):
    """Invalid configuration. The message is shown to the person starting the service."""


@dataclass(frozen=True)
class Settings:
    profile: Profile
    data_dir: Path
    port: int
    static_dir: Path | None
    dev_origins: tuple[str, ...] = ()

    @property
    def database_path(self) -> Path:
        return self.data_dir / DATABASE_NAME

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def self_origins(self) -> tuple[str, ...]:
        return (f"http://{LOOPBACK_HOST}:{self.port}", f"http://localhost:{self.port}")

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset((*self.self_origins, *self.dev_origins))

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset(urlsplit(origin).netloc for origin in self.allowed_origins)


def default_root(env: Mapping[str, str]) -> Path:
    local = env.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "LibraryAtlas"


def _parse_port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError("ATLAS_PORT 必须是 1024–65535 之间的整数。") from None
    if not 1024 <= port <= 65535:
        raise ConfigError("ATLAS_PORT 必须是 1024–65535 之间的整数。")
    return port


def _parse_origins(raw: str) -> tuple[str, ...]:
    origins: list[str] = []
    for value in filter(None, (part.strip() for part in raw.split(","))):
        parts = urlsplit(value)
        if (
            parts.scheme != "http"
            or parts.hostname not in {LOOPBACK_HOST, "localhost"}
            or parts.port is None
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise ConfigError(
                "ATLAS_DEV_ORIGINS 只能包含本机回环地址，例如 http://127.0.0.1:5173。"
            )
        origins.append(f"{parts.scheme}://{parts.netloc}")
    return tuple(origins)


def _resolve_data_dir(profile: Profile, raw: str, env: Mapping[str, str], create: bool) -> Path:
    root = default_root(env)
    if not raw:
        if profile == "test":
            raise ConfigError("测试配置必须用 ATLAS_DATA_DIR 显式指定测试目录，不能使用默认目录。")
        path = root / "profiles" / "default"
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ConfigError("无法创建默认数据目录，请检查 LOCALAPPDATA 的访问权限。") from None
        return path

    path = Path(raw)
    if not path.is_absolute():
        raise ConfigError("ATLAS_DATA_DIR 必须是绝对路径；相对路径会随启动位置改变。")
    path = path.resolve()
    if path.exists() and not path.is_dir():
        raise ConfigError("ATLAS_DATA_DIR 指向的不是目录。")
    if profile == "test" and path.is_relative_to(root.resolve()):
        raise ConfigError("测试目录不能位于正常数据目录之内。")
    if not path.exists():
        # A missing explicit directory may be an unplugged drive. Creating it here would
        # quietly show an empty library instead of the user's data.
        if not create:
            raise ConfigError(
                "ATLAS_DATA_DIR 指定的目录不存在。服务不会自动新建，以免把缺失的资料显示成空库；"
                "如确需新建，请运行 init 命令。"
            )
        path.mkdir(parents=True)
    return path


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    profile: str | None = None,
    data_dir: str | None = None,
    port: int | None = None,
    create_data_dir: bool = False,
) -> Settings:
    source = os.environ if env is None else env
    chosen = profile or source.get("ATLAS_PROFILE") or "real"
    if chosen not in ("real", "test"):
        raise ConfigError("ATLAS_PROFILE 只能是 real 或 test。")
    typed = cast(Profile, chosen)
    resolved = _resolve_data_dir(
        typed, data_dir or source.get("ATLAS_DATA_DIR") or "", source, create_data_dir
    )
    marked = (resolved / TEST_MARKER).is_file()
    if typed == "test" and not create_data_dir and not marked:
        raise ConfigError("该目录未标记为测试目录。请先用 seed-test 命令初始化。")
    if typed == "real" and marked:
        raise ConfigError("该目录是测试目录，不能作为真实资料库打开。")

    static_raw = source.get("ATLAS_STATIC_DIR") or ""
    static = Path(static_raw) if static_raw else Path(__file__).parents[3] / "frontend" / "dist"
    if static_raw and not static.is_absolute():
        raise ConfigError("ATLAS_STATIC_DIR 必须是绝对路径。")
    return Settings(
        profile=typed,
        data_dir=resolved,
        port=port
        if port is not None
        else _parse_port(source.get("ATLAS_PORT") or str(DEFAULT_PORT)),
        static_dir=static if (static / "index.html").is_file() else None,
        dev_origins=_parse_origins(source.get("ATLAS_DEV_ORIGINS") or ""),
    )
