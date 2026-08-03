"""知识入库、分块、索引与检索。"""

from bili_support.knowledge.chunk_strategies import (
    FaqChunkStrategy,
    ManualChunkStrategy,
    MixedDocumentChunkStrategy,
    PolicyChunkStrategy,
    StrategySelector,
    TableChunkStrategy,
)
from bili_support.knowledge.chunking import (
    ChunkDraft,
    ChunkKind,
    ChunkStrategy,
    DocumentKnowledgeType,
    GenericChunkStrategy,
)
from bili_support.knowledge.claim_verification import (
    ClaimSupportStatus,
    ClaimVerification,
    ClaimVerifier,
    EvidenceRecord,
    GroundedVerificationDecision,
    GroundedVerificationResult,
    TransformersNliClaimVerifier,
    VerificationMode,
    parse_evidence_records,
    verify_grounded_answer,
)
from bili_support.knowledge.embedding import (
    DeterministicHashEmbeddingProvider,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
)
from bili_support.knowledge.grounded_answer import (
    GroundedAnswer,
    GroundedAnswerContractError,
    GroundedAnswerEvidenceError,
    GroundedClaim,
    GroundedCompleteness,
    validate_grounded_answer_evidence,
)
from bili_support.knowledge.small_to_big import (
    ChildChunkHit,
    ParentExpansionPlan,
    SmallToBigExpander,
)
from bili_support.knowledge.vector_store import (
    MilvusVectorStore,
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
    VectorStore,
)

__all__ = [
    "ChunkDraft",
    "ChunkKind",
    "ChunkStrategy",
    "ClaimSupportStatus",
    "ClaimVerification",
    "ClaimVerifier",
    "ChildChunkHit",
    "DocumentKnowledgeType",
    "DeterministicHashEmbeddingProvider",
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingVector",
    "EvidenceRecord",
    "FaqChunkStrategy",
    "GroundedAnswer",
    "GroundedAnswerContractError",
    "GroundedAnswerEvidenceError",
    "GroundedClaim",
    "GroundedCompleteness",
    "GroundedVerificationDecision",
    "GroundedVerificationResult",
    "GenericChunkStrategy",
    "ManualChunkStrategy",
    "MixedDocumentChunkStrategy",
    "MilvusVectorStore",
    "PolicyChunkStrategy",
    "ParentExpansionPlan",
    "SmallToBigExpander",
    "StrategySelector",
    "TableChunkStrategy",
    "TransformersNliClaimVerifier",
    "VectorRecord",
    "VectorSearchHit",
    "VectorSearchQuery",
    "VectorStore",
    "VerificationMode",
    "validate_grounded_answer_evidence",
    "parse_evidence_records",
    "verify_grounded_answer",
]
