"""ローカル専用の起動・更新操作。勤務データは常に元のinstanceに保存する。"""
import json, os, secrets, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent

from contextlib import contextmanager

@contextmanager
def operation_lock(root):
    folder = Path(root) / ".runtime"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "operation.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("起動・更新の処理中です。しばらく待ってから開いてください。")
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def state(root):
    path = root / ".runtime" / "versions.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"current": {"code": str(root), "python": str(root / ".venv/Scripts/python.exe"), "version": "workspace"}}

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)

def health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:5000/health", timeout=1) as response:
            return json.load(response)
    except Exception:
        return None

def token(root):
    path = root / ".runtime" / "owner"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(24), encoding="ascii")
    return path.read_text(encoding="ascii")

def stop_owned(root):
    info = health()
    if info is None:
        return
    record = root / ".runtime" / "server.json"
    if not record.exists() or info.get("app") != "nurse-scheduler" or info.get("owner") != token(root) or info.get("pid") != json.loads(record.read_text())["pid"]:
        raise RuntimeError("別の方法で起動中のアプリがあります。閉じてから操作してください。")
    import signal
    os.kill(info["pid"], signal.SIGTERM)
    for _ in range(50):
        if health() is None:
            return
        time.sleep(.1)
    raise RuntimeError("アプリを終了できませんでした。")

def launch(root=ROOT, open_browser=True):
    root = Path(root).resolve()
    current = state(root)["current"]
    info = health()
    if info:
        if info.get("app") != "nurse-scheduler" or info.get("version") != current["version"] or info.get("owner") != token(root):
            raise RuntimeError("別の版が起動中です。更新または再起動を確認してください。")
        if open_browser:
            webbrowser.open("http://127.0.0.1:5000/")
        return
    from automatic_backup import backup_database
    database = root / "instance/staff.sqlite3"
    backup_database(database, "start")
    env = dict(os.environ, NURSE_SCHEDULER_DATABASE=str(database), NURSE_SCHEDULER_OWNER=token(root), NURSE_SCHEDULER_VERSION=current["version"])
    logs = root / "instance"
    logs.mkdir(exist_ok=True)
    with (logs / "server.stdout.log").open("ab") as out, (logs / "server.stderr.log").open("ab") as err:
        process = subprocess.Popen([current["python"], str(Path(current["code"]) / "app.py")], cwd=current["code"], env=env, stdout=out, stderr=err, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    atomic_json(root / ".runtime/server.json", {"pid": process.pid})
    for _ in range(150):
        info = health()
        if info and info.get("owner") == token(root) and info.get("version") == current["version"]:
            if open_browser:
                webbrowser.open("http://127.0.0.1:5000/")
            return
        if process.poll() is not None:
            break
        time.sleep(.2)
    raise RuntimeError("起動できませんでした。instance/server.stderr.logを確認してください。")

def show(message, error=False):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(message), "看護師勤務表", 16 if error else 64)
    else:
        print(message)

if __name__ == "__main__":
    try:
        with operation_lock(ROOT):
            launch()
    except Exception as exc:
        show(exc, True)
        sys.exit(1)
