import bioagent


def test_package_exposes_version() -> None:
    assert bioagent.__version__ == "0.1.0"
