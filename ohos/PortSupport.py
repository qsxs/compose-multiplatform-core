"""独立 Material Icons 构建所需的文件、工具与隔离校验。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

TOOL_COMMIT = "d0cff88fd1ea2e4f08bb4409f1c802cca0c7f285"
TOOL_PREFIX = "toolchains/kotlin-native/2.4.20-0.1.0-08/"


def physical(path):
    path = Path(path).absolute()
    if os.name != "nt":
        return path
    text = str(path)
    if text.startswith("\\\\?\\"):
        return path
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def load(path):
    return json.loads(physical(path).read_text(encoding="utf-8-sig"))


def logical(path):
    text = str(path)
    if os.name == "nt" and text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif os.name == "nt" and text.startswith("\\\\?\\"):
        text = text[4:]
    return Path(text)


def record(path, base=None):
    path = Path(path)
    data = physical(path).read_bytes()
    display = logical(path)
    return {"path": display.relative_to(logical(base)).as_posix() if base else str(display),
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write(path, value):
    path = physical(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError("Existing immutable file differs: " + str(path))
        return
    with path.open("xb") as output:
        output.write(data)


def environment(work=None):
    names = ("PATH", "HOME", "USERPROFILE", "SystemRoot", "ComSpec", "JAVA_HOME", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "LD_LIBRARY_PATH")
    env = {key: os.environ[key] for key in names if key in os.environ}
    env["GIT_NO_LAZY_FETCH"] = "1"
    if work:
        for key, part in (("GRADLE_USER_HOME", "gradle-user-home"), ("KONAN_DATA_DIR", "konan"),
                          ("TMPDIR", "temp"), ("TEMP", "temp"), ("TMP", "temp")):
            directory = Path(work) / part
            physical(directory).mkdir(parents=True, exist_ok=True)
            env[key] = str(directory)
    return env


def safe_relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or ":" in value or any(x in ("", ".", "..") for x in path.parts):
        raise RuntimeError("Unsafe relative path: " + value)
    return Path(*path.parts)


def check_tools(directory, lock_path):
    directory = Path(directory).resolve()
    lock = load(lock_path)
    if lock.get("revision") != TOOL_COMMIT or lock.get("repository") != "https://github.com/qsxs/cpf-port-tooling":
        raise RuntimeError("Tooling lock identity differs")
    cmd = ["git", "-c", "core.longpaths=true", "-C", str(directory), "rev-parse"]
    try:
        root = subprocess.check_output(cmd + ["--show-toplevel"], env=environment(), text=True, stderr=subprocess.PIPE).strip()
        commit = subprocess.check_output(cmd + ["--verify", "HEAD^{commit}"], env=environment(), text=True, stderr=subprocess.PIPE).strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError("Tooling must be a Git checkout") from error
    if Path(root).resolve() != directory or commit != TOOL_COMMIT:
        raise RuntimeError("Tooling Git root or revision differs")
    rows = lock["files"]
    if len(rows) != 20 or len({r["path"] for r in rows}) != 20:
        raise RuntimeError("Tooling lock must list 20 distinct files")
    for item in rows:
        if not item["path"].startswith(TOOL_PREFIX):
            raise RuntimeError("Unexpected tool path")
        found = record(directory / safe_relative(item["path"]))
        if (found["size"], found["sha256"]) != (item["size"], item["sha256"]):
            raise RuntimeError("Tooling file differs: " + item["path"])
    return {"gitRoot": str(directory), "commit": commit, "lockedFiles": len(rows)}


def check_native(home, tooling):
    home = Path(home).resolve()
    lines = physical(home / "konan/konan.properties").read_text(encoding="utf-8").splitlines()
    properties = dict(line.split("=", 1) for line in lines if "=" in line)
    if properties.get("compilerVersion", "").strip() != "2.4.20-0.1.0-08":
        raise RuntimeError("Native compiler version differs")
    if sys.platform.startswith("linux"):
        bundle = load(Path(tooling) / TOOL_PREFIX / "bootstrap-linux.json")["nativeBundle"]
        receipt = load(home.parent / "bootstrap-receipt.json")
        archive = record(home.parent / (bundle["directory"] + ".tar.gz"))
        if (home.name != bundle["directory"] or Path(receipt["nativeHome"]).resolve() != home or
                (archive["size"], archive["sha256"]) != (bundle["bytes"], bundle["sha256"]) or
                (receipt["bytes"], receipt["sha256"]) != (bundle["bytes"], bundle["sha256"])):
            raise RuntimeError("Native bootstrap identity differs")
    elif os.name == "nt":
        compiler = record(home / "konan/lib/kotlin-native-compiler-embeddable.jar")
        if (compiler["size"], compiler["sha256"]) != (225009008, "f0db0d77740004ea5604d8647b8b555603d7deb5827339dc4b82b139d52641f1"):
            raise RuntimeError("Windows Native compiler differs")
    else:
        raise RuntimeError("Unsupported producer host")
