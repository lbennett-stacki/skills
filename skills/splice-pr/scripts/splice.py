#!/usr/bin/env python3
"""Splice one branch into a stack of smaller branches without rewriting code.

Every slice is built from the original diff by copying whole files (exact
blobs) or applying the original's own hunks. The final slice always carries
the original head tree, so the stack adds up to the original byte for byte.
Nothing here touches the working tree or the user's index: trees are built in
a throwaway index file and commits are made with commit-tree.

Subcommands:
  inventory  list changed files, hunks, categories and dependency hints
  build      turn a plan.json into commits, verify them, optionally set branches
  restack    after slices squash-merge, move the remaining slices onto the new base
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ZERO = "0" * 40


def git(*args: str, env: dict | None = None, input: str | bytes | None = None, check: bool = True) -> str:
    data = input.encode() if isinstance(input, str) else input
    proc = subprocess.run(["git", *args], input=data, capture_output=True, env=env)
    if check and proc.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{proc.stderr.decode(errors='replace')}")
    return proc.stdout.decode(errors="replace")


def rev(ref: str) -> str:
    return git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()


# ---------------------------------------------------------------- inventory


@dataclass
class Hunk:
    id: str
    header: str
    added: int
    removed: int
    text: str  # the hunk, starting at its @@ line

    def preview(self, n: int = 4) -> list[str]:
        lines = [l for l in self.text.splitlines()[1:] if l[:1] in "+-"]
        return lines[:n]


@dataclass
class Change:
    status: str  # A M D T R C
    path: str
    old_path: str | None
    old_mode: str
    new_mode: str
    old_blob: str
    new_blob: str
    added: int | None = None  # None for binary
    removed: int | None = None
    category: str = ""
    patch_header: str = ""
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def binary(self) -> bool:
        return self.added is None


CATEGORY_RULES: list[tuple[str, str]] = [
    ("migration", r"(^|/)(migrations?|alembic)/|\.sql$"),
    ("generated", r"(pnpm-lock\.yaml|package-lock\.json|yarn\.lock|uv\.lock|poetry\.lock|Cargo\.lock|go\.sum"
     r"|python-package-graph\.json|\.gen\.|_pb2\.py|/generated/|/__generated__/|openapi.*\.(json|ya?ml)|\.snap$)"),
    ("test", r"(^|/)(tests?|__tests__|e2e|spec)/|(^|/)test_[^/]*\.py$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$|conftest\.py$"),
    ("docs", r"\.(md|mdx|rst|txt)$|(^|/)docs/"),
    ("infra", r"(^|/)(terraform|\.github|deploy|deployment|k8s|helm)/|Dockerfile|\.tf$|docker-compose"),
    ("config", r"\.(ya?ml|toml|ini|cfg|json|env[^/]*)$|(^|/)\.[^/]+rc$"),
    ("schema", r"(^|/)(schema|models?)/|(^|/)models?\.py$"),
    ("frontend", r"\.(tsx|jsx|css|scss|vue|svelte)$|(^|/)(frontend|web|app|components|pages)/"),
]


def categorize(path: str) -> str:
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, path):
            return name
    return "code"


def load_changes(base: str, head: str, context: int, with_hunks: bool = True) -> tuple[str, list[Change]]:
    merge_base = git("merge-base", base, head).strip()
    raw = git("diff", "--raw", "-z", "-M", "--no-abbrev", merge_base, head).split("\0")
    changes: list[Change] = []
    i = 0
    while i < len(raw) and raw[i]:
        meta = raw[i].lstrip(":").split()
        old_mode, new_mode, old_blob, new_blob, status = meta
        kind = status[0]
        if kind in "RC":
            old_path, path = raw[i + 1], raw[i + 2]
            i += 3
        else:
            old_path, path = None, raw[i + 1]
            i += 2
        changes.append(Change(kind, path, old_path, old_mode, new_mode, old_blob, new_blob))

    by_path = {c.path: c for c in changes}
    num = git("diff", "--numstat", "-z", "-M", merge_base, head).split("\0")
    i = 0
    while i < len(num) and num[i]:
        added, removed, path = num[i].split("\t", 2)
        if path == "":  # rename: old and new follow as separate fields
            path = num[i + 2]
            i += 3
        else:
            i += 1
        c = by_path.get(path)
        if c and added != "-":
            c.added, c.removed = int(added), int(removed)

    for c in changes:
        c.category = categorize(c.path)
        if with_hunks and c.status == "M" and not c.binary:
            parse_hunks(c, merge_base, head, context)
    return merge_base, changes


def parse_hunks(c: Change, merge_base: str, head: str, context: int) -> None:
    out = git("diff", f"-U{context}", "--no-color", "--no-ext-diff", "--no-renames", merge_base, head, "--", c.path)
    header, hunks, current = [], [], None
    for line in out.splitlines(keepends=True):
        if line.startswith("@@"):
            current = [line]
            hunks.append(current)
        elif current is None:
            if not line.startswith(("old mode", "new mode", "index ")):
                header.append(line)
        else:
            current.append(line)
    c.patch_header = "".join(header)
    for n, lines in enumerate(hunks):
        body = lines[1:]
        c.hunks.append(Hunk(
            id=f"{c.path}#{n}",
            header=lines[0].rstrip("\n"),
            added=sum(1 for l in body if l.startswith("+")),
            removed=sum(1 for l in body if l.startswith("-")),
            text="".join(lines),
        ))


SYMBOL_DEF = re.compile(
    # top-level only: methods are reached as attributes, whose names collide with every library's
    r"^\+(?:async\s+)?(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"|^\+\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|const|let|class|type|interface|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)"
    r"|^\+([A-Z][A-Z0-9_]{3,})\s*[:=]"
)


def added_lines(merge_base: str, head: str, c: Change) -> list[str]:
    if c.binary or c.status == "D":
        return []
    if c.hunks:
        return [l for h in c.hunks for l in h.text.splitlines() if l.startswith("+")]
    out = git("diff", "-U0", "--no-color", "--no-ext-diff", merge_base, head, "--", c.path)
    return [l for l in out.splitlines() if l.startswith("+") and not l.startswith("+++")]


def module_tokens(path: str) -> list[str]:
    stem = re.sub(r"\.(py|tsx?|jsx?|mjs|cjs)$", "", path)
    if stem == path:
        return []
    stem = re.sub(r"/(index|__init__)$", "", stem)
    parts = stem.split("/")
    tokens = [".".join(parts)] if path.endswith(".py") else []
    if len(parts) >= 2:
        tokens.append("/".join(parts[-2:]))
    return tokens


def new_definitions(merge_base: str, head: str, changes: list[Change]) -> tuple[dict[str, set[str]], dict[str, list[str]], dict[str, list[str]]]:
    """(symbols each file newly defines, module tokens of each added file, added lines per file)."""
    adds = {c.path: added_lines(merge_base, head, c) for c in changes}
    defined: dict[str, set[str]] = {}
    for path, lines in adds.items():
        for line in lines:
            m = SYMBOL_DEF.match(line)
            if m:
                name = next(g for g in m.groups() if g)
                if len(name) >= 5 and not name.startswith("test"):
                    defined.setdefault(path, set()).add(name)
    # keep symbols that are new in this diff and defined in exactly one file
    owners: dict[str, list[str]] = {}
    for path, names in defined.items():
        for n in names:
            owners.setdefault(n, []).append(path)
    candidates = {n for n, ps in owners.items() if len(ps) == 1}
    status = {c.path: c.status for c in changes}
    for path, names in defined.items():
        # a name the file already had at the merge-base is an edit, not a new definition
        before = git("show", f"{merge_base}:{path}", check=False) if status[path] == "M" else ""
        defined[path] = {n for n in names if n in candidates and not re.search(rf"(?<![\w$]){re.escape(n)}(?![\w$])", before)}
    new_modules = {c.path: module_tokens(c.path) for c in changes if c.status in "AR"}
    return defined, new_modules, adds


def dependency_hints(merge_base: str, head: str, changes: list[Change]) -> dict[str, dict[str, list[str]]]:
    """file -> {file it seems to need: [evidence]}. Heuristic: symbols and modules the diff adds."""
    defined, new_modules, adds = new_definitions(merge_base, head, changes)
    category = {c.path: c.category for c in changes}
    hints: dict[str, dict[str, list[str]]] = {}
    for user, lines in adds.items():
        blob = "\n".join(lines)
        if not blob:
            continue
        for provider in set(defined) | set(new_modules):
            if provider == user or (category[provider] == "test" and category[user] != "test"):
                continue
            evidence = [s for s in sorted(defined.get(provider, ())) if re.search(rf"(?<![\w$]){re.escape(s)}(?![\w$])", blob)]
            evidence += [f"module {t}" for t in new_modules.get(provider, []) if t in blob]
            if evidence:
                hints.setdefault(user, {})[provider] = evidence[:6]
    return hints


def cmd_inventory(args: argparse.Namespace) -> None:
    merge_base, changes = load_changes(args.base, args.head, args.context)
    if args.hunks:
        wanted = set(args.hunks)
        for c in changes:
            if c.path in wanted:
                print(f"\n{c.path}  ({c.status}, {len(c.hunks)} hunks)")
                for h in c.hunks:
                    print(f"  {h.id}  +{h.added} -{h.removed}  {h.header}")
                    for l in h.preview(args.preview):
                        print(f"      {l[:140]}")
        return

    hints = dependency_hints(merge_base, args.head, changes)
    totals: dict[str, list[int]] = {}
    for c in changes:
        t = totals.setdefault(c.category, [0, 0, 0])
        t[0] += 1
        t[1] += c.added or 0
        t[2] += c.removed or 0

    print(f"base {args.base} -> merge-base {merge_base[:12]}; head {args.head} ({rev(args.head)[:12]})")
    print(f"{len(changes)} files, +{sum(c.added or 0 for c in changes)} -{sum(c.removed or 0 for c in changes)}\n")
    print("By category:")
    for name, (n, a, r) in sorted(totals.items(), key=lambda kv: -kv[1][1] - kv[1][2]):
        print(f"  {name:10} {n:4} files  +{a:<6} -{r}")
    print("\nFiles:")
    for c in sorted(changes, key=lambda c: (c.category, c.path)):
        size = "binary" if c.binary else f"+{c.added} -{c.removed}"
        hunks = f" {len(c.hunks)}h" if c.hunks else ""
        rename = f" (from {c.old_path})" if c.old_path else ""
        print(f"  {c.status} {c.category:9} {size:>12}{hunks:>5}  {c.path}{rename}")
    if hints:
        print("\nDependency hints (heuristic: a file's added lines mention symbols/modules another file adds):")
        for user in sorted(hints):
            for provider, ev in sorted(hints[user].items()):
                print(f"  {user} -> {provider}  [{', '.join(ev)}]")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "base": args.base, "head": args.head, "merge_base": merge_base, "head_commit": rev(args.head),
            "files": [{
                "path": c.path, "old_path": c.old_path, "status": c.status, "category": c.category,
                "added": c.added, "removed": c.removed,
                "hunks": [{"id": h.id, "header": h.header, "added": h.added, "removed": h.removed} for h in c.hunks],
            } for c in changes],
            "dependency_hints": hints,
        }, indent=2))
        print(f"\nwrote {args.json}")


# -------------------------------------------------------------------- build


def author_env(commit: str) -> dict:
    name, email, date = git("log", "-1", "--format=%an%x00%ae%x00%aD", commit).strip().split("\0")
    return {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": date}


def commit_tree(tree: str, parents: list[str], message: str, author_from: str) -> str:
    args = ["commit-tree", tree]
    for p in parents:
        args += ["-p", p]
    return git(*args, env=author_env(author_from), input=message).strip()


def merge_message(branches: list[str]) -> str:
    """git's own wording, so the join reads like any merge in the branch history."""
    quoted = [f"'{b}'" for b in branches]
    return f"Merge branches {', '.join(quoted[:-1])} and {quoted[-1]}"


