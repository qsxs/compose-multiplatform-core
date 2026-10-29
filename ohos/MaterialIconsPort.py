"""MaterialIcons 完整双模块原源 producer；静态计划不代表编译或运行成功。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
from PortSupport import load, record, write, physical, logical, environment, check_tools, check_native
GROUP = "io.github.qsxs.cpf.materialicons"
ORIGINAL_PORT = "a2c2a1ddfc81e876ee2fe1686681aa3b00b160ac"
UPSTREAM = "6a03ba934d30f31bf55c36d36e46aec9a7701477"
TOOL_COMMIT = "d0cff88fd1ea2e4f08bb4409f1c802cca0c7f285"
MODULES = ("material-icons-core", "material-icons-extended")
STAGES = (("Metadata", "metadata", "recordIconsMetadata"), ("NativeX64", "native-x64", "recordIconsX64"),
          ("NativeArm64", "native-arm64", "recordIconsArm64"))
COMPILE_ORDER = [(module, stage, evidence) for stage, evidence, _ in STAGES for module in MODULES]


def source_digest(rows):
    compact = [{key: row[key] for key in ("member", "size", "sha256")} for row in sorted(rows, key=lambda row: row["member"])]
    return hashlib.sha256(json.dumps(compact, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def windows_path_key(name):
    return "/".join(part.rstrip(" .").casefold() for part in PurePosixPath(name).parts)


def staged_paths(names):
    # Windows 会折叠 AddChart/Addchart；只给碰撞成员增加不同父目录，原 basename 和内容不变。
    groups = {}
    for name in names:
        groups.setdefault(windows_path_key(name), []).append(name)
    mapping = {name: name for name in names}
    collisions = []
    for key in sorted(groups):
        group = sorted(groups[key])
        if len(group) > 1:
            for index, name in enumerate(group, 1):
                relative = PurePosixPath(name)
                mapping[name] = (relative.parent / ("__case_" + str(index)) / relative.name).as_posix()
            collisions.append({"members": group, "stagedPaths": [mapping[name] for name in group]})
    if len(mapping) != len(names) or len({windows_path_key(name) for name in mapping.values()}) != len(names):
        raise RuntimeError("MaterialIcons staged paths are not Windows-unique")
    return mapping, collisions


def mapping_digest(mapping):
    rows = [{"member": member, "stagedPath": mapping[member]} for member in sorted(mapping)]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recipe_matches_commit(commit, recipe):
    command = ["git", "-c", "core.longpaths=true", "-C", str(ROOT)]
    listed = subprocess.check_output(command + ["ls-tree", "-r", "--name-only", commit, "--", "ohos/"],
                                     env=environment(), text=True).splitlines()
    expected = {"ohos/" + row["path"] for row in recipe}
    if set(listed) != expected:
        return False
    for row in recipe:
        data = subprocess.check_output(command + ["show", commit + ":ohos/" + row["path"]], env=environment())
        if (len(data), hashlib.sha256(data).hexdigest()) != (row["size"], row["sha256"]):
            return False
    return True


def plan(args):
    if (not re.fullmatch(r"[0-9a-f]{40}", args.source_sha) or
            not re.fullmatch(r"[1-9][0-9]*", args.run_id) or
            not re.fullmatch(r"[1-9][0-9]*", args.run_attempt)):
        raise RuntimeError("Full source SHA and positive run identifiers are required")
    head = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                   env=environment(), text=True).strip()
    if head != args.source_sha:
        raise RuntimeError("Source SHA must match fork HEAD")
    for path in (args.work, args.repository, args.native_home, args.tooling):
        if not path.is_absolute():
            raise RuntimeError("Work, repository, native home and tooling must be absolute paths")
    work, repository, native, tooling = (x.resolve() for x in (args.work, args.repository, args.native_home, args.tooling))
    for output in (work, repository):
        for other in (ROOT.resolve(), native, tooling, repository if output == work else work):
            if output == other or output.is_relative_to(other) or other.is_relative_to(output):
                raise RuntimeError("Work, staging, checkout, native home and tooling must be separate")
    config = load(HERE / "port-config.json")
    if (config["group"], config["upstreamForkCommit"], config["originalPortCommit"], config["toolingCommit"],
            config["gradle"], config["kotlin"], config["compose"]) != (
            GROUP, UPSTREAM, ORIGINAL_PORT, TOOL_COMMIT, "9.5.0", "2.4.20-0.1.0-08", "1.12.0-0.1.0-11"):
        raise RuntimeError("Pinned producer identity differs")
    wrapper = config["gradleWrapper"]
    if [record(HERE / item["path"], HERE) for item in wrapper["inputs"]] != wrapper["inputs"]:
        raise RuntimeError("Gradle wrapper bytes differ")
    properties = dict(line.split("=", 1) for line in (HERE / "gradle/wrapper/gradle-wrapper.properties")
                      .read_text(encoding="utf-8").splitlines() if "=" in line)
    if (properties.get("distributionUrl", "").replace("\\:", ":") != wrapper["distributionUrl"] or
            properties.get("distributionSha256Sum") != wrapper["distributionSha256"]):
        raise RuntimeError("Gradle distribution identity differs")
    inputs = load(HERE / "source-inputs.json")
    if record(HERE / "tooling-lock.json")["sha256"] != "886a9d79daae5c49dc9604cbaab9b709cf20d8dd7f607ada3a5610c3565243f0":
        raise RuntimeError("Pinned tooling lock bytes differ")
    origin = load(HERE / "original-port-inputs.json")
    if origin["originalPortCommit"] != ORIGINAL_PORT or origin["upstreamForkCommit"] != UPSTREAM:
        raise RuntimeError("Original port provenance differs")
    source_facts = {}
    for module in MODULES:
        model = inputs["modules"][module]
        for kind in ("sources", "pom", "gmm"):
            item = model[kind]
            if record(HERE / item["path"], HERE) != item:
                raise RuntimeError("Original Maven input differs: " + module + ":" + kind)
            source_path = "harmony-build/ports/material-icons/" + item["path"]
            rows = [row for row in origin["files"] if row["originalPath"] == source_path]
            if len(rows) != 1 or (rows[0]["size"], rows[0]["sha256"]) != (item["size"], item["sha256"]):
                raise RuntimeError("Original Git source provenance differs: " + source_path)
        with zipfile.ZipFile(physical(HERE / model["sources"]["path"])) as archive:
            entries = archive.infolist()
            seen = set()
            for item in entries:
                name = item.filename
                part = PurePosixPath(name)
                if (not name or part.is_absolute() or ".." in part.parts or "\\" in name or ":" in name or
                        "\x00" in name or name in seen or stat.S_ISLNK(item.external_attr >> 16)):
                    raise RuntimeError("Unsafe or duplicate archive member: " + name)
                seen.add(name)
            mapping, collisions = staged_paths([item.filename for item in entries if not item.is_dir()])
            rows = []
            for item in entries:
                if item.is_dir() or not item.filename.endswith(".kt"):
                    continue
                if not item.filename.startswith(model["compilePrefix"]):
                    raise RuntimeError("Kotlin source outside commonMain: " + item.filename)
                data = archive.read(item)
                rows.append({"member": item.filename, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            if len(rows) != model["kotlinSourceCount"] or source_digest(rows) != model["sourceSetSha256"]:
                raise RuntimeError("Complete source count or digest differs: " + module)
            if module == "material-icons-core" and collisions:
                raise RuntimeError("Unexpected core case collision")
            if module == "material-icons-extended":
                if len(collisions) != 5 or any({PurePosixPath(n).name for n in group["members"]} != {"AddChart.kt", "Addchart.kt"} for group in collisions):
                    raise RuntimeError("Expected five AddChart/Addchart case collisions")
            source_facts[module] = {"count": len(rows), "sourceSetSha256": source_digest(rows),
                                    "caseCollisionGroups": collisions, "mappingSha256": mapping_digest(mapping)}
    legal = record(HERE / "legal/LICENSE", HERE)
    if any(legal["sha256"] != item["licenseSha256"] for item in config["modules"].values()):
        raise RuntimeError("Apache 2.0 license differs")
    recipe = []
    for path in sorted(HERE.rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Recipe may not contain symlinks: " + str(path))
        if path.is_file() and "__pycache__" not in path.relative_to(HERE).parts:
            recipe.append(record(path, HERE))
    version = "1.7.3-cpf11-preview-" + args.source_sha[:12] + "-" + args.run_id + "-" + args.run_attempt
    identity = {"sourceCommit": args.source_sha, "upstreamForkCommit": UPSTREAM, "originalPortCommit": ORIGINAL_PORT,
                "expectedToolingCommit": TOOL_COMMIT, "group": GROUP, "version": version,
                "recipe": recipe, "sourceFacts": source_facts, "license": legal}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    committed = recipe_matches_commit(args.source_sha, recipe)
    return {**identity, "fingerprint": fingerprint, "recipeMatchesCommit": committed,
            "work": str(work), "repository": str(repository), "nativeHome": str(native), "tooling": str(tooling),
            "versions": {module: version for module in MODULES}}


def expected_provenance(value):
    recipe = {item["path"]: item for item in value["recipe"]}
    for name in ("source-inputs.json", "original-port-inputs.json", "legal/LICENSE"):
        if name not in recipe or record(HERE / name, HERE) != recipe[name]:
            raise RuntimeError("Provenance recipe input differs: " + name)
    return {"schemaVersion": 1, "fingerprint": value["fingerprint"],
            "sourceCommit": value["sourceCommit"], "originalPortCommit": ORIGINAL_PORT, "upstreamForkCommit": UPSTREAM,
            "toolingCommit": TOOL_COMMIT, "toolingFilesVerified": 20,
            "group": GROUP, "version": value["version"], "sources": value["sourceFacts"],
            "mavenInputs": load(HERE / "source-inputs.json"),
            "originalPortInputs": load(HERE / "original-port-inputs.json"),
            "legal": value["license"], "runtime": "NOT_RUN"}


def verify_provenance(value):
    expected = (json.dumps(expected_provenance(value), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path = Path(value["work"]) / "build-provenance.json"
    if physical(path).read_bytes() != expected:
        raise RuntimeError("Prepared build provenance differs")
    return expected


def prepare(value):
    work = physical(value["work"])
    prepared = work / "prepared.json"
    if work.exists() or Path(value["repository"]).exists():
        raise RuntimeError("Work and staging must both be new paths")
    tooling = check_tools(value["tooling"], HERE / "tooling-lock.json")
    work.mkdir(parents=True, exist_ok=False)
    config = load(HERE / "port-config.json")
    inputs = load(HERE / "source-inputs.json")
    members, staging = [], {}
    for module in MODULES:
        model = inputs["modules"][module]
        for kind in ("sources", "gmm", "pom"):
            if record(HERE / model[kind]["path"], HERE) != model[kind]:
                raise RuntimeError("Official MaterialIcons input differs: " + module + ":" + kind)
        module_members, seen = [], set()
        with zipfile.ZipFile(physical(HERE / model["sources"]["path"])) as archive:
            for member in archive.infolist():
                name = member.filename
                relative = PurePosixPath(name)
                if (not name or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name or
                        "\x00" in name or name in seen or stat.S_ISLNK(member.external_attr >> 16)):
                    raise RuntimeError("Unsafe or duplicate MaterialIcons archive member: " + name)
                seen.add(name)
            mapping, collisions = staged_paths([member.filename for member in archive.infolist() if not member.is_dir()])
            source_mapping = {name: staged for name, staged in mapping.items()
                              if name.startswith(model["compilePrefix"]) and name.endswith(model["compileSuffix"])}
            staging[module] = {"archiveMappingSha256": mapping_digest(mapping),
                               "stagedMappingSha256": mapping_digest(source_mapping), "caseCollisionGroups": collisions}
            for member in archive.infolist():
                name = member.filename
                staged_path = name if member.is_dir() else mapping[name]
                relative = PurePosixPath(staged_path)
                target = work / "sources" / module / Path(*relative.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                data = archive.read(member)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    output.write(data)
                compile_source = name.startswith(model["compilePrefix"]) and name.endswith(model["compileSuffix"])
                if name.endswith(".kt") and not compile_source:
                    raise RuntimeError("Kotlin source excluded from full MaterialIcons module: " + name)
                module_members.append({"module": module, "member": name, "stagedPath": staged_path,
                                       "compile": compile_source, **record(target)})
        sources = [row for row in module_members if row["compile"]]
        if (len(sources) != model["kotlinSourceCount"] or len(sources) != config["modules"][module]["sourceCount"] or
                source_digest(sources) != model["sourceSetSha256"]):
            raise RuntimeError("Complete MaterialIcons source inventory differs: " + module)
        members.extend(module_members)
    legal = record(HERE / "legal/LICENSE", HERE)
    if any(legal["sha256"] != model["licenseSha256"] for model in config["modules"].values()):
        raise RuntimeError("Official Apache2 license differs")
    write(work / "source-manifest.json", {"fingerprint": value["fingerprint"], "members": members,
          "modules": {module: {**{key: inputs["modules"][module][key] for key in ("sources", "kotlinSourceCount", "sourceSetSha256")},
                               **staging[module]}
                      for module in MODULES}, "legal": legal, "origins": record(HERE / "legal/origins.json", HERE)})
    write(work / "tooling-verification.json", {"fingerprint": value["fingerprint"], **tooling})
    write(work / "build-provenance.json", expected_provenance(value))
    write(prepared, value)
    return value


def verify_stage(value, module, evidence):
    model = load(HERE / "source-inputs.json")["modules"][module]
    manifest = load(Path(value["work"]) / "source-manifest.json")
    row = load(Path(value["work"]) / "evidence" / (module + "-" + evidence + ".json"))
    if (row["fingerprint"] != value["fingerprint"] or row["module"] != module or row["stage"] != evidence or
            row["sourceCount"] != model["kotlinSourceCount"] or row["sourceSetSha256"] != model["sourceSetSha256"] or
            row["stagedMappingSha256"] != manifest["modules"][module]["stagedMappingSha256"] or
            row["sourceManifest"] != record(Path(value["work"]) / "source-manifest.json")):
        raise RuntimeError("MaterialIcons compile source identity differs: " + module + ":" + evidence)
    native_targets = []
    for producer in row["producers"]:
        if not producer["outputs"] or not any(item["size"] > 0 for item in producer["outputs"]):
            raise RuntimeError("MaterialIcons producer has empty outputs")
        for item in producer["outputs"]:
            if record(item["path"]) != item:
                raise RuntimeError("MaterialIcons stage output bytes changed")
            path = physical(item["path"])
            text = None
            if path.suffix == ".klib" and zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    text = archive.read("default/manifest").decode()
            elif path.as_posix().endswith("/default/manifest"):
                text = path.read_text(encoding="utf-8")
            if text is not None:
                props = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
                native_targets.extend(props.get("native_targets", "").split())
    if evidence != "metadata":
        expected = "ohos_x64" if evidence == "native-x64" else "ohos_arm64"
        if not native_targets or set(native_targets) != {expected}:
            raise RuntimeError("MaterialIcons Native klib target differs: " + module)
    return row


def stage_key(stage, module):
    return stage + ("-" + module if module else "")


def stage_evidence_path(work, stage, module):
    if stage == "Tasks":
        return work / "task-discovery.json"
    if stage == "Resolve":
        return work / "evidence/resolve.json"
    for stage_name, evidence_name, _ in STAGES:
        if stage == stage_name and module in MODULES:
            return work / "evidence" / (module + "-" + evidence_name + ".json")
    if stage == "Publish" and module is None:
        return work / "publication.json"
    raise RuntimeError("Unexpected stage or module: " + stage)


def require_invocation_receipt(value, stage, module, attempt):
    if type(attempt) is not int or attempt < 1:
        raise RuntimeError("Invalid stage attempt: " + stage_key(stage, module))
    receipt = Path(value["work"]) / "invocations" / (stage_key(stage, module) + "-" + str(attempt) + ".json")
    invocation = load(receipt)
    if (invocation.get("stage") != stage or invocation.get("module") != module or
            invocation.get("fingerprint") != value["fingerprint"] or
            type(invocation.get("exitCode")) is not int or invocation["exitCode"] != 0):
        raise RuntimeError("Stage did not exit successfully: " + stage_key(stage, module))
    return receipt


def mark_stage_success(value, stage, module, attempt, receipt):
    work = Path(value["work"])
    if receipt != require_invocation_receipt(value, stage, module, attempt):
        raise RuntimeError("Stage invocation path differs: " + stage_key(stage, module))
    evidence = stage_evidence_path(work, stage, module)
    proof = {"stage": stage, "module": module, "attempt": attempt, "fingerprint": value["fingerprint"],
             "invocation": record(receipt), "evidence": record(evidence) if evidence else None}
    write(work / "invocations" / (stage_key(stage, module) + "-success.json"), proof)


def require_stage_success(value, stage, module=None):
    work = Path(value["work"])
    proof = load(work / "invocations" / (stage_key(stage, module) + "-success.json"))
    attempt = proof.get("attempt")
    if (proof.get("stage") != stage or proof.get("module") != module or
            proof.get("fingerprint") != value["fingerprint"] or
            type(attempt) is not int or attempt < 1):
        raise RuntimeError("Stage success identity differs: " + stage_key(stage, module))
    receipt = require_invocation_receipt(value, stage, module, attempt)
    if proof.get("invocation") != record(receipt):
        raise RuntimeError("Stage invocation receipt differs: " + stage_key(stage, module))
    evidence = stage_evidence_path(work, stage, module)
    if proof.get("evidence") != (record(evidence) if evidence else None):
        raise RuntimeError("Stage evidence differs: " + stage_key(stage, module))
    if evidence and load(evidence).get("fingerprint") != value["fingerprint"]:
        raise RuntimeError("Stage evidence identity differs: " + stage_key(stage, module))
    return proof


def wrapper_command():
    java_name = "java.exe" if os.name == "nt" else "java"
    java_home = os.environ.get("JAVA_HOME")
    java = str(Path(java_home) / "bin" / java_name) if java_home else java_name
    return [java, "-classpath", str(HERE / "gradle/wrapper/gradle-wrapper.jar"),
            "org.gradle.wrapper.GradleWrapperMain"]


def verify_publication(value, publish_attempt=None):
    require_stage_success(value, "Tasks")
    require_stage_success(value, "Resolve")
    for module, stage, _ in COMPILE_ORDER:
        require_stage_success(value, stage, module)
    if publish_attempt is None:
        require_stage_success(value, "Publish")
    else:
        require_invocation_receipt(value, "Publish", None, publish_attempt)
    provenance = verify_provenance(value)
    config = load(HERE / "port-config.json")
    pins = {**load(HERE / "dependency-pins.json"), **load(HERE / "metadata-pins.json")}
    stage_rows = [verify_stage(value, module, evidence) for module, _, evidence in COMPILE_ORDER]
    repo = physical(value["repository"]) / Path(*GROUP.split("."))
    rows = []
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    for module in MODULES:
        version = value["versions"][module]
        root_file = repo / module / version / (module + "-" + version + ".module")
        root = load(root_file)
        for suffix, target in (("", None), ("-ohosx64", "ohos_x64"), ("-ohosarm64", "ohos_arm64")):
            name = module + suffix
            directory = repo / name / version
            gmm_file = directory / (name + "-" + version + ".module")
            gmm = load(gmm_file)
            if any(gmm["component"].get(k) != v for k, v in {"group": GROUP, "module": module, "version": version}.items()):
                raise RuntimeError("MaterialIcons publication owner differs")
            if target:
                if (directory / gmm["component"]["url"]).resolve() != root_file.resolve():
                    raise RuntimeError("MaterialIcons Native leaf owner URL differs")
                links = [variant["available-at"] for variant in root["variants"]
                         if variant.get("attributes", {}).get("org.jetbrains.kotlin.native.target") == target and "available-at" in variant]
                if not links or any(link["group"] != GROUP or link["module"] != name or
                                    link["version"] != version or (root_file.parent / link["url"]).resolve() != gmm_file.resolve() for link in links):
                    raise RuntimeError("MaterialIcons root Native available-at differs")
            api = []
            for variant in gmm["variants"]:
                attrs = variant.get("attributes", {})
                if ((not target and attrs.get("org.gradle.usage") == "kotlin-metadata" and attrs.get("org.jetbrains.kotlin.platform.type") == "common") or
                        (target and attrs.get("org.gradle.usage") == "kotlin-api" and attrs.get("org.jetbrains.kotlin.native.target") == target)):
                    api.append(variant)
                for dep in variant.get("dependencies", []):
                    ga = dep["group"] + ":" + dep["module"]
                    if dep["module"].startswith("material-icons-"):
                        if (module != "material-icons-extended" or dep["group"] != GROUP or
                                dep["module"] not in {"material-icons-core", "material-icons-core" + suffix} or
                                dep.get("version", {}).get("requires") != value["versions"]["material-icons-core"]):
                            raise RuntimeError("MaterialIcons publication contains wrong core/private dependency: " + ga)
                    elif pins.get(ga) != dep.get("version", {}).get("requires"):
                        raise RuntimeError("MaterialIcons publication dependency escaped frozen pins: " + ga)
                for artifact in variant.get("files", []):
                    item = record(directory / artifact["url"])
                    if item["sha256"] != artifact["sha256"] or item["size"] != artifact["size"]:
                        raise RuntimeError("MaterialIcons published artifact identity differs")
            api_artifact = directory / (name + "-" + version + (".klib" if target else ".jar"))
            if not api or not all(any((directory / item["url"]).resolve() == api_artifact.resolve()
                    for item in variant.get("files", [])) for variant in api):
                raise RuntimeError("MaterialIcons common metadata or Native API artifact is absent")
            ui_edges = {"org.jetbrains.compose.ui:ui", "org.jetbrains.compose.ui:ui-graphics"}
            if module == "material-icons-core":
                ui_edges.add("org.jetbrains.compose.ui:ui-unit")
            for variant in api:
                edges = {dep["group"] + ":" + dep["module"] for dep in variant.get("dependencies", [])}
                if not ui_edges.issubset(edges):
                    raise RuntimeError("MaterialIcons UI API dependencies are missing")
            if module == "material-icons-extended" and not all(any(
                    dep["group"] == GROUP and dep["module"] in {"material-icons-core", "material-icons-core" + suffix} and
                    dep.get("version", {}).get("requires") == value["versions"]["material-icons-core"]
                    for dep in variant.get("dependencies", [])) for variant in api):
                raise RuntimeError("MaterialIcons extended API must expose private core root/leaf")
            pom = directory / (name + "-" + version + ".pom")
            tree = ET.fromstring(pom.read_bytes())
            if any(tree.findtext("m:" + key, namespaces=ns) != expected for key, expected in
                   (("groupId", GROUP), ("artifactId", name), ("version", version))):
                raise RuntimeError("MaterialIcons POM identity differs")
            if (tree.findtext("m:licenses/m:license/m:name", namespaces=ns) != config["modules"][module]["license"] or
                    tree.findtext("m:licenses/m:license/m:url", namespaces=ns) != config["modules"][module]["licenseUrl"]):
                raise RuntimeError("MaterialIcons POM license differs")
            dependencies = tree.findall("m:dependencies/m:dependency", ns)
            for dep in dependencies:
                group, artifact, dep_version = [dep.findtext("m:" + key, namespaces=ns) for key in ("groupId", "artifactId", "version")]
                if artifact.startswith("material-icons-"):
                    if (group != GROUP or artifact != "material-icons-core" + suffix or
                            dep_version != value["versions"]["material-icons-core"]):
                        raise RuntimeError("MaterialIcons POM leaked upstream icons edge")
                elif pins.get(group + ":" + artifact) != dep_version:
                    raise RuntimeError("MaterialIcons POM escaped frozen dependency pins")
            if module == "material-icons-extended" and not any(
                    dep.findtext("m:artifactId", namespaces=ns) == "material-icons-core" + suffix and
                    dep.findtext("m:scope", namespaces=ns) == ("compile" if target else "runtime") for dep in dependencies):
                raise RuntimeError("MaterialIcons POM lost extended API scope")
            license_file = directory / (name + "-" + version + "-license.txt")
            if record(license_file)["sha256"] != config["modules"][module]["licenseSha256"]:
                raise RuntimeError("MaterialIcons publication license differs")
            if (directory / (name + "-" + version + "-upstream-origins.json")).read_bytes() != (HERE / "legal/origins.json").read_bytes():
                raise RuntimeError("MaterialIcons publication provenance differs")
            if target:
                verify_native_klib(directory / (name + "-" + version + ".klib"), target)
            if (directory / (name + "-" + version + "-build-provenance.json")).read_bytes() != provenance:
                raise RuntimeError("MaterialIcons build provenance differs")
            source_file = directory / (name + "-" + version + "-sources.jar")
            source_variants = [variant for variant in gmm["variants"]
                if variant.get("attributes", {}).get("org.gradle.category") == "documentation"
                and variant.get("attributes", {}).get("org.gradle.docstype") == "sources"
                and variant.get("attributes", {}).get("org.gradle.usage") == "kotlin-runtime"
                and variant.get("attributes", {}).get("org.jetbrains.kotlin.platform.type") == ("native" if target else "common")
                and variant.get("attributes", {}).get("org.jetbrains.kotlin.native.target") == target]
            if not source_variants or not all(any((directory / item["url"]).resolve() == source_file.resolve()
                    for item in variant.get("files", [])) for variant in source_variants):
                raise RuntimeError("MaterialIcons source variant does not reference its source JAR")
            verify_sources_jar(source_file, module, value)
            if not suffix:
                model = load(HERE / "source-inputs.json")["modules"][module]
                for kind, classifier in (("sources", "upstream-sources.jar"), ("pom", "upstream-pom.xml"), ("gmm", "upstream-module.json")):
                    if record(directory / (name + "-" + version + "-" + classifier))["sha256"] != model[kind]["sha256"]:
                        raise RuntimeError("MaterialIcons publication original upstream archive/metadata differs")
            rows.extend(record(path) for path in sorted(directory.iterdir()) if path.is_file())
    result = {"status": "PUBLISHED_COORDINATES_AND_BYTES_VERIFIED_RUNTIME_NOT_RUN", **value, "files": rows,
              "compilations": [{key: row[key] for key in ("module", "stage", "sourceCount", "sourceSetSha256", "stagedMappingSha256", "sourceManifest")}
                               for row in stage_rows], "runtime": "NOT_RUN"}
    verify_provenance(value)
    write(Path(value["work"]) / "publication.json", result)
    return result


def discovered(value):
    row = load(Path(value["work"]) / "task-discovery.json")
    if row["fingerprint"] != value["fingerprint"] or row["stdout"] != record(row["stdout"]["path"]):
        raise RuntimeError("MaterialIcons actual task discovery identity differs")
    return row


def verify_native_klib(path, target):
    with zipfile.ZipFile(physical(path)) as archive:
        manifests = [name for name in archive.namelist() if name == "manifest" or name.endswith("/manifest")]
        if len(manifests) != 1:
            raise RuntimeError("Published KLIB manifest count differs")
        props = dict(line.split("=", 1) for line in archive.read(manifests[0]).decode().splitlines() if "=" in line)
        if props.get("native_targets", "").split() != [target] or not props.get("unique_name"):
            raise RuntimeError("Published KLIB target or identity differs")
        for prefix in ("default/ir/", "default/linkdata/"):
            entries = [item for item in archive.infolist() if item.filename.startswith(prefix) and not item.is_dir() and item.file_size > 0]
            if not entries or not archive.read(entries[0]):
                raise RuntimeError("Published KLIB payload is empty: " + prefix)


def verify_sources_jar(path, module, value):
    manifest = load(Path(value["work"]) / "source-manifest.json")
    expected = {row["stagedPath"]: row for row in manifest["members"] if row["module"] == module and row["compile"]}
    with zipfile.ZipFile(physical(path)) as archive:
        actual = [entry for entry in archive.infolist() if not entry.is_dir() and entry.filename.endswith(".kt")]
        if len(actual) != len(expected) or len({entry.filename for entry in actual}) != len(actual):
            raise RuntimeError("Published source JAR count or uniqueness differs: " + module)
        license_name = "META-INF/licenses/material-icons/LICENSE"
        license_entries = [entry for entry in archive.infolist() if entry.filename == license_name and not entry.is_dir()]
        if len(license_entries) != 1 or archive.read(license_entries[0]) != (HERE / "legal/LICENSE").read_bytes():
            raise RuntimeError("Published source JAR license differs: " + module)
        for entry in actual:
            member = entry.filename
            if member not in expected:
                member = "commonMain/" + member
            if member not in expected:
                raise RuntimeError("Unexpected published source member: " + entry.filename)
            data = archive.read(entry)
            row = expected.pop(member)
            if len(data) != row["size"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise RuntimeError("Published Kotlin source bytes differ: " + entry.filename)
    if expected:
        raise RuntimeError("Published sources omit Kotlin members")


def verify_prepared(value):
    work = Path(value["work"])
    if load(work / "prepared.json") != value:
        raise RuntimeError("Prepared identity differs")
    tools = check_tools(value["tooling"], HERE / "tooling-lock.json")
    if load(work / "tooling-verification.json") != {"fingerprint": value["fingerprint"], **tools}:
        raise RuntimeError("Prepared tooling proof differs")
    verify_provenance(value)
    manifest = load(work / "source-manifest.json")
    if manifest["fingerprint"] != value["fingerprint"]:
        raise RuntimeError("Prepared manifest fingerprint differs")
    expected = set()
    for row in manifest["members"]:
        target = Path(row["path"])
        source_root = (work / "sources" / row["module"]).resolve()
        if target.resolve() != (source_root / Path(*PurePosixPath(row["stagedPath"]).parts)).resolve():
            raise RuntimeError("Prepared source path differs")
        if record(target) != {key: row[key] for key in ("path", "size", "sha256")}:
            raise RuntimeError("Prepared source bytes differ: " + row["member"])
        if row["compile"]:
            expected.add(target.resolve())
    actual = {logical(path).resolve() for path in physical(work / "sources").rglob("*.kt") if path.is_file()}
    if actual != expected:
        raise RuntimeError("Prepared source closure differs")
    for module in MODULES:
        rows = [row for row in manifest["members"] if row["module"] == module and row["compile"]]
        facts = value["sourceFacts"][module]
        if len(rows) != facts["count"] or source_digest(rows) != facts["sourceSetSha256"]:
            raise RuntimeError("Prepared source inventory differs: " + module)


def run_gradle(value, stage, module, attempt, offline):
    work = Path(value["work"])
    tasks = {"Tasks": ["tasks", "--all"], "Resolve": ["resolveIcons"], "Publish": ["publishIcons"]}
    if stage in {item[0] for item in STAGES}:
        evidence_name = next(item[1] for item in STAGES if item[0] == stage)
        task_name = next(item[2] for item in STAGES if item[0] == stage)
        tasks[stage] = [":" + module + ":" + task_name]
        position = COMPILE_ORDER.index((module, stage, evidence_name))
        for previous_module, previous_stage, previous_evidence in COMPILE_ORDER[:position]:
            require_stage_success(value, previous_stage, previous_module)
            verify_stage(value, previous_module, previous_evidence)
        if load(work / "evidence/resolve.json")["fingerprint"] != value["fingerprint"]:
            raise RuntimeError("Resolve evidence differs")
        if (work / "evidence" / (module + "-" + evidence_name + ".json")).exists():
            raise RuntimeError("Stage evidence already exists; use a fresh work directory")
    if stage != "Tasks":
        task_proof = require_stage_success(value, "Tasks")
        if discovered(value)["invocation"] != task_proof["invocation"]:
            raise RuntimeError("Task discovery receipt differs")
    if stage in {item[0] for item in STAGES} or stage == "Publish":
        require_stage_success(value, "Resolve")
    if stage == "Resolve" and (work / "evidence/resolve.json").exists():
        raise RuntimeError("Resolve evidence already exists")
    if stage == "Tasks" and (work / "task-discovery.json").exists():
        raise RuntimeError("Task discovery already exists")
    if stage == "Publish":
        for source_module, source_stage, evidence in COMPILE_ORDER:
            require_stage_success(value, source_stage, source_module)
            verify_stage(value, source_module, evidence)
        if Path(value["repository"]).exists():
            raise RuntimeError("Staging already exists; refusing overwrite")
    argv = wrapper_command() + ["-p", str(HERE), "--project-cache-dir", str(work / "project-cache"),
            "-PportWork=" + str(work), "-PportRepository=" + value["repository"],
            "-PportFingerprint=" + value["fingerprint"], "-PportVersion=" + value["version"],
            "-Pkotlin.project.persistent.dir=" + str(work / "kotlin-cache"),
            "-Pkotlin.native.home=" + value["nativeHome"], "--console=plain", *tasks[stage]]
    if offline:
        argv.append("--offline")
    name = stage + ("-" + module if module else "") + "-" + str(attempt)
    receipt = work / "invocations" / (name + ".json")
    stdout = receipt.with_suffix(".stdout.log")
    stderr = receipt.with_suffix(".stderr.log")
    if any(path.exists() for path in (receipt, stdout, stderr)):
        raise RuntimeError("Existing invocation or logs; select another attempt")
    physical(receipt.parent).mkdir(parents=True, exist_ok=True)
    claim = physical(receipt.parent / (stage + ("-" + module if module else "") + ".claim"))
    try:
        with claim.open("xb") as lock:
            lock.write((value["fingerprint"] + "\n").encode())
    except FileExistsError as error:
        raise RuntimeError("Stage was already claimed; use a fresh work and run attempt") from error
    row = {"stage": stage, "module": module, "fingerprint": value["fingerprint"], "argv": argv,
           "started": time.time(), "exitCode": None}
    try:
        with physical(stdout).open("xb") as out, physical(stderr).open("xb") as err:
            result = subprocess.run(argv, cwd=ROOT, env=environment(work), stdout=out, stderr=err)
            row["exitCode"] = result.returncode
    finally:
        row["finished"] = time.time()
        write(receipt, row)
    if row["exitCode"] != 0:
        raise RuntimeError("Gradle failed; retained invocation and logs: " + str(receipt))
    if stage == "Tasks":
        text = physical(stdout).read_text(encoding="utf-8-sig", errors="replace")
        names = set(re.findall(r"^\s*([\w:-]+)(?:\s+-|\s*$)", text, flags=re.MULTILINE))
        required = [m + ":" + task for m in MODULES for task in (
            "compileCommonMainKotlinMetadata", "allMetadataJar", "compileKotlinOhosX64", "compileKotlinOhosArm64",
            "recordIconsMetadata", "recordIconsX64", "recordIconsArm64", "publishAllPublicationsToPortRepository")]
        if not set(required).issubset({name.lstrip(":") for name in names}):
            raise RuntimeError("Expected tasks missing; inspect retained log")
        write(work / "task-discovery.json", {"fingerprint": value["fingerprint"], "requiredTasks": required,
              "stdout": record(stdout), "invocation": record(receipt)})
    elif stage == "Resolve":
        if load(work / "evidence/resolve.json").get("fingerprint") != value["fingerprint"]:
            raise RuntimeError("Resolve evidence identity differs")
    elif stage in {item[0] for item in STAGES}:
        verified = verify_stage(value, module, evidence_name)
        write(work / "invocations" / (name + "-evidence.json"), verified)
    if stage != "Publish":
        mark_stage_success(value, stage, module, attempt, receipt)
    return receipt


def finish_publication(value, attempt, receipt):
    result = verify_publication(value, publish_attempt=attempt)
    mark_stage_success(value, "Publish", None, attempt, receipt)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("Plan", "Prepare", "Tasks", "Resolve", "Metadata", "NativeX64", "NativeArm64", "Publish", "Verify"))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--native-home", type=Path, required=True)
    parser.add_argument("--tooling", type=Path, required=True)
    parser.add_argument("--module", choices=("All", "Core", "Extended"), default="All")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    compile_stage = args.stage in {item[0] for item in STAGES}
    if (not compile_stage and args.module != "All") or args.attempt < 1:
        parser.error("--module applies only to compile stages; --attempt must be positive")
    value = plan(args)
    if args.stage == "Plan":
        print(json.dumps(value, indent=2)); return
    if not value["recipeMatchesCommit"]:
        raise RuntimeError("Recipe must match the full fork commit before any write")
    if args.stage == "Prepare":
        prepare(value)
    else:
        verify_prepared(value)
        check_native(value["nativeHome"], value["tooling"])
        if args.stage == "Verify":
            result = verify_publication(value)
            print(json.dumps({"stage": args.stage, "fingerprint": value["fingerprint"], "publication": result["status"], "runtime": "NOT_RUN"})); return
        selected = MODULES if args.module == "All" else (MODULES[0 if args.module == "Core" else 1],)
        for module in selected if compile_stage else (None,):
            receipt = run_gradle(value, args.stage, module, args.attempt, args.offline)
        if args.stage == "Publish":
            finish_publication(value, args.attempt, receipt)
    print(json.dumps({"stage": args.stage, "work": value["work"], "fingerprint": value["fingerprint"], "runtime": "NOT_RUN"}))


if __name__ == "__main__":
    main()
