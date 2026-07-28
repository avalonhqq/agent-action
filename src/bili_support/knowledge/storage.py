"""第五周使用的本地不可变原文件存储；以后可替换为 OSS/S3。"""

from __future__ import annotations

from pathlib import Path


class LocalKnowledgeFileStore:
    """只接受服务端生成的相对 key，并用原子替换保存完整文件。"""

    def __init__(self, root: Path) -> None:
        """固定并解析存储根目录，后续所有key都必须位于该目录内。"""

        self._root = root.resolve()

    def build_key(self, *, version_id: str, filename: str) -> str:
        """使用服务端版本ID构造不可碰撞相对key，只继承安全的文件后缀。"""

        suffix = Path(filename).suffix.casefold()
        # 两级目录避免所有文件堆在同一个目录；版本 ID 保证不同版本不会互相覆盖。
        return f"{version_id[:2]}/{version_id}{suffix}"

    def write(self, *, key: str, content: bytes) -> None:
        """原子写入完整原文件，避免中途失败留下半文件。"""

        target = self._resolve_key(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # 先写临时文件再 replace，避免异常中断后留下“看似存在但内容不完整”的原文件。
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)

    def read(self, key: str) -> bytes:
        """读取已校验key对应的原始文件字节。"""

        return self._resolve_key(key).read_bytes()

    def _resolve_key(self, key: str) -> Path:
        """解析相对key并阻止路径穿越存储根目录。"""

        target = (self._root / key).resolve()
        # 防止 ../../ 等路径穿越知识文件根目录。
        if not target.is_relative_to(self._root):
            raise ValueError("storage key escapes knowledge root")
        return target
