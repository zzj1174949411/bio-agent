from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_start_script_checks_prerequisites_and_owns_no_other_processes() -> None:
    script = ROOT / "scripts" / "start-workbench.ps1"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    for required in ("node", "uv", "Rscript", "frontend\\dist", "uvicorn", "127.0.0.1"):
        assert required.lower() in text.lower()
    assert "Stop-Process" not in text and "taskkill" not in text.lower()
    assert "npm run build" in text
