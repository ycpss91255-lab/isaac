"""Track the stable official Isaac Sim image and its packaged test inventory."""

import argparse
import fnmatch
import hashlib
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import zlib
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


IMAGE = "nvcr.io/nvidia/isaac-sim"
REGISTRY = "https://nvcr.io/v2/nvidia/isaac-sim/"
AUTH = "https://nvcr.io/proxy_auth?scope=repository:nvidia/isaac-sim:pull"
VERSION = r"[0-9]{1,3}(?:\.[0-9]+){2,3}"
PIN = re.compile(rf'^(ARG BASE_IMAGE="{re.escape(IMAGE)}:)({VERSION})(")$', re.M)
ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))
TEST_DIR = "isaac-sim/tests/"
CONFIG = TEST_DIR + "test_config.json"
RUNNER = "isaac-sim/run_tests.py"


def parse_stable_tags(payload):
    return [tag for tag in payload["tags"] if re.fullmatch(VERSION, tag)]


def version_key(version):
    if not re.fullmatch(VERSION, version):
        raise ValueError("Expected a stable Isaac Sim version")
    return tuple(map(int, version.split(".")))


def latest_stable(tags):
    return max(tags, key=version_key)


def should_bump(current, latest):
    return version_key(latest) > version_key(current)


def read_base_version(path):
    [pin] = PIN.finditer(path.read_text())
    return pin[2]


def update_base_version(path, version):
    version_key(version)
    content, count = PIN.subn(lambda m: m[1] + version + m[3], path.read_text())
    if count != 1:
        raise ValueError("Expected one Isaac Sim BASE_IMAGE pin")
    path.write_text(content)


def issue_title_for(version):
    return f"追蹤 Isaac Sim {version} 官方測試清單"


def should_open(version, open_prs, open_issues):
    branch = f"bot/isaac-sim-{version}"
    issue_title = issue_title_for(version)
    return not (any(pr["headRefName"] == branch for pr in open_prs)
                or any(issue["title"] == issue_title for issue in open_issues))


def parse_test_config(config, scripts):
    """Use run_tests.py's first matching suite and first matching bucket."""
    suites = json.loads(config)["suites"]

    def group(suite, bucket):
        if ":" in suite or ":" in bucket:
            raise ValueError("Unsupported suite or bucket identifier")
        return suite if bucket == "default" else f"{suite}:{bucket}"

    inventory = {}
    for suite in suites:
        buckets = [b["name"] for b in suite.get("buckets", [])]
        for bucket in [*buckets, suite.get("default_bucket", "other")]:
            inventory[group(suite["name"], bucket)] = set()

    for script in scripts:
        def matches(patterns):
            return any(fnmatch.fnmatchcase(script, pattern) for pattern in patterns)

        for suite in suites:
            if suite["include"] and not matches(suite["include"]):
                continue
            if matches(suite.get("exclude", [])):
                continue
            bucket = next((b["name"] for b in suite.get("buckets", [])
                           if matches(b["include"])), suite.get("default_bucket", "other"))
            inventory[group(suite["name"], bucket)].add(script)
            break
        else:
            inventory.setdefault("未分類", set()).add(script)
    return inventory


def diff_inventory(old, new):
    def additions(before, after):
        return {key: sorted(files - before.get(key, set())) for key, files in after.items()
                if key not in before or files - before[key]}

    added = additions(old, new)
    removed = additions(new, old)
    renamed = {}
    old_names = old.keys() - new.keys()
    new_names = new.keys() - old.keys()
    for name in old_names:
        contents = old[name]
        matches = [key for key in new_names if new[key] == contents]
        if contents and len(matches) == 1 and sum(old[k] == contents for k in old_names) == 1:
            renamed[name] = matches[0]
            del removed[name], added[matches[0]]
    return {"added": added, "removed": removed, "renamed": renamed}


def public_name(value, *, group=False):
    # Only upstream identifiers go into Markdown. Never interpolate diagnostics,
    # environment values, paths, arbitrary Markdown or authentication material.
    if value == "未分類":
        return value
    parts = value.split(":", 1) if group else [value]
    if not all(re.fullmatch(r"[a-zA-Z0-9_.-]{1,200}", part) for part in parts):
        return "（名稱已隱藏）"
    sensitive = (socket.gethostname(), os.getenv("GH_TOKEN"), os.getenv("GITHUB_TOKEN"),
                 os.getenv("NGC_TOKEN"), os.getenv("RUNNER_NAME"))
    if (any(key and key in value for key in sensitive)
            or re.search(r"gh[pousr]_|github_pat_|eyJ[\w-]+\.[\w-]+\.", value)):
        return "（名稱已隱藏）"
    return f"`{value}`"


