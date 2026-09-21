# file_report.py

- **Source file:** `/uploads/code_bundle_30/python/file_report.py`
- **Language:** Python
- **Purpose:** Provides a utility for counting lines in a text file.
- **Key functions/classes:** `count_lines(path: str) -> int` reads a file and counts its lines.
- **Inputs:** A filesystem path string pointing to a UTF-8 text file.
- **Outputs:** Returns the number of lines as an integer.
- **Notable implementation details:** Uses `pathlib.Path.read_text(encoding='utf-8')` and `splitlines()`; reads the entire file into memory and does not handle missing-file or decoding errors internally.
