"""运行真实本地NLI Claim级Golden Dataset评估。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from bili_support.core.config import Settings
from bili_support.knowledge.claim_verification import (
    EvidenceRecord,
    TransformersNliClaimVerifier,
)
from bili_support.knowledge.grounded_answer import GroundedAnswer


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the production NLI verifier")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/claim_verification_dev_v1.jsonl"),
    )
    return parser.parse_args()


async def _run(path: Path) -> int:
    settings = Settings()
    verifier = TransformersNliClaimVerifier(
        model_name=settings.claim_verification_model,
        cache_dir=settings.claim_verification_cache_dir,
        device=settings.claim_verification_device,
        mode=settings.claim_verification_mode,
        entailment_threshold=settings.claim_entailment_threshold,
        contradiction_threshold=settings.claim_contradiction_threshold,
        max_length=settings.claim_verification_max_length,
        local_files_only=settings.claim_verification_local_files_only,
    )
    dataset_text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    rows = [json.loads(line) for line in dataset_text.splitlines() if line]
    passed = 0
    failures: list[str] = []
    total_latency = 0.0
    unsafe_acceptances = 0
    conflict_total = 0
    conflict_detected = 0
    for row in rows:
        answer = GroundedAnswer.model_validate(
            {
                "answer": f"{row['claim']}[E1]",
                "claims": [{"text": row["claim"], "evidence_ids": ["E1"]}],
                "used_evidence_ids": ["E1"],
                "completeness": "complete",
            }
        )
        result = await verifier.verify(
            answer,
            evidence=(
                EvidenceRecord(
                    evidence_id="E1",
                    document_title="大会员客服知识库",
                    content=row["premise"],
                ),
            ),
        )
        actual = result.claims[0].status.value
        if row["expected"] == "conflict":
            conflict_total += 1
            conflict_detected += actual == "conflict"
        if row["expected"] != "supported" and actual == "supported":
            unsafe_acceptances += 1
        total_latency += result.latency_ms
        if actual == row["expected"]:
            passed += 1
        else:
            claim = result.claims[0]
            failures.append(
                f"{row['id']}: expected={row['expected']} actual={actual} "
                f"scores=({claim.entailment_score},{claim.neutral_score},"
                f"{claim.contradiction_score}) reason={claim.reason_code}"
            )
    accuracy = passed / len(rows)
    contradiction_recall = conflict_detected / conflict_total if conflict_total else 1.0
    print(f"cases={len(rows)} passed={passed} accuracy={accuracy:.3f}")
    print(
        f"unsafe_acceptances={unsafe_acceptances} contradiction_recall={contradiction_recall:.3f}"
    )
    print(f"average_latency_ms={total_latency / len(rows):.1f}")
    for failure in failures:
        print(f"FAIL {failure}")
    # 生产门禁优先保证不误放；少量保守unknown可接受，但必须单独列出复盘。
    accepted = accuracy >= 0.90 and unsafe_acceptances == 0 and contradiction_recall >= 0.90
    return 0 if accepted else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run(_arguments().dataset)))


if __name__ == "__main__":
    main()
