"""Check a generic public source tree; runtime records do not belong in it."""
from pathlib import Path
import re
import sys

ROOT_FILES = {
    'README.md', 'ATTRIBUTION.md', 'CHANGELOG.md', 'LICENSE', 'UPSTREAM_LICENSE',
    'pyproject.toml', 'MANIFEST.in', '.gitignore', 'SECURITY.md',
}
ROOT_DIRS = {'pinuke', 'tests', 'docs', 'examples', 'tools', '.github'}
SKIP_DIRS = {'.git', '__pycache__', 'build', 'dist', '.venv', 'venv'}
PATTERNS = {
    'private host': r'\b[\w.-]+\.home\.arpa\b',
    'workstation/home path': r'/(?:Users|home)/[A-Za-z0-9_.-]+/',
    'private IPv4': r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b',
    'GitHub token': r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b',
    'private key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'credential URL': r'https?://[^\s/@]+:[^\s/@]+@',
    'cloud access key': r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
}


def check(root):
    findings = []
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root)
        if p.is_symlink():
            findings.append((str(rel), 'symlink could escape the public tree'))
            continue
        if any(part in SKIP_DIRS or part.endswith('.egg-info') for part in rel.parts):
            continue
        if not p.is_file():
            continue
        if ((len(rel.parts) == 1 and rel.name not in ROOT_FILES)
                or (len(rel.parts) > 1 and rel.parts[0] not in ROOT_DIRS)):
            findings.append((str(rel), 'not in public source allowlist'))
        if p.suffix.lower() in {'.json', '.jsonl', '.pcap', '.pcapng', '.log', '.pem', '.key', '.png', '.jpg', '.jpeg'}:
            findings.append((str(rel), 'record, credential or image requires separate review'))
        try:
            content = p.read_text(encoding='utf-8')
        except (UnicodeError, OSError):
            findings.append((str(rel), 'unexpected binary or unreadable file'))
            continue
        for label, pattern in PATTERNS.items():
            if re.search(pattern, content):
                findings.append((str(rel), label))
    return findings


if __name__ == '__main__':
    root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
    if not root.is_dir():
        raise SystemExit('Expected a public source directory')
    findings = check(root)
    for path, reason in findings:
        # Never print the matched secret or private value.
        print(f'{path}: {reason}')
    print(f'Public-tree checks: {len(findings)} finding(s). Review staged files and history separately.')
    raise SystemExit(bool(findings))
