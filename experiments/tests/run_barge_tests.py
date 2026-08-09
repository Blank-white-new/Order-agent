from __future__ import annotations

import inspect

from experiments.tests import test_barge_in


def main() -> int:
    tests = [
        (name, function)
        for name, function in inspect.getmembers(test_barge_in, inspect.isfunction)
        if name.startswith("test_")
    ]
    failures = []
    for name, function in tests:
        try:
            function()
            print(f"PASS {name}")
        except Exception as exc:  # pragma: no cover - command-line runner
            failures.append((name, exc))
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - len(failures)} passed, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
