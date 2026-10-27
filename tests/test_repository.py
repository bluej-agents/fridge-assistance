from pathlib import Path
import subprocess


def test_private_runtime_files_are_ignored():
    paths = [".env", ".env.local", "data/private.json", "uploads/photo.jpg", "logs/run.log", "content/post.md", "materials/prompt.md", ".venv/test", "bundle.zip"]
    result = subprocess.run(["git", "check-ignore", "--no-index", *paths], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == set(paths)
    assert subprocess.run(["git", "check-ignore", "--no-index", ".env.example"], capture_output=True).returncode == 1


def test_public_template_contains_no_key_and_materials_are_outside_repo():
    assert not Path("content").exists()
    assert not Path("materials").exists()
    for line in Path(".env.example").read_text().splitlines():
        if line.startswith("MODEL_"):
            assert line.split("=", 1)[1] == ""
