"""Package app/garden-steward as a zip that Arduino App Lab can import.

App Lab accepts archive.zip/<root_dir>/app.yaml. Tests and local files are left out.

    python3 tools/make_applab_zip.py      # writes dist/garden-steward-applab.zip
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app", "garden-steward")
OUT = os.path.join(ROOT, "dist", "garden-steward-applab.zip")
SKIP_DIRS = {"tests", "__pycache__", ".pytest_cache"}
SKIP_FILES = {".gitignore", "garden_log.jsonl"}


def app_files():
    """(path on disk, path inside the zip) for every file that belongs in the App Lab app."""
    for folder, dirs, files in os.walk(APP):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            path = os.path.join(folder, name)
            yield path, os.path.join("garden-steward", os.path.relpath(path, APP))


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, arcname in app_files():
            # Fixed timestamps keep the zip identical when nothing changed.
            info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(path, "rb") as f:
                archive.writestr(info, f.read())
    print(f"wrote {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
