"""把二维表格转换为保留表头和行语义的自包含文本。"""

from __future__ import annotations

from collections.abc import Sequence


def normalize_table(rows: Sequence[Sequence[str | None]]) -> str:
    """每一行重复表头，避免切块后只有孤立单元格和数字。"""
    cleaned = [
        [str(cell or "").strip() for cell in row]
        for row in rows
        if any(str(cell or "").strip() for cell in row)
    ]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    # 不规则表格补齐为空字符串，使每列始终与同一个表头对应。
    padded = [row + [""] * (width - len(row)) for row in cleaned]
    if len(padded) == 1:
        # 单行表无法证明该行是“表头”。尤其Word常用1x1表格制作提示框，
        # 旧逻辑会把同一单元格同时当表头和数据，产生“全文=全文”的重复内容。
        return _normalize_single_row(padded[0])
    raw_headers = padded[0]
    headers = [
        header or f"第{index + 1}列"
        for index, header in enumerate(raw_headers)
    ]
    # 只有一行时仍输出内容，避免把无表体的小表格直接丢弃。
    body = padded[1:] or [padded[0]]
    lines = []
    for row_index, row in enumerate(body, start=1):
        cells = [
            # 每个值都重复表头；即使后续按行切块，列语义仍然完整。
            f"{headers[column_index]}={value}"
            for column_index, value in enumerate(row)
            if value
        ]
        if cells:
            lines.append(f"第{row_index}行：" + "；".join(cells))
    return "\n".join(lines)


def _normalize_single_row(row: Sequence[str]) -> str:
    """处理提示框和无表头单行表，避免产生“全文=全文”的重复语义。"""

    if len(row) == 1:
        lines = [line.strip() for line in row[0].splitlines() if line.strip()]
        if len(lines) >= 2:
            return f"第1行：{lines[0]}=" + "\n".join(lines[1:])
        return f"第1行：内容={row[0]}"
    cells = [
        f"第{index + 1}列={value}"
        for index, value in enumerate(row)
        if value
    ]
    return "第1行：" + "；".join(cells)
