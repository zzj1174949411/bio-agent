import sys
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from verify_public_matrix import locked_cache, sample_design  # noqa: E402


def test_public_acceptance_summary_includes_alpha_boundary():
    from verify_public_matrix import verify_result_summary

    table = pd.DataFrame(
        {"padj": [0.01, 0.05, 0.05, 0.2, None], "log2FoldChange": [1, 1, -1, -1, 1]}
    )
    summary = {"genes": 5, "adjusted_p_available": 4, "significant_up": 2, "significant_down": 1}
    verify_result_summary(table, 0.05, summary)
    with pytest.raises(AssertionError):
        verify_result_summary(table, 0.05, {**summary, "significant_up": 1})


def test_offline_cache_requires_existing_unchanged_bytes(tmp_path):
    path = tmp_path / "source.gz"
    digest = sha256(b"official bytes").hexdigest()
    with pytest.raises(ValueError, match="CACHE_MISSING"):
        locked_cache(path, digest)
    path.write_bytes(b"official bytes")
    assert locked_cache(path, digest) == b"official bytes"
    path.write_bytes(b"tampered bytes")
    with pytest.raises(ValueError, match="CACHE_HASH_MISMATCH"):
        locked_cache(path, digest)


def test_sample_mapping_requires_official_identity_and_stage():
    samples = []
    headers = ["EntrezGeneID", "Length"]
    for gsm, name, stage in [
        ("GSM1480297", "DG", "virgin"),
        ("GSM1480298", "DH", "virgin"),
        ("GSM1480301", "DK", "2 day lactation"),
        ("GSM1480302", "DL", "2 day lactation"),
    ]:
        column = f"MCL1-{name}_official"
        headers.append(column)
        samples.append(
            {
                "accession": gsm,
                "platform": "GPL13112",
                "characteristics": [
                    {"value": "immunophenotype: basal cell population"},
                    {"value": "developmental stage: " + stage},
                ],
                "fields": [{"name": "Sample_description", "value": column}],
            }
        )
    mapping, groups, excluded = sample_design({"samples": samples}, headers)
    assert list(groups.values()) == ["Virgin", "Virgin", "Lactating", "Lactating"]
    assert list(mapping) == headers[2:] and excluded == []
    samples[-1]["characteristics"][-1]["value"] = "developmental stage: virgin"
    with pytest.raises(ValueError, match="SAMPLE_EVIDENCE_MISMATCH"):
        sample_design({"samples": samples}, headers)
