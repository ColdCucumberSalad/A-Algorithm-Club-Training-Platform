"""Display placeholders are never submitted solution content."""
EMPTY_LOGIC_TEXTS={'未提交题解思路。','未提交题解思路.','未提交题解思路'}


def normalize_logic(text):
    text=text.strip()
    return '' if text in EMPTY_LOGIC_TEXTS else text