def render_pr_body(current, latest, diff):
    version_key(current)
    version_key(latest)
    lines = [f"更新官方 Isaac Sim 映像，從 `{current}` 升至 `{latest}`。", "", "## 官方測試清單", ""]
    if diff is None:
        lines.append("清單差異無法取得。")
    elif not any(diff.values()):
        lines.append("測試清單沒有變更。")
    else:
        for kind, label in (("added", "新增"), ("removed", "移除")):
            for suite, files in sorted(diff[kind].items()):
                names = "、".join(map(public_name, files))
                lines.append(f"- {label} {public_name(suite, group=True)}" + (f"：{names}" if names else ""))
        for old, new in sorted(diff["renamed"].items()):
            lines.append(f"- 更名 {public_name(old, group=True)} → {public_name(new, group=True)}")
    return "\n".join(lines) + "\n"


def registry_get(path, token):
    request = Request(REGISTRY + path, headers={"Accept": ACCEPT})
    # Blob redirects point at signed storage URLs. Keep the bearer at nvcr.io.
    request.add_unredirected_header("Authorization", "Bearer " + token)
    return urlopen(request, timeout=45)


def stable_release(token):
    path = "tags/list"
    tags = []
    while path:
        with registry_get(path, token) as response:
            tags.extend(parse_stable_tags(json.load(response)))
            link = re.search(r'<([^>]+)>;\s*rel="next"', response.headers.get("Link", ""))
        if not link:
            break
        url = urljoin(REGISTRY + path, link[1])
        if not url.startswith(REGISTRY + "tags/list?"):
            raise ValueError("Invalid tag listing continuation")
        path = url[len(REGISTRY):]
    return latest_stable(tags)