def merge_trees(commits: list[str], author_from: str, message: str) -> str:
    """Octopus-style join commit whose tree is the union of the given commits."""
    acc = commits[0]
    for other in commits[1:]:
        proc = subprocess.run(["git", "merge-tree", "--write-tree", acc, other], capture_output=True, text=True)
        if proc.returncode != 0:
            sys.exit(f"parallel slices conflict when joined ({acc[:10]} + {other[:10]}):\n{proc.stdout}{proc.stderr}")
        acc = commit_tree(proc.stdout.split()[0], [acc, other], message, author_from)
    return commit_tree(git("rev-parse", f"{acc}^{{tree}}").strip(), commits, message, author_from)


def validate_plan(plan: dict, changes: dict[str, Change]) -> tuple[dict, dict]:
    slices = plan["slices"]
    ids = [s["id"] for s in slices]
    if len(set(ids)) != len(ids):
        sys.exit("slice ids must be unique")
    seen: set[str] = set()
    parent_of: dict[str, str | None] = {}
    for s in slices:
        p = s.get("after")
        if isinstance(p, list):
            sys.exit(f"slice {s['id']}: only the final slice may have several parents; use a single id or null")
        if p is not None and p not in seen:
            sys.exit(f"slice {s['id']}: parent {p!r} must be an earlier slice id (or null for the base)")
        parent_of[s["id"]] = p
        seen.add(s["id"])

    def ancestors(sid: str) -> list[str]:
        out = []
        while parent_of.get(sid):
            sid = parent_of[sid]
            out.append(sid)
        return out

    hunk_ids = {h.id: c for c in changes.values() for h in c.hunks}
    whole_owner: dict[str, str] = {}
    hunk_owner: dict[str, str] = {}
    errors = []
    for s in slices:
        for p in s.get("paths", []):
            if p not in changes:
                errors.append(f"{s['id']}: {p} is not changed in the original diff")
            elif p in whole_owner:
                errors.append(f"{p} is assigned to both {whole_owner[p]} and {s['id']}")
            else:
                whole_owner[p] = s["id"]
        for h in s.get("hunks", []):
            if h not in hunk_ids:
                errors.append(f"{s['id']}: unknown hunk {h} (run inventory --hunks with the same --context)")
            elif h in hunk_owner:
                errors.append(f"hunk {h} is assigned to both {hunk_owner[h]} and {s['id']}")
            else:
                hunk_owner[h] = s["id"]
        if not s.get("paths") and not s.get("hunks"):
            errors.append(f"{s['id']}: slice has no paths or hunks")
    for p, owner in whole_owner.items():
        c = changes[p]
        if c.old_path and c.status == "R" and c.old_path in whole_owner and whole_owner[c.old_path] != owner:
            errors.append(f"rename {c.old_path} -> {p} is split across slices")
        for h in c.hunks:
            hs = hunk_owner.get(h.id)
            if hs and hs != owner and hs not in ancestors(owner):
                errors.append(f"{h.id} is in {hs} but the whole file is in {owner}, which does not build on {hs}")
    if errors:
        sys.exit("plan errors:\n  " + "\n  ".join(errors))
    return whole_owner, hunk_owner


