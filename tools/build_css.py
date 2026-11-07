"""Build Tailwind using its pinned standalone CLI; no Node or Python packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def compiler():
    lock = json.loads((ROOT / "tools/tailwind-lock.json").read_text(encoding="utf-8"))
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}.get(platform.system())
    arch = {"AMD64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine())
    suffix = "-musl" if system == "linux" and platform.libc_ver()[0] == "musl" else ""
    name = f"tailwindcss-{system}-{arch}{suffix}" + (".exe" if system == "windows" else "")
    expected = lock["sha256"].get(name)
    if expected is None:
        raise SystemExit(f"Unsupported standalone platform: {platform.system()} {platform.machine()}")
    path = ROOT / ".tools/tailwind" / lock["version"] / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/tailwindlabs/tailwindcss/releases/download/v{lock['version']}/{name}"
        request = urllib.request.Request(url, headers={"User-Agent": "MockExam-CSS-Build"})
        temporary = path.with_suffix(path.suffix + ".download")
        try:
            with urllib.request.urlopen(request, timeout=120) as source, temporary.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
            with temporary.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise SystemExit("Downloaded compiler checksum does not match tools/tailwind-lock.json.")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            raise SystemExit("Cached compiler checksum mismatch. Remove that cached file and retry.")
    if os.name != "nt":
        path.chmod(0o755)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="Rebuild on template/source changes")
    mode.add_argument("--check", action="store_true", help="Fail if the generated CSS is out of date")
    args = parser.parse_args()
    executable = compiler()
    output = ROOT / "static/css/tailwind.css"
    with tempfile.TemporaryDirectory(prefix="mock-css-") as directory:
        target = Path(directory) / "tailwind.css" if args.check else output
        command = [str(executable), "-i", "assets/tailwind.css", "-o", str(target), "--minify"]
        if args.watch:
            command.append("--watch")
        subprocess.run(command, cwd=ROOT, check=True)
        if args.check and (not output.exists() or target.read_bytes() != output.read_bytes()):
            raise SystemExit("Compiled CSS is stale. Run python tools/build_css.py.")
    print("Tailwind CSS is current." if args.check else "Built static/css/tailwind.css")


if __name__ == "__main__":
    main()
