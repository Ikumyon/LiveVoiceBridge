"""Validation of the editable read-block form representation."""

READ_BLOCK_TYPES = {"author", "message", "text"}
DEFAULT_READ_BLOCKS = [{"type": "message"}]


def normalize_read_blocks(blocks: object) -> list[dict]:
    if not isinstance(blocks, list):
        return [block.copy() for block in DEFAULT_READ_BLOCKS]

    normalized = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type not in READ_BLOCK_TYPES:
            continue
        if block_type == "text":
            value = str(block.get("value", ""))
            if value:
                normalized.append({"type": "text", "value": value})
        else:
            normalized.append({"type": block_type})
    return normalized or [block.copy() for block in DEFAULT_READ_BLOCKS]