def build_slice_tree(parent_commit: str, slice_: dict, changes: dict[str, Change], base_dir: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(tmp, "index")}
        git("read-tree", parent_commit, env=env)
        entries = []
        for p in slice_.get("paths", []):
            c = changes[p]
            if c.old_path and c.status == "R":
                entries.append(f"0 {ZERO}\t{c.old_path}")
            if c.status == "D":
                entries.append(f"0 {ZERO}\t{c.path}")
            else:
                entries.append(f"{c.new_mode} {c.new_blob}\t{c.path}")
        if entries:
            git("update-index", "-z", "--index-info", env=env, input="\0".join(entries) + "\0")

        by_file: dict[str, list[str]] = {}
        for hid in slice_.get("hunks", []):
            by_file.setdefault(hid.rsplit("#", 1)[0], []).append(hid)
        for path, hids in by_file.items():
            c = changes[path]
            order = {h.id: n for n, h in enumerate(c.hunks)}
            text = c.patch_header + "".join(c.hunks[order[h]].text for h in sorted(hids, key=order.__getitem__))
            proc = subprocess.run(["git", "apply", "--cached", "-"], input=text.encode(), capture_output=True, env=env)
            if proc.returncode != 0:
                sys.exit(f"slice {slice_['id']}: hunks of {path} do not apply on their parent:\n"
                         f"{proc.stderr.decode()}\nMove these hunks with the hunks they depend on, or take the whole file.")

        if slice_.get("glue"):
            glue = (base_dir / slice_["glue"]).read_text()
            proc = subprocess.run(["git", "apply", "--cached", "-"], input=glue.encode(), capture_output=True, env=env)
            if proc.returncode != 0:
                sys.exit(f"slice {slice_['id']}: glue patch does not apply:\n{proc.stderr.decode()}")
        return git("write-tree", env=env).strip()


