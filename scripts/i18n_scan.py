#!/usr/bin/env python3
"""i18n Automated Key and Translation Scanner for xpx.

Scans the codebase to detect:
1. Parity between language tables (zh-CN vs en-US).
2. Format parameter consistency (e.g. {count}, {name}) across languages.
3. Code references via AST (missing keys used in code vs defined in i18n).
4. Unused/orphan keys defined in MESSAGES.
5. Hardcoded CJK (Chinese) string literals leaking in interactive UI code.
"""

from __future__ import annotations

import argparse
import ast
import re
import string
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Ensure src/ is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from lib.xpx.i18n import MESSAGES  # noqa: E402

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_FORMATTER = string.Formatter()

# Whitelisted literals that legitimately contain Chinese characters
_CJK_WHITELIST: set[str] = {
    "中文 (Simplified Chinese)",
}


@dataclass
class ScanResult:
    """Consolidated result of i18n analysis."""

    total_zh_keys: int = 0
    total_en_keys: int = 0
    missing_in_en: list[str] = field(default_factory=list)
    missing_in_zh: list[str] = field(default_factory=list)
    param_mismatches: list[tuple[str, set[str], set[str]]] = field(default_factory=list)
    code_keys_total: int = 0
    code_missing_in_zh: dict[str, list[str]] = field(default_factory=dict)
    code_missing_in_en: dict[str, list[str]] = field(default_factory=dict)
    dynamic_calls: list[str] = field(default_factory=list)
    unused_keys: list[str] = field(default_factory=list)
    cjk_leaks: list[tuple[str, int, str]] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """True if there are critical parity, missing keys, or CJK leak errors."""
        return bool(
            self.missing_in_en
            or self.missing_in_zh
            or self.param_mismatches
            or self.code_missing_in_zh
            or self.code_missing_in_en
            or self.cjk_leaks
        )


def check_key_parity() -> tuple[list[str], list[str]]:
    """Compare zh and en dictionary keys."""
    zh_keys = set(MESSAGES.get("zh", {}).keys())
    en_keys = set(MESSAGES.get("en", {}).keys())
    missing_in_en = sorted(zh_keys - en_keys)
    missing_in_zh = sorted(en_keys - zh_keys)
    return missing_in_en, missing_in_zh


def check_parameter_consistency() -> list[tuple[str, set[str], set[str]]]:
    """Check that format placeholders match across translations."""
    zh = MESSAGES.get("zh", {})
    en = MESSAGES.get("en", {})
    mismatches: list[tuple[str, set[str], set[str]]] = []

    common_keys = set(zh.keys()) & set(en.keys())
    for k in sorted(common_keys):
        zh_fields = {
            fname for _, fname, _, _ in _FORMATTER.parse(zh[k]) if fname is not None
        }
        en_fields = {
            fname for _, fname, _, _ in _FORMATTER.parse(en[k]) if fname is not None
        }
        if zh_fields != en_fields:
            mismatches.append((k, zh_fields, en_fields))

    return mismatches


def scan_ast_references(
    src_dir: Path | None = None,
) -> tuple[dict[str, list[str]], list[str]]:
    """Scan all Python files under src/ for t() calls via AST."""
    target_dir = src_dir or _SRC_ROOT
    used_keys: dict[str, list[str]] = {}
    dynamic_calls: list[str] = []

    for py_path in sorted(target_dir.rglob("*.py")):
        if py_path.name == "i18n.py":
            continue
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        except Exception:
            continue

        rel_path = py_path.relative_to(_REPO_ROOT)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Matches t(...) or i18n.t(...)
                is_t = (isinstance(func, ast.Name) and func.id == "t") or (
                    isinstance(func, ast.Attribute)
                    and func.attr == "t"
                    and isinstance(func.value, ast.Name)
                    and func.value.id in ("i18n", "lib_i18n")
                )
                if is_t and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(
                        first_arg.value, str
                    ):
                        k = first_arg.value
                        used_keys.setdefault(k, []).append(f"{rel_path}:{node.lineno}")
                    else:
                        dynamic_calls.append(f"{rel_path}:{node.lineno}")

    return used_keys, dynamic_calls


