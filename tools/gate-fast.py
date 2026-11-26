"""Fast pre-build gate (runs in ~3 min on a Linux runner).

Checks that historically cost us a 13-minute macOS build:
 1. every path referenced by the kernel file lists (bsd/osfmk/iokit/san/pexpert conf) exists,
 2. every file touched by the harness patch exists and is non-empty,
 3. file-scope statics that are used before their declaration site (the fPresentDrops class of bug),
 4. unbalanced #if/#endif in the touched files.

Usage: python3 tools/gate-fast.py <harness_repo_root> <source_root>
"""
import os
import re
import subprocess
import sys

CONF_LISTS = [
    'bsd/conf/files', 'osfmk/conf/files', 'iokit/conf/files',
    'pexpert/conf/files', 'libkern/conf/files', 'san/conf/files',
]
CONF_DIRS = ['bsd', 'osfmk', 'iokit', 'pexpert', 'libkern', 'san', 'mach']


def read(p):
    return open(p, encoding='utf-8', errors='surrogateescape').read()


def patch_targets(harness, only=None):
    files = []
    if only:
        for line in read(only).splitlines():
            if line.startswith('+++ b/'):
                files.append(line[6:].strip())
        return sorted({f for f in files if not f.startswith('xnu/patches/')})
    for dp, dn, fn in os.walk(os.path.join(harness, 'patches')):
        for f in fn:
            if not f.endswith('.patch'):
                continue
            for line in read(os.path.join(dp, f)).splitlines():
                if line.startswith('+++ b/'):
                    files.append(line[6:].strip())
    return sorted({f for f in files if not f.startswith('xnu/patches/')})


def check_filelists(source):
    bad = []
    for rel in CONF_LISTS:
        p = os.path.join(source, rel)
        if not os.path.exists(p):
            continue
        for line in read(p).splitlines():
            s = line.split('#', 1)[0].strip()
            if not s or s.startswith('OPT') or s.startswith('MODULE'):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            name = parts[-1] if len(parts) > 2 else parts[1]
            if not re.match(r'^[A-Za-z0-9_./-]+\.(c|cpp|cc|s|m)$', name):
                continue
            hit = [d for d in CONF_DIRS if os.path.exists(os.path.join(source, d, name))]
            if not hit:
                bad.append(f'{rel}: {name}')
    return bad


def check_touched(source, targets):
    problems = []
    for rel in targets:
        p = os.path.join(source, rel)
        if not os.path.exists(p):
            problems.append(f'missing touched file: {rel}')
            continue
        text = read(p)
        if not text.strip():
            problems.append(f'empty touched file: {rel}')
        depth = 0
        for i, line in enumerate(text.splitlines(), 1):
            st = line.strip()
            if st.startswith('#if'):
                depth += 1
            elif st.startswith('#endif'):
                depth -= 1
                if depth < 0:
                    problems.append(f'{rel}:{i}: unbalanced #endif')
                    depth = 0
        if depth:
            problems.append(f'{rel}: {depth} unterminated #if')
        # file-scope statics (fFoo convention, declared at column 0) used before their
        # declaration site: this is the exact class of bug that killed run #12.
        decl = {}
        for i, line in enumerate(text.splitlines(), 1):
            if line[:1].isspace() or not line.startswith('static'):
                continue
            m = re.match(r'static\s+[A-Za-z_][A-Za-z0-9_ \*]*?([fF][A-Z][A-Za-z0-9_]*)\s*[,;=\[]', line)
            if m:
                decl[m.group(1)] = i
            for extra in re.findall(r'[,\s]([fF][A-Z][A-Za-z0-9_]*)\s*[,;\[]', line):
                decl.setdefault(extra, i)
        for name, at in sorted(decl.items()):
            for i, line in enumerate(text.splitlines(), 1):
                if i >= at:
                    break
                if name in line and not line.lstrip().startswith(('static', '//', '/*', '*')):
                    problems.append(f'{rel}:{i}: {name} used before declaration at line {at}')
                    break
    return problems


def main():
    harness, source = sys.argv[1], sys.argv[2]
    only = sys.argv[3] if len(sys.argv) > 3 else None
    targets = patch_targets(harness, only)
    print(f'touched files: {len(targets)}')
    for t in targets:
        print('  ', t)
    problems = check_touched(source, targets)
    bad = check_filelists(source)
    for b in bad[:20]:
        print('MISSING FILELIST ENTRY:', b)
    for p in problems:
        print('PROBLEM:', p)
    if bad or problems:
        print(f'GATE-FAST FAIL ({len(bad)} filelist, {len(problems)} source)')
        return 1
    print('GATE-FAST PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
