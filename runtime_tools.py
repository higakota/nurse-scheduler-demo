"""検証済みの版に切り替える。元フォルダと勤務データは上書きしない。"""
from contextlib import closing
import argparse, io, json, os, sqlite3, subprocess, sys, zipfile
from datetime import datetime
from pathlib import Path
from launcher import ROOT, operation_lock, atomic_json, launch, show, state, stop_owned

def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.STDOUT)

def extract_release(root, revision):
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("不正な版番号です。")
    destination = root / ".runtime/versions" / revision
    if (destination / ".ready").exists():
        return destination
    archive = zipfile.ZipFile(io.BytesIO(git(root, "archive", "--format=zip", revision)))
    for entry in archive.infolist():
        target = (destination / entry.filename).resolve()
        if not target.is_relative_to(destination.resolve()) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("安全に展開できないファイルがあります。")
    destination.mkdir(parents=True, exist_ok=True)
    archive.extractall(destination)
    (destination / ".ready").write_text(revision)
    return destination

def safety_backup(root):
    source = root / "instance/staff.sqlite3"
    if not source.exists():
        return
    folder = source.parent / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / ("before_update_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".sqlite3")
    with closing(sqlite3.connect(str(source))) as db, closing(sqlite3.connect(str(target))) as backup:
        db.backup(backup)

def activate(root, next_state):
    old = state(root)
    safety_backup(root)
    stop_owned(root)
    atomic_json(root / ".runtime/versions.json", next_state)
    try:
        launch(root, open_browser=False)
    except Exception:
        stop_owned(root)
        atomic_json(root / ".runtime/versions.json", old)
        launch(root, open_browser=False)
        raise RuntimeError("起動に失敗したため、更新前の版へ戻しました。勤務データは保持しています。")

def update(root):
    if git(root, "status", "--porcelain").strip():
        raise RuntimeError("開発中の変更が残っています。保存・コミットしてから更新してください。")
    git(root, "fetch", "origin", "main")
    revision = git(root, "rev-parse", "origin/main").decode().strip()
    old = state(root)["current"]
    if revision == old["version"]:
        return "すでに最新です。"
    candidate = extract_release(root, revision)
    old_code = Path(old["code"])
    if (candidate / "requirements.txt").read_bytes() != (old_code / "requirements.txt").read_bytes():
        raise RuntimeError("必要なライブラリが変更されています。開発者による環境の更新が必要です。現在の版は変更していません。")
    env = dict(os.environ)
    env.pop("NURSE_SCHEDULER_DATABASE", None)
    log = root / ".runtime/update-test.log"
    with log.open("wb") as output:
        result = subprocess.run([old["python"], "-B", "-m", "unittest", "discover", "-s", "tests"], cwd=candidate, env=env, stdout=output, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("更新版のテストに失敗しました。現在の版は変更していません。記録: .runtime/update-test.log")
    previous = old
    if Path(old["code"]).resolve() == root.resolve():
        previous = dict(old, code=str(extract_release(root, git(root, "rev-parse", "HEAD").decode().strip())))
    activate(root, {"current": {"code": str(candidate), "python": old["python"], "version": revision}, "previous": previous})
    return "更新しました。勤務データはそのままです。"

def rollback(root):
    saved = state(root)
    if not saved.get("previous"):
        raise RuntimeError("戻せる更新履歴はまだありません。")
    activate(root, {"current": saved["previous"], "previous": saved["current"]})
    return "アプリを更新前の版に戻しました。勤務データはそのままです。"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["update", "rollback"])
    args = parser.parse_args()
    try:
        with operation_lock(ROOT):
            message = update(ROOT) if args.action == "update" else rollback(ROOT)
        show(message)
    except Exception as exc:
        show(exc, True)
        sys.exit(1)
