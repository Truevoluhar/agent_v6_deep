# math_utils.py

- **Source file:** `/uploads/code_bundle_30/python/math_utils.py`
- **Language:** Python
- **Purpose:** Implements a Fibonacci number helper.
- **Key functions/classes:** `fib(n: int) -> int` iteratively computes the nth Fibonacci value.
- **Inputs:** Integer `n`, interpreted as the number of iteration steps.
- **Outputs:** Returns the nth Fibonacci number with `fib(0) == 0` and `fib(1) == 1`.
- **Notable implementation details:** Uses an iterative tuple assignment update, which is memory efficient; negative inputs return `0` because `range(n)` is empty for negative `n`.
