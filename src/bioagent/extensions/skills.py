"""Safely discover local Skills and freeze their literal Markdown/text content."""

import hashlib
import json
import re
import stat
from pathlib import Path, PureWindowsPath
from typing import TypedDict, cast
from uuid import NAMESPACE_URL, uuid5

import yaml
from yaml.error import YAMLError

from bioagent.extensions.models import (
    SkillRecord,
    SkillReferenceSnapshot,
    SkillScan,
    SkillScanError,
    SkillSnapshot,
)

MAX_SKILL_FILE_BYTES = 64 * 1024
MAX_TURN_SKILL_BYTES = 128 * 1024
MAX_TURN_SKILLS = 3
MAX_REFERENCE_DEPTH = 3
_REFERENCE = re.compile(r"<!--\s*bioagent:include\s+([^\s>]+)\s*-->")
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)


class SkillPathError(ValueError):
    """A path was not a local child of the selected Skill directory."""

    def __init__(self, code: str = "SKILL_PATH_REJECTED") -> None:
        super().__init__(code)


class SkillValidationError(ValueError):
    """A Skill did not satisfy a deterministic content or lifecycle invariant."""

    def __init__(self, code: str = "SKILL_INVALID") -> None:
        super().__init__(code)


class _SkillFrontmatter(TypedDict):
    name: str
    description: str
    allowed_tools: list[str] | None


def _is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def resolve_reference(skill_directory: Path, relative_path: str) -> Path:
    """Resolve a text reference only when it stays inside its real Skill directory."""
    normalized = relative_path.replace("\\", "/")
    candidate = Path(relative_path)
    if (
        not relative_path
        or candidate.is_absolute()
        or PureWindowsPath(relative_path).drive
        or ":" in relative_path
        or ".." in normalized.split("/")
        or candidate.suffix.casefold() not in {".md", ".markdown", ".txt"}
    ):
        raise SkillPathError()
    try:
        root = skill_directory.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise SkillPathError() from exc
    if _is_symlink(skill_directory) or not root.is_dir():
        raise SkillPathError()
    current = root
    for component in normalized.split("/"):
        if component in {"", "."}:
            raise SkillPathError()
        current = current / component
        if _is_symlink(current):
            raise SkillPathError()
    try:
        result = (root / relative_path).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise SkillPathError() from exc
    if not result.is_relative_to(root) or not result.is_file():
        raise SkillPathError()
    return result


def _read_text(path: Path) -> tuple[str, str]:
    if _is_symlink(path):
        raise SkillPathError()
    try:
        before = path.stat()
    except OSError as exc:
        raise SkillValidationError() from exc
    if before.st_size > MAX_SKILL_FILE_BYTES:
        raise SkillValidationError("SKILL_TOO_LARGE")
    try:
        raw = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise SkillValidationError() from exc
    if before.st_ino != after.st_ino or before.st_size != after.st_size or _is_symlink(path):
        raise SkillPathError()
    if len(raw) > MAX_SKILL_FILE_BYTES:
        raise SkillValidationError("SKILL_TOO_LARGE")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillValidationError() from exc
    return text, hashlib.sha256(raw).hexdigest()


def _combined_hash(entry_hash: str, references: list[SkillReferenceSnapshot]) -> str:
    payload = json.dumps(
        {"entry": entry_hash, "references": [reference.sha256 for reference in references]},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _frontmatter(entry: str) -> tuple[_SkillFrontmatter, str]:
    match = _FRONTMATTER.match(entry)
    if match is None:
        raise SkillValidationError()
    try:
        parsed = yaml.safe_load(match.group(1))
    except YAMLError as exc:
        raise SkillValidationError() from exc
    if not isinstance(parsed, dict) or set(parsed) - {"name", "description", "allowed_tools"}:
        raise SkillValidationError()
    name = parsed.get("name")
    description = parsed.get("description")
    allowed_tools = parsed.get("allowed_tools")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(description, str)
        or not description.strip()
    ):
        raise SkillValidationError()
    if allowed_tools is not None and (
        isinstance(allowed_tools, str)
        or not isinstance(allowed_tools, list)
        or not all(isinstance(tool, str) and tool.strip() for tool in allowed_tools)
    ):
        raise SkillValidationError()
    tools = None if allowed_tools is None else cast(list[str], allowed_tools)
    return {
        "name": name,
        "description": description,
        "allowed_tools": tools,
    }, entry[match.end() :]


