"""Errors with a stable code and a display message; never carry internals."""


class AtlasError(Exception):
    def __init__(
        self, code: str, message: str, *, status: int = 400, retryable: bool = False
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


class WorkUnavailable(AtlasError):
    """Private, hidden, unconfirmed and absent works all look exactly like this."""

    def __init__(self) -> None:
        super().__init__("work_unavailable", "作品暂不可用。", status=404)


class VersionConflict(AtlasError):
    def __init__(self) -> None:
        super().__init__("version_conflict", "这条记录已在别处更新，请刷新后再保存。", status=409)


class NothingToUpdate(AtlasError):
    def __init__(self) -> None:
        super().__init__("no_changes", "没有可保存的修改。", status=422)


NOT_READY_MESSAGES = {
    "schema_too_new": "资料库由更新版本的 Library Atlas 创建，当前程序无法安全打开。请升级程序。",
    "profile_mismatch": "该资料库与当前配置（真实 / 测试）不一致，已拒绝打开。",
    "database_corrupt": "资料库文件无法读取，可能已损坏。文件未被改动，可从 backups 目录恢复。",
    "database_unavailable": "无法打开资料库文件，请检查数据目录的访问权限。",
    "migration_failed": "资料库升级失败，原有资料未被覆盖。请查看运行说明中的恢复步骤。",
    "backup_failed": "升级前备份失败，已停止升级，原有资料未被改动。",
    "migrations_missing": "程序缺少资料库迁移文件，请重新安装。",
    "starting": "服务正在启动。",
}
