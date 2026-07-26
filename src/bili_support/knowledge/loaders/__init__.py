"""Public document Loader contracts and default registry."""

from bili_support.knowledge.loaders.base import (
    DocumentLoader,
    DocumentLoaderRegistry,
    DocumentLoadError,
)
from bili_support.knowledge.loaders.implementations import (
    DocxLoader,
    MarkdownLoader,
    PdfLoader,
    TextLoader,
)


def create_default_loader_registry() -> DocumentLoaderRegistry:
    return DocumentLoaderRegistry(
        (
            PdfLoader(),
            DocxLoader(),
            MarkdownLoader(),
            TextLoader(),
        )
    )


__all__ = [
    "DocumentLoadError",
    "DocumentLoader",
    "DocumentLoaderRegistry",
    "DocxLoader",
    "MarkdownLoader",
    "PdfLoader",
    "TextLoader",
    "create_default_loader_registry",
]
