"""Command line: python -m app <serve|check|init|seed-test>."""

import argparse
import logging
import socket
import sys
from pathlib import Path

import uvicorn

from app.core.config import LOOPBACK_HOST, TEST_MARKER, ConfigError, Settings, load_settings
from app.core.errors import NOT_READY_MESSAGES
from app.db.bootstrap import DatabaseNotReady, open_database
from app.main import create_app
from app.testing import synthetic

EXIT_CONFIG = 2
EXIT_PORT = 3
EXIT_DATABASE = 4


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((LOOPBACK_HOST, port))
        except OSError:
            return False
    return True


def _open(settings: Settings) -> None:
    opened = open_database(settings.database_path, settings.backup_dir, settings.profile)
    opened.engine.dispose()


def serve(settings: Settings) -> int:
    if not _port_free(settings.port):
        # Whatever holds the port may be someone else's program; never touch it.
        print(
            f"端口 {settings.port} 已被占用。Library Atlas 不会结束其他程序；"
            "请关闭占用的程序，或设置 ATLAS_PORT 使用其他端口。",
            file=sys.stderr,
        )
        return EXIT_PORT
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("alembic").setLevel(logging.WARNING)
    print(f"Library Atlas · {settings.profile} · http://{LOOPBACK_HOST}:{settings.port}")
    uvicorn.run(
        create_app(settings),
        host=LOOPBACK_HOST,
        port=settings.port,
        access_log=False,
        log_level="warning",
    )
    return 0


def check(settings: Settings) -> int:
    """Validates configuration and opens (and if needed migrates) the database."""
    _open(settings)
    print(f"就绪 · 配置 {settings.profile}")
    print(f"数据目录：{settings.data_dir}")
    print(f"前端构建：{'已找到' if settings.static_dir else '未找到（请运行 npm run build）'}")
    return 0


def seed_test(args: argparse.Namespace) -> int:
    settings = load_settings(profile="test", data_dir=args.data_dir, create_data_dir=True)
    marker = settings.data_dir / TEST_MARKER
    entries = {entry.name for entry in settings.data_dir.iterdir()}
    if entries and not marker.is_file():
        print("该目录非空且未标记为测试目录，已拒绝写入。请指定新的空目录。", file=sys.stderr)
        return EXIT_CONFIG
    if settings.database_path.exists():
        if not args.reset:
            print("测试库已存在。如需重建，请加 --reset。", file=sys.stderr)
            return EXIT_CONFIG
        # Only reached for a directory carrying the test marker; removes only its database.
        for suffix in ("", "-wal", "-shm"):
            Path(f"{settings.database_path}{suffix}").unlink(missing_ok=True)
    marker.write_text("Library Atlas synthetic test data. Safe to delete.\n", encoding="utf-8")
    opened = open_database(settings.database_path, settings.backup_dir, "test")
    try:
        count = synthetic.seed(opened.engine, args.size)
    finally:
        opened.engine.dispose()
    print(f"已写入 {count} 条合成作品（其中 3 条为不可见的私人哨兵）。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app", description="Library Atlas local service"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("serve", "启动服务（仅绑定 127.0.0.1）；Ctrl+C 关闭"),
        ("check", "检查配置并打开或迁移资料库"),
        ("init", "创建显式指定的数据目录并初始化空资料库"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--profile", choices=("real", "test"))
        command.add_argument("--data-dir")
        command.add_argument("--port", type=int)
    seeding = commands.add_parser("seed-test", help="向显式指定的测试目录写入合成数据")
    seeding.add_argument("--data-dir", required=True)
    seeding.add_argument("--size", type=int, default=120, help="普通作品数量，如 1500、5000")
    seeding.add_argument("--reset", action="store_true", help="重建已有的测试库")
    args = parser.parse_args(argv)
    try:
        if args.command == "seed-test":
            return seed_test(args)
        settings = load_settings(
            profile=args.profile,
            data_dir=args.data_dir,
            port=args.port,
            create_data_dir=args.command == "init",
        )
        if args.command == "serve":
            return serve(settings)
        return check(settings)
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return EXIT_CONFIG
    except DatabaseNotReady as error:
        print(
            f"资料库未就绪：{NOT_READY_MESSAGES.get(error.reason, error.reason)}", file=sys.stderr
        )
        return EXIT_DATABASE


if __name__ == "__main__":
    sys.exit(main())