COMMENT_LINE = re.compile(r"\s*(#|//|/\*|\*|--|\"\"\"|''')")


def find_forward_refs(slices: list[dict], commits: dict, parents: dict, merge_base: str, head: str,
                      changes: list[Change]) -> list[str]:
    """Symbols and modules new in the original that a slice's added lines use but its tree lacks."""
    defined, new_modules, _ = new_definitions(merge_base, head, changes)
    found = []
    for s in slices:
        commit = commits[s["id"]]
        diff = git("diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", parents[s["id"]], commit)
        added_by_file: dict[str, list[str]] = {}
        current = None
        for l in diff.splitlines():
            if l.startswith("+++ "):
                current = l[6:] if l.startswith("+++ b/") else None
            elif l.startswith("+") and current and not COMMENT_LINE.match(l[1:]):
                added_by_file.setdefault(current, []).append(l)
        if not added_by_file:
            continue
        before = {p: git("show", f"{merge_base}:{p}", check=False) for p in added_by_file}
        tree_files = set(git("ls-tree", "-r", "--name-only", "-z", commit).split("\0"))

        def uses(name: str, provider: str) -> bool:
            word = re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")
            for path, lines in added_by_file.items():
                if categorize(provider) == "test" and categorize(path) != "test":
                    continue  # test helpers only matter to tests
                if word.search(before[path]):
                    continue  # the file already used this name before the PR: not the new definition
                if word.search("\n".join(lines)):
                    return True
            return False

        blob = "\n".join(l for lines in added_by_file.values() for l in lines)
        for provider, names in defined.items():
            used = [n for n in names if uses(n, provider)]
            if not used:
                continue
            content = git("show", f"{commit}:{provider}", check=False) if provider in tree_files else ""
            missing = [n for n in used if not re.search(rf"(?<![\w$]){re.escape(n)}(?![\w$])", content)]
            if missing:
                found.append(f"{s['id']}: uses {', '.join(missing)} from {provider}, not in this slice's tree")
        for provider, tokens in new_modules.items():
            hit = [t for t in tokens if t in blob]
            if hit and provider not in tree_files:
                found.append(f"{s['id']}: mentions module {hit[0]} ({provider}), not in this slice's tree")
    return found


