"""统一Loader协议、错误码与文件类型注册表。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from bili_support.knowledge.types import LoadedDocument


class DocumentLoadError(Exception):
    """对外稳定的解析错误；隐藏 PyMuPDF、python-docx 等底层异常细节。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DocumentLoader(Protocol):
    """所有文件解析器必须满足的最小接口，便于注册和替换实现。"""

    extensions: frozenset[str]

    def load(
        self,
        *,
        content: bytes,
        filename: str,
        media_type: str,
    ) -> LoadedDocument: ...


class DocumentLoaderRegistry:
    """按扩展名选择 Loader，并统一文件名清理和异常转换。"""

    def __init__(self, loaders: tuple[DocumentLoader, ...]) -> None:
        self._by_extension: dict[str, DocumentLoader] = {}
        for loader in loaders:
            for extension in loader.extensions:
                # casefold 比 lower 更适合做不区分大小写的规范化。
                normalized = extension.casefold()
                if normalized in self._by_extension:
                    raise ValueError(f"duplicate loader extension: {normalized}")
                self._by_extension[normalized] = loader

    def load(
        self,
        *,
        content: bytes,
        filename: str,
        media_type: str,
    ) -> LoadedDocument:
        # 媒体类型由客户端提供，可能不可信；当前以服务端可控的扩展名选择解析器，
        # 再由各 Loader 检查 PDF/ZIP 等文件签名。
        extension = Path(filename).suffix.casefold()
        loader = self._by_extension.get(extension)
        if loader is None:
            raise DocumentLoadError("UNSUPPORTED_DOCUMENT_TYPE")
        try:
            return loader.load(
                content=content,
                # 只把 basename 交给解析器，避免把客户端路径带入日志或存储逻辑。
                filename=Path(filename).name,
                media_type=media_type,
            )
        except DocumentLoadError:
            # 已经归一化的业务错误码原样保留。
            raise
        except Exception as exc:
            # 未预料的第三方库异常不直接暴露给 API。
            raise DocumentLoadError("DOCUMENT_PARSE_FAILED") from exc
