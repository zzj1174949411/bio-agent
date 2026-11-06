from pathlib import Path

import pytest

from bioagent.extensions.models import SkillSnapshot
from bioagent.extensions.skills import (
    SkillCatalog,
    SkillPathError,
    SkillValidationError,
    resolve_reference,
)
from bioagent.extensions.store import SkillStore


def test_reference_cannot_escape_skill(tmp_path):
    skill = tmp_path / "skills" / "rnaseq"
    skill.mkdir(parents=True)

    with pytest.raises(SkillPathError, match="SKILL_PATH_REJECTED"):
        resolve_reference(skill, "../../secrets.txt")


@pytest.mark.parametrize(
    "reference",
    ["/absolute.txt", "C:/secrets.txt", "https://example.test/skill.md", "../secret.txt"],
)
def test_reference_rejects_absolute_remote_and_parent_paths(tmp_path, reference):
    skill = tmp_path / "skills" / "rnaseq"
    skill.mkdir(parents=True)

    with pytest.raises(SkillPathError, match="SKILL_PATH_REJECTED"):
        resolve_reference(skill, reference)


def write_skill(
    directory: Path, *, name: str = "RNA review", body: str = "Read carefully."
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    entry = directory / "SKILL.md"
    entry.write_text(
        f"---\nname: {name}\ndescription: Safe local instructions\n---\n{body}\n",
        encoding="utf-8",
    )
    return entry


def test_discovers_only_one_level_and_reports_minimal_invalid_boundaries(tmp_path):
    root = tmp_path / "skills"
    write_skill(root / "rna")
    write_skill(root / "nested" / "ignored")
    write_skill(root / "zzzduplicate", name="RNA review")
    (root / "missing").mkdir()
    no_frontmatter = root / "no-frontmatter"
    no_frontmatter.mkdir()
    (no_frontmatter / "SKILL.md").write_text("plain Markdown", encoding="utf-8")
    unsafe = root / "unsafe"
    unsafe.mkdir()
    (unsafe / "SKILL.md").write_text(
        "---\nname: !!python/object/apply:os.system ['never run']\ndescription: no\n---\ntext",
        encoding="utf-8",
    )
    (root / "bad-utf8").mkdir()
    (root / "bad-utf8" / "SKILL.md").write_bytes(b"---\nname: bad\ndescription: bad\n---\n\xff")
    huge = root / "huge"
    huge.mkdir()
    (huge / "SKILL.md").write_bytes(b"x" * (64 * 1024 + 1))

    scan = SkillCatalog(root, root_id="local").scan()

    assert [record.name for record in scan.records] == ["RNA review"]
    assert {error.code for error in scan.errors} == {"SKILL_INVALID", "SKILL_TOO_LARGE"}
    assert all(record.relative_path == "rna/SKILL.md" for record in scan.records)


def test_snapshot_freezes_entry_references_and_combined_hash(tmp_path):
    root = tmp_path / "skills"
    entry = write_skill(
        root / "rna",
        body="Use <!-- bioagent:include review.md --> as a local reference.",
    )
    reference = entry.parent / "review.md"
    reference.write_text("Do not execute `${TOKEN}`.", encoding="utf-8")
    catalog = SkillCatalog(root, root_id="local")
    record = catalog.scan().records[0]

    first = catalog.snapshot(record, locally_authorized_tools={"mcp.local.read", "run.status"})
    reference.write_text("Changed, but still literal `${TOKEN}`.", encoding="utf-8")
    second = catalog.snapshot(catalog.scan().records[0], locally_authorized_tools={"run.status"})

    assert first.content.rstrip().endswith("as a local reference.")
    assert first.references[0].content == "Do not execute `${TOKEN}`."
    assert "${TOKEN}" in second.references[0].content
    assert first.sha256 != second.sha256
    assert first.granted_tools == frozenset({"mcp.local.read", "run.status"})
    assert second.granted_tools == frozenset({"run.status"})


def test_snapshot_rejects_reference_depth_and_cycles(tmp_path):
    root = tmp_path / "skills"
    entry = write_skill(root / "rna", body="<!-- bioagent:include a.md -->")
    a = entry.parent / "a.md"
    a.write_text("<!-- bioagent:include b.md -->", encoding="utf-8")
    b = entry.parent / "b.md"
    b.write_text("<!-- bioagent:include c.md -->", encoding="utf-8")
    (entry.parent / "c.md").write_text("<!-- bioagent:include d.md -->", encoding="utf-8")
    (entry.parent / "d.md").write_text("end", encoding="utf-8")

    depth_scan = SkillCatalog(root, root_id="local").scan()
    assert depth_scan.records == ()
    assert depth_scan.errors[0].code == "SKILL_REFERENCE_DEPTH"

    b.write_text("<!-- bioagent:include a.md -->", encoding="utf-8")
    cycle_scan = SkillCatalog(root, root_id="local").scan()
    assert cycle_scan.records == ()
    assert cycle_scan.errors[0].code == "SKILL_REFERENCE_CYCLE"


def test_rejects_symlink_reference_when_platform_permits_it(tmp_path):
    root = tmp_path / "skills"
    entry = write_skill(root / "rna", body="<!-- bioagent:include linked.md -->")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    try:
        (entry.parent / "linked.md").symlink_to(outside)
    except OSError:
        pytest.skip("directory symlink permission unavailable on this Windows host")

    record = SkillCatalog(root, root_id="local").scan().records[0]
    with pytest.raises(SkillPathError, match="SKILL_PATH_REJECTED"):
        SkillCatalog(root, root_id="local").snapshot(record, locally_authorized_tools=set())


def test_enable_binds_hash_and_preserves_old_snapshot_after_disable(tmp_path):
    root = tmp_path / "skills"
    write_skill(root / "rna", body="<!-- bioagent:include review.md -->")
    (root / "rna" / "review.md").write_text("v1", encoding="utf-8")
    catalog = SkillCatalog(root, root_id="local")
    record = catalog.scan().records[0]
    snapshot = catalog.snapshot(record, locally_authorized_tools={"run.status"})

    with SkillStore(tmp_path / "workbench.sqlite") as store:
        store.sync((record,))
        with pytest.raises(SkillValidationError, match="SKILL_HASH_CONFLICT"):
            store.enable(record.id, expected_hash="0" * 64, snapshot=snapshot)
        enabled = store.enable(record.id, expected_hash=record.sha256, snapshot=snapshot)
        assert store.enabled_directory() == (enabled,)
        assert store.load_enabled(record.id) == snapshot
        (root / "rna" / "review.md").write_text("v2", encoding="utf-8")
        changed = SkillCatalog(root, root_id="local").scan().records[0]
        store.sync((changed,))
        assert store.enabled_directory() == ()
        store.disable(record.id)
        with pytest.raises(SkillValidationError, match="SKILL_DISABLED"):
            store.load_enabled(record.id)
        assert snapshot.references[0].content == "v1"


def test_allowed_tools_is_only_an_upper_bound(tmp_path):
    root = tmp_path / "skills"
    entry = write_skill(root / "restricted")
    entry.write_text(
        (
            "---\nname: Restricted\ndescription: Local\n"
            "allowed_tools: [run.status, mcp.server.read]\n---\ntext"
        ),
        encoding="utf-8",
    )
    write_skill(root / "unrestricted", name="Unrestricted")
    catalog = SkillCatalog(root, root_id="local")
    restricted, unrestricted = catalog.scan().records

    assert catalog.snapshot(
        restricted, locally_authorized_tools={"run.status", "run.artifacts"}
    ).granted_tools == frozenset({"run.status"})
    assert catalog.snapshot(
        unrestricted, locally_authorized_tools={"run.status", "run.artifacts"}
    ).granted_tools == frozenset({"run.status", "run.artifacts"})


def test_snapshot_model_is_frozen():
    snapshot = SkillSnapshot(
        skill_id="00000000-0000-0000-0000-000000000001",
        name="name",
        description="description",
        content="literal ${SECRET}",
        entry_hash="0" * 64,
        references=(),
        sha256="1" * 64,
        granted_tools=frozenset(),
    )

    with pytest.raises((TypeError, ValueError)):
        snapshot.content = "changed"