def state_path(name: str) -> Path:
    common = Path(git("rev-parse", "--git-common-dir").strip()).resolve()
    return common / "splice" / f"{re.sub(r'[^A-Za-z0-9._-]', '_', name)}.json"


def set_branch(branch: str, commit: str, force: bool, stamp: str) -> str:
    ref = f"refs/heads/{branch}"
    old = git("rev-parse", "--verify", "-q", ref, check=False).strip()
    if old == commit:
        return "unchanged"
    if old:
        if not force:
            sys.exit(f"branch {branch} exists at {old[:10]}; pass --force to move it (a backup ref is kept)")
        git("update-ref", f"refs/splice-backup/{branch}/{stamp}", old)
        git("update-ref", ref, commit, old)
        return f"moved from {old[:10]} (backup refs/splice-backup/{branch}/{stamp})"
    git("update-ref", ref, commit, ZERO)
    return "created"


def cmd_build(args: argparse.Namespace) -> None:
    plan_file = Path(args.plan)
    plan = json.loads(plan_file.read_text())
    head_commit = rev(plan["head"])
    merge_base, change_list = load_changes(plan["base"], head_commit, plan.get("context", 3))
    changes = {c.path: c for c in change_list}
    whole_owner, hunk_owner = validate_plan(plan, changes)

    head_ref = plan["head"].removeprefix("refs/heads/")
    for b in [s["branch"] for s in plan["slices"]] + [plan["final"]["branch"]]:
        if b == head_ref or git("rev-parse", "-q", "--verify", f"refs/heads/{b}", check=False).strip() == head_commit:
            sys.exit(f"branch {b} is the original; every slice, the final one included, gets a new branch "
                     "so the original PR stays as it is")

    commits: dict[str, str] = {}
    parents: dict[str, str] = {}
    report = []
    for s in plan["slices"]:
        parent = commits[s["after"]] if s.get("after") else merge_base
        tree = build_slice_tree(parent, s, changes, plan_file.parent)
        if tree == git("rev-parse", f"{parent}^{{tree}}").strip():
            sys.exit(f"slice {s['id']} is empty on top of its parent")
        commits[s["id"]] = commit_tree(tree, [parent], s["message"], head_commit)
        parents[s["id"]] = parent

    final = plan["final"]
    after = final.get("after") or []
    after = [after] if isinstance(after, str) else after
    tips = [commits[a] for a in after] or [merge_base]
    branch_of = {s["id"]: s["branch"] for s in plan["slices"]}
    join = tips[0] if len(tips) == 1 else merge_trees(tips, head_commit, merge_message([branch_of[a] for a in after]))
    head_tree = git("rev-parse", f"{head_commit}^{{tree}}").strip()
    final_commit = commit_tree(head_tree, [join], final["message"], head_commit)

    # verification: slices touch only what they were given, whole files are exact copies,
    # and the final slice is the original head tree.
    problems = []
    for s in plan["slices"]:
        allowed = set(s.get("paths", [])) | {h.rsplit("#", 1)[0] for h in s.get("hunks", [])}
        allowed |= {changes[p].old_path for p in s.get("paths", []) if changes[p].old_path and changes[p].status == "R"}
        glue_files = set()
        if s.get("glue"):
            glue_files = set(re.findall(r"^\+\+\+ b/(.+)$", (plan_file.parent / s["glue"]).read_text(), re.M))
        touched = [p for p in git("diff", "--name-only", "-z", "--no-renames", parents[s["id"]], commits[s["id"]]).split("\0") if p]
        stray = [p for p in touched if p not in allowed | glue_files]
        if stray:
            problems.append(f"{s['id']} touches unassigned paths: {stray}")
        for p in s.get("paths", []):
            c = changes[p]
            got = git("rev-parse", "-q", "--verify", f"{commits[s['id']]}:{p}", check=False).strip()
            want = "" if c.status == "D" else c.new_blob
            if got != want:
                problems.append(f"{s['id']}: {p} is not an exact copy of the original")
        stat = git("diff", "--shortstat", parents[s["id"]], commits[s["id"]]).strip()
        report.append((s["id"], s.get("branch", ""), commits[s["id"]], stat, bool(s.get("glue"))))
    if git("rev-parse", f"{final_commit}^{{tree}}").strip() != head_tree:
        problems.append("final slice tree differs from the original head tree")
    if problems:
        sys.exit("verification failed:\n  " + "\n  ".join(problems))

    forward_refs = find_forward_refs(plan["slices"], commits, parents, merge_base, head_commit, change_list)

    remainder = git("diff", "--shortstat", join, final_commit).strip()
    report.append(("final", final.get("branch", ""), final_commit, remainder or "(empty)", False))
    unassigned_paths = [p for p in changes if p not in whole_owner and not any(h.id in hunk_owner for h in changes[p].hunks)]
    partial = sorted({h.rsplit("#", 1)[0] for h in hunk_owner} - set(whole_owner))

    print(f"merge-base {merge_base[:12]}  original {head_commit[:12]}\n")
    for sid, branch, commit, stat, has_glue in report:
        print(f"  {sid:18} {commit[:12]}  {branch or '(no branch)':45} {stat}{'  [GLUE]' if has_glue else ''}")
    print(f"\nverified: slices touch only their assigned paths, whole files are exact copies, final tree == original tree")
    print(f"final slice keeps {len(unassigned_paths)} untouched files plus the rest of {len(partial)} partly-sliced files")
    if any(r[4] for r in report):
        print("WARNING: at least one slice carries a glue patch, i.e. code the original did not have")
    if forward_refs:
        print("\nWARNING forward references (a slice uses something the original adds, but a later slice brings it):")
        for line in forward_refs:
            print(f"  {line}")
        if not args.allow_forward_refs:
            sys.exit("\nfix the plan (move the provider earlier or the user later), or pass --allow-forward-refs "
                     "if each one is a false positive you have checked")

    if args.dry_run:
        print("\ndry run: no branches changed")
        return

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for s in plan["slices"]:
        print(f"  {s['branch']}: {set_branch(s['branch'], commits[s['id']], args.force, stamp)}")
    print(f"  {final['branch']}: {set_branch(final['branch'], final_commit, args.force, stamp)}")

    state = {
        "plan": plan, "plan_file": str(plan_file.resolve()), "merge_base": merge_base,
        "original_head": head_commit, "built_at": stamp, "join": join if len(tips) > 1 else None,
        "slices": [{"id": s["id"], "branch": s["branch"], "after": s.get("after"),
                    "commit": commits[s["id"]], "merged": False} for s in plan["slices"]],
        "final": {"branch": final["branch"], "after": after, "commit": final_commit, "base": join},
    }
    sp = state_path(final["branch"])
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state, indent=2))
    print(f"\nstate: {sp}")
    print(f"original head kept at {head_commit} (also in the reflog and any backup ref above)")


