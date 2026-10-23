"""配布版のコードと利用者の勤務データを分離して管理する。"""
import hashlib, json, os, re, secrets, shutil, signal, sqlite3, subprocess, sys, tempfile, time, urllib.request, webbrowser, zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path, PurePosixPath
from launcher import atomic_json, operation_lock, token

APP_NAME = "看護師勤務表"
EXE_NAME = "NurseScheduler.exe"
VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")

def default_home():
    return Path(os.environ["LOCALAPPDATA"]) / "NurseScheduler"

def valid_version(value):
    if not isinstance(value,str) or not VERSION_PATTERN.fullmatch(value) or value in (".","..") or value.endswith("."):
        raise ValueError("更新ファイルの版番号が不正です。")
    return value

def installed_state(home):
    path = home / "installation.json"
    if not path.exists(): return None
    value = json.loads(path.read_text(encoding="utf-8"))
    valid_version(value["current"])
    if value.get("previous"): valid_version(value["previous"])
    port = value.get("port",5000)
    if type(port) is not int or not 1024 <= port <= 65535: raise ValueError("起動設定が不正です。")
    return value

def executable(home, version):
    return home / "versions" / valid_version(version) / EXE_NAME

def health(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            return json.load(response)
    except Exception: return None

def owned(home, info):
    record = home / ".runtime/server.json"
    if not record.exists() or not info: return False
    value = json.loads(record.read_text(encoding="utf-8"))
    return info.get("app")=="nurse-scheduler" and info.get("owner")==token(home) and info.get("pid")==value.get("pid")

def stop(home, port):
    info = health(port)
    if not info: return
    if not owned(home,info):
        raise RuntimeError("別のアプリが同じ起動先を使っています。終了してからやり直してください。")
    os.kill(info["pid"],signal.SIGTERM)
    for _ in range(100):
        if health(port) is None: return
        time.sleep(.1)
    raise RuntimeError("アプリを終了できませんでした。")

def command(exe, *args):
    return [str(exe),*map(str,args)]

def launch(home, open_browser=True):
    saved = installed_state(home)
    if not saved: raise RuntimeError("先にセットアップを実行してください。")
    port = saved.get("port",5000)
    url = f"http://127.0.0.1:{port}/"
    info = health(port)
    if info:
        if not owned(home,info) or info.get("version")!=saved["current"]:
            raise RuntimeError("別の版やアプリが起動中です。閉じてから開き直してください。")
    else:
        from automatic_backup import backup_database
        database = home / "data/staff.sqlite3"
        database.parent.mkdir(parents=True,exist_ok=True)
        backup_database(database,"start")
        env = dict(os.environ,NURSE_SCHEDULER_DATABASE=str(database),NURSE_SCHEDULER_OWNER=token(home),NURSE_SCHEDULER_VERSION=saved["current"])
        with (home/"data/server.stdout.log").open("ab") as out, (home/"data/server.stderr.log").open("ab") as err:
            process = subprocess.Popen(command(executable(home,saved["current"]),"--serve","--home",home,"--port",port),
                cwd=home,env=env,stdout=out,stderr=err,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        atomic_json(home/".runtime/server.json",{"pid":process.pid})
        for _ in range(200):
            info = health(port)
            if owned(home,info) and info.get("version")==saved["current"]: break
            if process.poll() is not None: break
            time.sleep(.15)
        else: info = None
        if not owned(home,info) or info.get("version")!=saved["current"]:
            raise RuntimeError("起動できませんでした。管理画面から保存場所を開き、data/server.stderr.logを確認してください。")
    if open_browser: webbrowser.open(url)

def safety_backup(home):
    source = home/"data/staff.sqlite3"
    if not source.exists(): return None
    folder = home/"data/backups";folder.mkdir(parents=True,exist_ok=True)
    target = folder/("before_update_"+datetime.now().strftime("%Y%m%d_%H%M%S_%f")+".sqlite3")
    with closing(sqlite3.connect(str(source),timeout=15)) as db, closing(sqlite3.connect(str(target))) as backup:
        db.backup(backup)
    return target

def activate(home, next_state):
    old = installed_state(home)
    port = (old or next_state).get("port",5000)
    stop(home,port)
    try:
        safety_backup(home)
        atomic_json(home/"installation.json",next_state)
        launch(home,open_browser=False)
    except Exception as error:
        try:
            stop(home,next_state.get("port",5000))
        finally:
            if old:
                atomic_json(home/"installation.json",old)
                launch(home,open_browser=False)
            else:
                (home/"installation.json").unlink(missing_ok=True)
        raise RuntimeError("切り替えを中止しました。登録データは残しています。"+str(error)) from error

def validate_package(package):
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries)>5000 or sum(item.file_size for item in entries)>512*1024*1024:
            raise ValueError("更新ファイルのサイズが不正です。")
        names = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            parts = path.parts
            if (not parts or entry.filename!=path.as_posix() or path.is_absolute() or any(p in (".","..") or p.endswith((" ",".")) or ":" in p or "\\" in p for p in parts)
                or any(p.split(".")[0].upper() in {"CON","PRN","AUX","NUL",*[f"COM{i}" for i in range(1,10)],*[f"LPT{i}" for i in range(1,10)]} for p in parts)
                or (entry.external_attr>>16)&0o170000==0o120000 or entry.is_dir()):
                raise ValueError("安全に展開できない更新ファイルです。")
            key = entry.filename.casefold()
            if key in names: raise ValueError("更新ファイルの名前が重複しています。")
            names.add(key)
            if any(p.casefold() in ("data","instance",".git",".runtime") for p in parts) or path.suffix.lower() in (".sqlite3",".db",".xlsx"):
                raise ValueError("勤務データを含むファイルはインストールできません。")
        if "package.json" not in names: raise ValueError("更新情報がありません。")
        if archive.getinfo("package.json").file_size>2*1024*1024: raise ValueError("更新情報が大きすぎます。")
        manifest=json.loads(archive.read("package.json"))
        valid_version(manifest["version"])
        if manifest.get("format")!=1 or not isinstance(manifest.get("files"),dict):
            raise ValueError("対応していない更新形式です。")
        expected=manifest["files"]
        if set(expected)!={item.filename for item in entries if item.filename!="package.json"} or EXE_NAME not in expected:
            raise ValueError("更新ファイルの構成が不正です。")
        for name,digest in expected.items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:
                raise ValueError("更新ファイルが破損しています。送り直してもらってください。")
        return manifest

def move_staged_release(source,destination):
    # Windows can temporarily hold freshly extracted executable files while scanning.
    for attempt in range(40):
        try:
            source.rename(destination)
            return
        except PermissionError:
            if attempt==39:raise
            time.sleep(.25)

def install(package,home,port=5000,progress=lambda message:None,shortcuts=True):
    home=Path(home).resolve()
    home.mkdir(parents=True,exist_ok=True)
    with operation_lock(home):
        progress("ファイルを確認しています…")
        manifest=validate_package(package)
        version=manifest["version"]
        old=installed_state(home)
        if old and old["current"]==version: return "この版はすでにインストールされています。"
        destination=home/"versions"/version
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():
            saved=destination/".package.json"
            if not saved.exists() or json.loads(saved.read_text(encoding="utf-8"))!=manifest:
                raise ValueError("同じ版番号の異なるファイルがあります。別の版番号で作成してください。")
        else:
            with tempfile.TemporaryDirectory(prefix="install-",dir=destination.parent) as temporary:
                staging=Path(temporary)/"app";staging.mkdir()
                with zipfile.ZipFile(package) as archive:
                    for name in manifest["files"]:
                        target=staging/name;target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_bytes(archive.read(name))
                atomic_json(staging/".package.json",manifest)
                move_staged_release(staging,destination)
        progress("起動できるか確認しています…")
        check=subprocess.run(command(destination/EXE_NAME,"--self-check"),capture_output=True,timeout=120,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if check.returncode: raise RuntimeError("更新版の起動確認に失敗しました。今までの版とデータは変更していません。")
        next_state={"current":version,"previous":old["current"] if old else None,"port":old.get("port",port) if old else port}
        progress("データを保護して切り替えています…")
        activate(home,next_state)
        if shortcuts:
            try:create_shortcuts(home)
            except (OSError,subprocess.SubprocessError):
                return "インストールは完了しましたが、ショートカットを作れませんでした。保存先の versions フォルダ内の NurseScheduler.exe から起動できます。"
        return "更新しました。登録した勤務データはそのままです。" if old else "インストールできました。デスクトップの「看護師勤務表」から開けます。"

def rollback(home):
    with operation_lock(home):
        saved=installed_state(home)
        if not saved or not saved.get("previous"): raise RuntimeError("戻せる更新履歴はまだありません。")
        activate(home,dict(current=saved["previous"],previous=saved["current"],port=saved.get("port",5000)))
    return "前の版に戻しました。勤務データはそのままです。"

def create_shortcuts(home):
    exe=executable(home,installed_state(home)["current"])
    # Environment variables keep filesystem paths out of PowerShell source interpolation.
    script="""
$sh=New-Object -ComObject WScript.Shell
$desktop=[Environment]::GetFolderPath('Desktop')
$menu=Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\\看護師勤務表'
[IO.Directory]::CreateDirectory($menu) | Out-Null
foreach($item in @(@($desktop,'看護師勤務表',''),@($menu,'看護師勤務表',''),@($menu,'更新・保存場所の確認','--manage'))){
 $link=$sh.CreateShortcut((Join-Path $item[0] ($item[1]+'.lnk')))
 $link.TargetPath=$env:NURSE_INSTALL_EXE
 $link.Arguments='--home "'+$env:NURSE_INSTALL_HOME+'" '+$item[2]
 $link.WorkingDirectory=$env:NURSE_INSTALL_HOME
 $link.IconLocation=$env:NURSE_INSTALL_EXE+',0'
 $link.Save()
}
"""
    env=dict(os.environ,NURSE_INSTALL_EXE=str(exe),NURSE_INSTALL_HOME=str(home))
    subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],env=env,check=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
