"""Read-only prospective Git staging/secret/size audit (never prints secret values)."""

from __future__ import annotations

from collections import defaultdict
import gzip
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {".secrets", ".venv", "node_modules", "__pycache__", "dist", "raw", "interim", "processed", "reports", "ref_images"}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".md", ".txt", ".toml", ".html", ".css", ".sh"}
PATTERNS = {
    "AWS_ACCESS_KEY": re.compile(r"AKIA[0-9A-Z]{16}"),
    "PRIVATE_KEY": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "BEARER_TOKEN": re.compile(r"Bearer [A-Za-z0-9._~+/=-]{24,}"),
    "QUOTED_SECRET": re.compile(r"(?i)(?:api_key|secret_key|access_token|password)\s*[:=]\s*['\"][^'\"]{16,}['\"]"),
}


def candidate_paths() -> list[Path]:
    # Temporary empty index lets Git apply this worktree's .gitignore without
    # initializing or modifying the user's repository.
    with TemporaryDirectory(prefix="yuki-git-audit-") as temporary:
        subprocess.run(["git", "init", "-q", temporary], check=True, capture_output=True)
        result = subprocess.run(["git", f"--git-dir={Path(temporary) / '.git'}", f"--work-tree={ROOT}",
                                 "ls-files", "--others", "--exclude-standard", "-z"],
                                check=True, capture_output=True)
        return sorted(ROOT / Path(part.decode("utf-8")) for part in result.stdout.split(b"\0") if part)


def main() -> None:
    paths = candidate_paths()
    bad = [path.relative_to(ROOT) for path in paths if any(part in FORBIDDEN_PARTS for part in path.relative_to(ROOT).parts)]
    if bad:
        raise ValueError(f"Forbidden deployment paths would be staged: {bad[:8]}")
    findings = []
    for path in paths:
        if path.suffix.lower() == ".gz" and path.is_relative_to(ROOT / "runtime"):
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
                tail = ""
                found = set()
                while chunk := handle.read(1024 * 1024):
                    content = tail + chunk
                    found.update(name for name, pattern in PATTERNS.items() if pattern.search(content))
                    tail = content[-256:]
                findings.extend((path.relative_to(ROOT), name) for name in sorted(found))
        elif path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 6_000_000:
            content = path.read_text(encoding="utf-8", errors="replace")
            findings.extend((path.relative_to(ROOT), name) for name, pattern in PATTERNS.items()
                            if pattern.search(content))
    sizes = defaultdict(int)
    for path in paths:
        sizes[path.relative_to(ROOT).parts[0]] += path.stat().st_size
    total = sum(path.stat().st_size for path in paths)
    print(f"PROSPECTIVE_GIT_FILES={len(paths)}")
    print(f"PROSPECTIVE_GIT_BYTES={total}")
    print(f"PROSPECTIVE_GIT_MIB={total / 1024**2:.2f}")
    print("TOP_DIRECTORIES_MIB=" + ", ".join(f"{name}:{size / 1024**2:.2f}"
                                           for name, size in sorted(sizes.items(), key=lambda pair: -pair[1])[:8]))
    print("TOP_FILES_MIB=" + ", ".join(f"{path.relative_to(ROOT)}:{path.stat().st_size / 1024**2:.2f}"
                                       for path in sorted(paths, key=lambda item: -item.stat().st_size)[:8]))
    print(f"POTENTIAL_SECRET_FINDINGS={len(findings)}")
    for path, kind in findings:
        print(f"POTENTIAL_SECRET_PATH={path} RULE={kind}")
    if findings:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