def scan_cjk_leaks(
    interactive_dir: Path | None = None,
) -> list[tuple[str, int, str]]:
    """Scan interactive UI source code for hardcoded Chinese string literals."""
    target_dir = interactive_dir or (_SRC_ROOT / "lib" / "xpx" / "interactive")
    leaks: list[tuple[str, int, str]] = []

    for py_path in sorted(target_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        except Exception:
            continue

        rel_path = str(py_path.relative_to(_REPO_ROOT))

        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.strip()
                if _CJK_PATTERN.search(val) and val not in _CJK_WHITELIST:
                    leaks.append((rel_path, node.lineno, val))
            elif isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        val = part.value.strip()
                        if _CJK_PATTERN.search(val) and val not in _CJK_WHITELIST:
                            leaks.append((rel_path, node.lineno, val))

    return leaks


def run_i18n_scan(src_dir: Path | None = None) -> ScanResult:
    """Perform a complete scan and return aggregated ScanResult."""
    zh_keys = set(MESSAGES.get("zh", {}).keys())
    en_keys = set(MESSAGES.get("en", {}).keys())

    missing_in_en, missing_in_zh = check_key_parity()
    param_mismatches = check_parameter_consistency()
    used_keys, dynamic_calls = scan_ast_references(src_dir)
    cjk_leaks = scan_cjk_leaks()

    code_missing_in_zh = {k: locs for k, locs in used_keys.items() if k not in zh_keys}
    code_missing_in_en = {k: locs for k, locs in used_keys.items() if k not in en_keys}

    all_defined = zh_keys | en_keys
    unused_keys = sorted(all_defined - set(used_keys.keys()))

    return ScanResult(
        total_zh_keys=len(zh_keys),
        total_en_keys=len(en_keys),
        missing_in_en=missing_in_en,
        missing_in_zh=missing_in_zh,
        param_mismatches=param_mismatches,
        code_keys_total=len(used_keys),
        code_missing_in_zh=code_missing_in_zh,
        code_missing_in_en=code_missing_in_en,
        dynamic_calls=dynamic_calls,
        unused_keys=unused_keys,
        cjk_leaks=cjk_leaks,
    )


def print_report(res: ScanResult, *, verbose: bool = False) -> None:
    """Print human-readable report."""
    print("=" * 60)
    print("         🌐  XPX i18n Translation & Key Scanner")
    print("=" * 60)
    print(f"Defined keys: zh={res.total_zh_keys}, en={res.total_en_keys}")
    print(f"Statically resolved keys in code: {res.code_keys_total}")

    # 1. Parity Check
    if not res.missing_in_en and not res.missing_in_zh:
        print("\n✔  Language Parity: OK (100% matched between zh and en)")
    else:
        print("\n✘  Language Parity: MISMATCH")
        if res.missing_in_en:
            print(f"   Missing in en ({len(res.missing_in_en)}):")
            for k in res.missing_in_en:
                print(f"     - {k}")
        if res.missing_in_zh:
            print(f"   Missing in zh ({len(res.missing_in_zh)}):")
            for k in res.missing_in_zh:
                print(f"     - {k}")

    # 2. Parameter Consistency
    if not res.param_mismatches:
        print("✔  Format Placeholders: OK (Parameters identical across languages)")
    else:
        print(f"\n✘  Format Placeholders: {len(res.param_mismatches)} MISMATCHES")
        for k, zf, ef in res.param_mismatches:
            print(f"   Key '{k}': zh={sorted(zf)} vs en={sorted(ef)}")

    # 3. Missing in Code
    if not res.code_missing_in_zh and not res.code_missing_in_en:
        print("✔  Code References: OK (All keys used in code exist in i18n)")
    else:
        print("\n✘  Code References: UNKNOWN KEYS USED IN CODE")
        missing_all = set(res.code_missing_in_zh.keys()) | set(
            res.code_missing_in_en.keys()
        )
        for k in sorted(missing_all):
            locs = res.code_missing_zh.get(k) or res.code_missing_in_en.get(k, [])
            loc_str = ", ".join(locs[:3])
            print(f"   - '{k}' -> used at {loc_str}")

    # 4. Hardcoded CJK Leaks
    if not res.cjk_leaks:
        print("✔  UI CJK Leaks: OK (No hardcoded Chinese strings in interactive UI)")
    else:
        print(f"\n✘  UI CJK Leaks: {len(res.cjk_leaks)} HARDCODED STRINGS FOUND")
        for path, line, text in res.cjk_leaks:
            print(f"   - {path}:{line} -> {text!r}")

    # 5. Dynamic Calls
    if res.dynamic_calls and verbose:
        print(f"\nℹ  Dynamic t() calls ({len(res.dynamic_calls)}):")
        for loc in res.dynamic_calls:
            print(f"   - {loc}")

    # 6. Unused Keys
    if res.unused_keys and verbose:
        count = len(res.unused_keys)
        print(f"\nℹ  Defined keys with no direct static reference ({count}):")
        for k in res.unused_keys:
            print(f"   - {k}")

    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan codebase for i18n keys, parity, and hardcoded CJK leaks"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with code 1 if any missing keys or CJK leaks are detected",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also exit with code 1 on unused/orphan keys",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed list of dynamic calls and unused keys",
    )
    args = parser.parse_args()

    result = run_i18n_scan()
    print_report(result, verbose=args.verbose)

    if args.check and result.has_errors:
        return 1
    if args.strict and (result.has_errors or result.unused_keys):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