class SkillCatalog:
    """One-level, no-symlink discovery rooted in a user-selected local directory."""

    def __init__(self, root: Path, *, root_id: str) -> None:
        self._root = root
        self._root_id = root_id

    def scan(self) -> SkillScan:
        try:
            root = self._root.resolve(strict=True)
        except (FileNotFoundError, OSError):
            return SkillScan(errors=(SkillScanError(relative_path=".", code="SKILL_INVALID"),))
        if _is_symlink(self._root) or not root.is_dir():
            return SkillScan(
                errors=(SkillScanError(relative_path=".", code="SKILL_PATH_REJECTED"),)
            )
        records: list[SkillRecord] = []
        errors: list[SkillScanError] = []
        names: set[str] = set()
        for directory in sorted(root.iterdir(), key=lambda candidate: candidate.name.casefold()):
            if not directory.is_dir() or _is_symlink(directory):
                continue
            entry = directory / "SKILL.md"
            if not entry.exists():
                continue
            relative = entry.relative_to(root).as_posix()
            try:
                metadata, _, entry_hash, references = self._load_entry(directory, entry)
                name = metadata["name"]
                if not isinstance(name, str) or name in names:
                    raise SkillValidationError()
                names.add(name)
                record = SkillRecord(
                    id=uuid5(NAMESPACE_URL, f"bioagent:skill:{self._root_id}:{relative}"),
                    name=name,
                    description=metadata["description"],
                    root_id=self._root_id,
                    relative_path=relative,
                    sha256=_combined_hash(entry_hash, references),
                    requested_tools=(
                        None
                        if metadata["allowed_tools"] is None
                        else frozenset(metadata["allowed_tools"])
                    ),
                )
                records.append(record)
            except SkillPathError as exc:
                errors.append(SkillScanError(relative_path=relative, code=str(exc)))
            except SkillValidationError as exc:
                errors.append(SkillScanError(relative_path=relative, code=str(exc)))
        return SkillScan(records=tuple(records), errors=tuple(errors))

    def snapshot(
        self, record: SkillRecord, *, locally_authorized_tools: set[str] | frozenset[str]
    ) -> SkillSnapshot:
        if record.root_id != self._root_id:
            raise SkillValidationError("SKILL_NOT_FOUND")
        root = self._root.resolve(strict=True)
        entry = resolve_reference(root, record.relative_path)
        if entry.parent.parent != root:
            raise SkillPathError()
        metadata, content, entry_hash, references = self._load_entry(entry.parent, entry)
        combined = _combined_hash(entry_hash, references)
        if combined != record.sha256:
            raise SkillValidationError("SKILL_HASH_CONFLICT")
        allowed = metadata["allowed_tools"]
        requested = frozenset(allowed) if isinstance(allowed, list) else None
        local = frozenset(locally_authorized_tools)
        granted = local if requested is None else local & requested
        return SkillSnapshot(
            skill_id=record.id,
            name=record.name,
            description=record.description,
            content=content,
            entry_hash=entry_hash,
            references=tuple(references),
            sha256=combined,
            granted_tools=granted,
        )

    def _load_entry(
        self, directory: Path, entry: Path
    ) -> tuple[_SkillFrontmatter, str, str, list[SkillReferenceSnapshot]]:
        raw_entry, entry_hash = _read_text(entry)
        metadata, body = _frontmatter(raw_entry)
        references: list[SkillReferenceSnapshot] = []
        seen = {entry.resolve(strict=True)}

        def collect(text: str, depth: int) -> None:
            for relative_path in _REFERENCE.findall(text):
                if depth > MAX_REFERENCE_DEPTH:
                    raise SkillValidationError("SKILL_REFERENCE_DEPTH")
                reference = resolve_reference(directory, relative_path)
                if reference in seen:
                    raise SkillValidationError("SKILL_REFERENCE_CYCLE")
                seen.add(reference)
                reference_text, reference_hash = _read_text(reference)
                references.append(
                    SkillReferenceSnapshot(
                        relative_path=reference.relative_to(directory).as_posix(),
                        content=reference_text,
                        sha256=reference_hash,
                    )
                )
                collect(reference_text, depth + 1)

        collect(body, 1)
        total_bytes = len(raw_entry.encode("utf-8")) + sum(
            len(reference.content.encode("utf-8")) for reference in references
        )
        if total_bytes > MAX_TURN_SKILL_BYTES:
            raise SkillValidationError("SKILL_TOO_LARGE")
        return metadata, body, entry_hash, references


def validate_turn_snapshots(snapshots: tuple[SkillSnapshot, ...]) -> tuple[SkillSnapshot, ...]:
    """Enforce the per-turn loading limits without interpreting any Skill content."""
    if len(snapshots) > MAX_TURN_SKILLS:
        raise SkillValidationError("SKILL_TURN_LIMIT")
    total_bytes = sum(
        len(snapshot.content.encode("utf-8"))
        + sum(len(reference.content.encode("utf-8")) for reference in snapshot.references)
        for snapshot in snapshots
    )
    if total_bytes > MAX_TURN_SKILL_BYTES:
        raise SkillValidationError("SKILL_TOO_LARGE")
    return snapshots