def descriptor_digest(descriptor):
    digest = descriptor["digest"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Invalid registry digest")
    return digest


def image_layers(version, token):
    with registry_get("manifests/" + version, token) as response:
        manifest = json.load(response)
    if "manifests" in manifest:
        platform = next(d for d in manifest["manifests"]
                        if d.get("platform", {}).get("os") == "linux"
                        and d["platform"].get("architecture") == "amd64")
        with registry_get("manifests/" + descriptor_digest(platform), token) as response:
            manifest = json.load(response)
    layers = manifest["layers"]
    with registry_get("blobs/" + descriptor_digest(manifest["config"]), token) as response:
        history = [h for h in json.load(response).get("history", []) if not h.get("empty_layer")]
    if len(history) != len(layers):
        history = [{}] * len(layers)
    return [(descriptor_digest(layer), step.get("created_by", "")) for layer, step in zip(layers, history)]


def read_layer(blob):
    files = {}
    hidden = set()
    created_root = False
    with tarfile.open(fileobj=blob, mode="r|*", bufsize=256 * 1024) as archive:
        for entry in archive:
            path = entry.name.removeprefix("./").lstrip("/")
            directory, _, name = path.rpartition("/")
            if path == "isaac-sim" and entry.isdir():
                created_root = True
            if name.startswith(".wh.") and directory in ("", "isaac-sim", TEST_DIR[:-1]):
                prefix = directory + "/" if directory else ""
                hidden.add(prefix if name == ".wh..wh..opq" else prefix + name[4:])
            elif path in (CONFIG, RUNNER):
                if not entry.isfile() or entry.size > 2 * 1024 * 1024:
                    raise ValueError("Unsupported test metadata")
                files[path] = archive.extractfile(entry).read()
            elif directory + "/" == TEST_DIR and fnmatch.fnmatchcase(name, "tests-*.sh"):
                if entry.isfile() or entry.islnk() or entry.issym():
                    files[path] = None
    return files, hidden, created_root


def image_inventory(version, token, layer_cache):
    visible = {}
    hidden = set()
    for digest, step in reversed(image_layers(version, token)):
        if digest not in layer_cache:
            with registry_get("blobs/" + digest, token) as blob:
                layer_cache[digest] = read_layer(blob)
        files, whiteouts, created_root = layer_cache[digest]
        for path, data in files.items():
            if not any(not w or path == w or path.startswith(w.rstrip("/") + "/") for w in hidden):
                visible.setdefault(path, data)
        hidden.update(whiteouts)
        # A non-empty WORKDIR layer that actually creates /isaac-sim marks
        # the start of the installation. An opaque/deleted tree also masks
        # older entries. An ordinary patch with three matching files does not.
        if created_root and re.fullmatch(r"(?:/bin/sh -c #\(nop\) +)?WORKDIR /isaac-sim/?", step):
            break
        if hidden & {"", "isaac-sim", "isaac-sim/"}:
            break
        if hidden & {TEST_DIR, TEST_DIR[:-1]} and RUNNER in visible:
            break
    scripts = [p[len(TEST_DIR):] for p in visible if p.endswith(".sh")]
    if not scripts:
        raise ValueError("Missing test scripts")
    return parse_test_config(visible[CONFIG], scripts), hashlib.sha256(visible[RUNNER]).digest()


def inventory_diff(current, latest, token):
    def deadline(*_):
        raise TimeoutError("Inventory deadline reached")

    previous = signal.signal(signal.SIGALRM, deadline)
    signal.alarm(30 * 60)
    try:
        layer_cache = {}
        old, old_runner = image_inventory(current, token, layer_cache)
        new, new_runner = image_inventory(latest, token, layer_cache)
        return diff_inventory(old, new), old_runner != new_runner
    except (OSError, EOFError, ValueError, TypeError, LookupError, StopIteration,
            AttributeError, tarfile.TarError, zlib.error, http.client.HTTPException):
        return None, False
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def open_items(endpoint):
    # The issues endpoint includes PRs. Both endpoints paginate to exhaustion.
    pages = command("gh", "api", "--paginate", "--slurp",
                    f"repos/{{owner}}/{{repo}}/{endpoint}?state=open&per_page=100")
    return [item for page in json.loads(pages) for item in page
            if endpoint != "issues" or "pull_request" not in item]


def planned_pr_body(pin, current, latest, diff, runner_changed):
    body = render_pr_body(current, latest, diff)
    if current != pin:
        body = body.replace("## 官方測試清單", f"## 官方測試清單（比較 `{current}` 與 `{latest}`）")
    if runner_changed:
        body += "\n官方測試執行器 `run_tests.py` 有變更，請確認分組規則。\n"
    return (body + "\n## 人工確認\n\n"
            "本次自動更新僅修改 Dockerfile 的 `ARG BASE_IMAGE`。\n\n"
            "- [ ] 請核對 `README.md` 與 Dockerfile 註解，將其中寫死的舊版號同步更新為新版號。\n")


def run(override, dry_run=False):
    dockerfile = Path("Dockerfile")
    pin = read_base_version(dockerfile)
    current = override or pin
    version_key(current)
    with urlopen(AUTH, timeout=45) as response:
        token = json.load(response)["token"]
    latest = stable_release(token)
    if not should_bump(current, latest) or (
        not (dry_run and override) and not should_bump(pin, latest)
    ):
        print("Dockerfile 無可套用的版本更新。")
        return

    branch = "bot/isaac-sim-" + latest
    if command("git", "ls-remote", "--heads", "origin", "refs/heads/" + branch):
        return
    prs = [dict(headRefName=p["head"]["ref"]) for p in open_items("pulls")]
    if not should_open(latest, prs, open_items("issues")):
        return

    diff, runner_changed = inventory_diff(current, latest, token)
    body = planned_pr_body(pin, current, latest, diff, runner_changed)
    title = f"更新 Isaac Sim 至 {latest}"
    issue_title = issue_title_for(latest) if diff and any(diff.values()) else None
    if dry_run:
        print(title)
        print(body, end="")
        if issue_title:
            print(issue_title)
        return

    with tempfile.TemporaryDirectory() as tmp:
        body_file = Path(tmp) / "body.md"
        body_file.write_text(body)
        command("git", "switch", "-c", branch)
        update_base_version(dockerfile, latest)
        command("git", "-c", "user.name=github-actions[bot]",
                "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "-m", title, "--", "Dockerfile")
        ref = "refs/heads/" + branch
        commit = command("git", "rev-parse", "HEAD").strip()
        # Require the ref to be absent, including if someone created it during the scan.
        command("git", "push", f"--force-with-lease={ref}:", "origin", "HEAD:" + ref)
        try:
            command("gh", "pr", "create", "--base", os.environ["BASE_BRANCH"], "--head", branch,
                    "--title", title, "--body-file", str(body_file))
        except subprocess.CalledProcessError:
            # Creation can succeed even if the response is lost. Only remove
            # our orphaned commit after confirming there is no matching PR.
            if not any(pr["head"]["ref"] == branch for pr in open_items("pulls")):
                command("git", "push", f"--force-with-lease={ref}:{commit}", "origin", ":" + ref)
                raise
        try:
            command("gh", "workflow", "run", "main.yaml", "--ref", branch, "-f", "groups=all")
        except subprocess.CalledProcessError:
            print("警告：CI 啟動失敗。請儲存庫擁有者關閉 PR 後重新開啟，以觸發 CI。", file=sys.stderr)
        if issue_title:
            body_file.write_text(body + "\n請依差異核對 #435 的 Isaac Sim 測試項目。\n")
            args = ("gh", "issue", "create", "--title", issue_title, "--body-file", str(body_file))
            try:
                command(*args)
            except subprocess.CalledProcessError:
                if not any(i["title"] == issue_title for i in open_items("issues")):
                    command(*args)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True).add_parser("run")
    sub.add_argument("--current-version", default="")
    sub.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        run(args.current_version, dry_run=args.dry_run)
    except subprocess.CalledProcessError as error:
        sys.exit(f"{error.cmd[0]} {error.cmd[1]} 失敗（結束碼 {error.returncode}）。")
    except (OSError, ValueError, LookupError, http.client.HTTPException):
        sys.exit("讀取官方 Isaac Sim 版本或儲存庫設定失敗。")


if __name__ == "__main__":
    main()
