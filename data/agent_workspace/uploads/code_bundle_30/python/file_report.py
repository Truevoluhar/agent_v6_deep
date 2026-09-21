from pathlib import Path


def count_lines(path: str) -> int:
    return len(Path(path).read_text(encoding='utf-8').splitlines())
