"""Offline contracts for the explicitly authorized manual live acceptance."""

import json
import sqlite3
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from verify_parkinson_live import (  # noqa: E402
    CallBudget,
    require_live,
    resolve_saved_profile,
    select_samples,
    traits,
    validate_counts,
)


def sample(gsm, patient, disease="Control", region="CAU"):
    return {
        "accession": gsm,
        "title": gsm,
        "organism": "Homo sapiens",
        "platform": "GPL24676",
        "characteristics": [
            {"value": f"patient: {patient}"},
            {"value": f"disease: {disease}"},
            {"value": f"region: {region}"},
        ],
    }


def source():
    return {
        "samples": [
            *[sample(f"C{i}", f"control{i}") for i in range(3)],
            *[sample(f"P{i}", f"patient{i}", "PD") for i in range(3)],
            sample("other_region", "patient0", "PD", "PUT"),
        ]
    }


def test_selection_excludes_other_region_and_preserves_all_independent_donors():
    chosen, excluded = select_samples(
        source(), ["GeneID", "C0", "C1", "C2", "P0", "P1", "P2", "other_region"]
    )
    assert len(chosen) == 6
    assert {row["group"] for row in chosen} == {"Control", "PD"}
    assert excluded == ["other_region"]


def test_duplicate_donor_is_rejected_even_if_sample_ids_differ():
    data = source()
    data["samples"][1]["characteristics"][0]["value"] = "patient: control0"
    with pytest.raises(ValueError, match="DUPLICATE_DONOR"):
        select_samples(data, [row["accession"] for row in data["samples"]])


def test_missing_matrix_sample_is_not_silently_dropped():
    with pytest.raises(ValueError, match="SAMPLE_COLUMN_MISSING"):
        select_samples(source(), ["C0", "C1", "C2", "P0", "P1"])


@pytest.mark.parametrize("bad", [1.25, -1, float("inf"), float("nan")])
def test_counts_are_never_rounded_or_imputed(bad):
    with pytest.raises(ValueError, match="INVALID_RAW_COUNTS"):
        validate_counts(pd.DataFrame({"a": [bad]}), "RAW_COUNTS")


def test_normalized_source_is_rejected_even_if_values_look_integer():
    with pytest.raises(ValueError, match="RAW_SOURCE_REQUIRED"):
        validate_counts(pd.DataFrame({"a": [1, 2]}), "TPM")


def test_no_live_flag_stops_before_requests():
    with pytest.raises(ValueError, match="EXPLICIT_LIVE_REQUIRED"):
        require_live(False)


def test_budget_rejects_next_call_without_touching_previous_evaluation(tmp_path):
    budget = CallBudget(tmp_path / "calls.json", maximum_calls=1)
    budget.reserve({"messages": [{"role": "user", "content": "public data"}]})
    with pytest.raises(ValueError, match="LIVE_CALL_LIMIT"):
        budget.reserve({"messages": []})
    assert len(budget.calls) == 1
    assert budget.calls[0]["input_bytes"] > 0


def test_live_uses_saved_profile_credential_instead_of_environment_fallback(tmp_path):
    from pydantic import SecretStr

    identity = str(uuid4())
    record = {
        "id": identity,
        "label": "my-deepseek",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "structured_method": "function_calling",
        "thinking": "disabled",
        "revision": 1,
        "credential_ref": "keyring:existing-profile",
    }
    db_path = tmp_path / "workbench.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE model_profiles(record TEXT, deleted INTEGER)")
        db.execute("INSERT INTO model_profiles VALUES (?,0)", (json.dumps(record),))

    class Secrets:
        def get(self, reference):
            assert reference == "keyring:existing-profile"
            return SecretStr("fixture-not-a-real-key")

    profile, credential = resolve_saved_profile(db_path, identity, Secrets())
    assert str(profile.id) == identity
    assert credential.get_secret_value() == "fixture-not-a-real-key"


def test_metadata_label_with_embedded_colons_keeps_sex_value_separate():
    values = traits(
        {
            "characteristics": [
                {"value": "gender (m: male, f: female): F"},
                {"value": "rna integrity number (rin): 6.2"},
                {"value": "disease: PD"},
            ]
        }
    )
    assert values["gender (m: male, f: female)"] == "F"
    assert values["rna integrity number (rin)"] == "6.2"
    assert values["disease"] == "PD"