# ------------------------------------------------------------------ restack


def replay(old_parent: str, new_parent: str, old_commit: str, label: str) -> str:
    if old_parent == new_parent:
        return old_commit
    proc = subprocess.run(["git", "merge-tree", "--write-tree", "--merge-base", old_parent, new_parent, old_commit],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"{label} conflicts with the new base; resolve by hand:\n{proc.stdout}{proc.stderr}")
    message = git("log", "-1", "--format=%B", old_commit)
    return commit_tree(proc.stdout.split()[0], [new_parent], message, old_commit)


def cmd_restack(args: argparse.Namespace) -> None:
    sp = Path(args.state) if args.state else state_path(args.branch)
    state = json.loads(sp.read_text())
    onto = rev(args.onto)
    merged = set(filter(None, (args.merged or "").split(",")))
    known = {s["id"] for s in state["slices"]}
    if merged - known:
        sys.exit(f"unknown slice ids: {sorted(merged - known)}")
    for s in state["slices"]:
        s["merged"] = s["merged"] or s["id"] in merged

    new_commit: dict[str, str] = {}
    old_commit = {s["id"]: s["commit"] for s in state["slices"]}
    old_parent_of = {s["id"]: (old_commit[s["after"]] if s["after"] else state["merge_base"]) for s in state["slices"]}
    moves = []
    for s in state["slices"]:
        if s["merged"]:
            continue
        p = s["after"]
        if p and p in new_commit:
            new_parent = new_commit[p]
        elif p or args.all:  # parent landed, or asked to refresh every root slice
            new_parent = onto
        else:  # an untouched root slice stays put: its diff against the base is still right
            new_parent = old_parent_of[s["id"]]
        new_commit[s["id"]] = replay(old_parent_of[s["id"]], new_parent, s["commit"], s["id"])
        moves.append((s, new_commit[s["id"]]))

    f = state["final"]
    live = [new_commit[a] for a in f["after"] if a in new_commit]
    if not live:
        new_base = onto
    elif len(live) == 1:
        new_base = live[0]
    else:
        branch_of = {s["id"]: s["branch"] for s in state["slices"]}
        new_base = merge_trees(live, f["commit"], merge_message([branch_of[a] for a in f["after"] if a in new_commit]))
    final_commit = replay(f["base"], new_base, f["commit"], "final")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    pushes = []
    for s, c in moves:
        if c != s["commit"]:
            if not args.dry_run:
                print(f"  {s['branch']}: {set_branch(s['branch'], c, True, stamp)}")
            pushes.append((s["branch"], s["commit"]))
            s["commit"] = c
    if final_commit != f["commit"]:
        if not args.dry_run:
            print(f"  {f['branch']}: {set_branch(f['branch'], final_commit, True, stamp)}")
        pushes.append((f["branch"], f["commit"]))
        f["commit"], f["base"] = final_commit, new_base
    if args.dry_run:
        print("dry run: would move " + (", ".join(b for b, _ in pushes) or "nothing"))
        return
    sp.write_text(json.dumps(state, indent=2))
    if pushes:
        print("\npush (after the user confirms):")
        for branch, old in pushes:
            print(f"  git push --force-with-lease={branch}:{old} origin {branch}")
    else:
        print("nothing to move")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("inventory", help="list what the original changes")
    inv.add_argument("--base", default="origin/main")
    inv.add_argument("--head", required=True)
    inv.add_argument("--context", type=int, default=3, help="hunk context lines; use the same value in plan.json")
    inv.add_argument("--hunks", nargs="+", metavar="PATH", help="print hunk ids and previews for these files only")
    inv.add_argument("--preview", type=int, default=4)
    inv.add_argument("--json")
    inv.set_defaults(fn=cmd_inventory)

    b = sub.add_parser("build", help="build and verify slices from plan.json")
    b.add_argument("plan")
    b.add_argument("--dry-run", action="store_true", help="build and verify commits, change no branches")
    b.add_argument("--force", action="store_true", help="move existing branches (backup refs kept)")
    b.add_argument("--allow-forward-refs", action="store_true", help="proceed despite checked false positives")
    b.set_defaults(fn=cmd_build)

    r = sub.add_parser("restack", help="move remaining slices onto a new base after some merged")
    r.add_argument("--branch", help="final branch name (locates the state file)")
    r.add_argument("--state")
    r.add_argument("--merged", help="comma-separated slice ids that have landed")
    r.add_argument("--onto", default="origin/main")
    r.add_argument("--all", action="store_true", help="also move root slices that did not need it")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_restack)

    args = ap.parse_args()
    if args.cmd == "restack" and not (args.branch or args.state):
        ap.error("restack needs --branch or --state")
    args.fn(args)


if __name__ == "__main__":
    main()
