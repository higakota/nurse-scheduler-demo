"""Windows配布版を、入力データを一切含めずにビルドする。"""
import argparse, hashlib, json, subprocess, sys, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def build(version,output):
    sys.path.insert(0,str(ROOT))
    from desktop_runtime import valid_version
    valid_version(version)
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    work=ROOT/".runtime/distribution-build"/version
    work.mkdir(parents=True,exist_ok=True)
    common=[sys.executable,"-m","PyInstaller","--noconfirm","--clean","--windowed","--icon",str(ROOT/"static/app-icon.ico"),
            "--distpath",str(work/"dist"),"--workpath",str(work/"work"),"--specpath",str(work)]
    command=common+["--onedir","--name","NurseScheduler","--add-data",str(ROOT/"templates")+";templates",
                  "--add-data",str(ROOT/"static")+";static",str(ROOT/"desktop_entry.py")]
    log=work/"build.log"
    with log.open("w",encoding="utf-8") as capture:
        subprocess.run(command,cwd=ROOT,check=True,stdout=capture,stderr=subprocess.STDOUT)
        app=work/"dist/NurseScheduler"
        subprocess.run([str(app/"NurseScheduler.exe"),"--self-check"],cwd=app,check=True,timeout=120)
        manifest={"format":1,"version":version,"files":{}}
        package=work/"release.zip"
        with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(app.rglob("*")):
                if path.is_file():
                    name=path.relative_to(app).as_posix()
                    manifest["files"][name]=hashlib.sha256(path.read_bytes()).hexdigest()
                    archive.write(path,name)
            archive.writestr("package.json",json.dumps(manifest,ensure_ascii=False))
        from desktop_runtime import validate_package
        validate_package(package)
        subprocess.run(common+["--onefile","--name","NurseSchedulerSetup","--add-data",str(package)+";.","--add-data",str(ROOT/"static/app-icon.ico")+";.",str(ROOT/"desktop_setup.py")],
                       cwd=ROOT,check=True,stdout=capture,stderr=subprocess.STDOUT)
    target=output/f"看護師勤務表-セットアップ-{version}.exe"
    target.write_bytes((work/"dist/NurseSchedulerSetup.exe").read_bytes())
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (output/(target.name+".sha256")).write_text(digest+"  "+target.name+"\n",encoding="utf-8")
    print(json.dumps({"installer":str(target),"sha256":digest,"size":target.stat().st_size,"version":version},ensure_ascii=False),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--version",required=True)
    parser.add_argument("--output",type=Path,default=ROOT/"dist")
    args=parser.parse_args()
    build(args.version,args.output)
