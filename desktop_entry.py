"""Pythonのインストールが不要なWindows配布版の入口。"""
import argparse, json, os, sys, tempfile
from pathlib import Path
import desktop_runtime as runtime

def self_check():
    with tempfile.TemporaryDirectory() as folder:
        os.environ["NURSE_SCHEDULER_DATABASE"]=str(Path(folder)/"check.sqlite3")
        from app import app
        app.config.update(TESTING=True,AUTO_BACKUP_ENABLED=False,DATABASE=os.environ["NURSE_SCHEDULER_DATABASE"])
        from flask import url_for
        with app.test_request_context():
            paths=[url_for(name) for name in ("index","staff_settings","monthly_settings","doctor_import","coverage_settings","leave_history","help_availability","schedule","manual_schedule","data_backup")]
        client=app.test_client()
        for path in paths+["/static/style.css"]:
            result=client.get(path,follow_redirects=True)
            if result.status_code!=200:raise RuntimeError("起動確認に失敗しました: "+path)
        for folder_name in ("templates","static"):
            if not (Path(__file__).parent/folder_name).is_dir():raise RuntimeError("画面ファイルがありません。")

def serve(home,port):
    import logging
    data=home/"data";data.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=data/"server.stderr.log",encoding="utf-8",level=logging.INFO)
    os.environ["NURSE_SCHEDULER_DATABASE"]=str(data/"staff.sqlite3")
    from app import app
    app.config["DATABASE"]=str(data/"staff.sqlite3")
    from werkzeug.serving import make_server
    make_server("127.0.0.1",port,app,threaded=True).serve_forever()

def manage(home):
    import tkinter as tk
    from tkinter import messagebox
    window=tk.Tk();window.title("看護師勤務表の管理");window.geometry("520x320");window.resizable(False,False)
    saved=runtime.installed_state(home)
    tk.Label(window,text="看護師勤務表",font=("Yu Gothic",17,"bold")).pack(pady=(20,8))
    tk.Label(window,text="使用中の版："+saved["current"]).pack()
    tk.Label(window,text="更新するときは、受け取った新しいセットアップを実行します。\nスタッフや勤務表を入力し直す必要はありません。",justify="left").pack(pady=14)
    def revert():
        if not messagebox.askyesno("前の版に戻す","アプリを前の版へ戻します。勤務データはそのままです。\n保存前の操作を終えてから実行してください。",parent=window):return
        try:
            runtime.rollback(home)
            messagebox.showinfo("完了","前の版に戻しました。",parent=window);window.destroy()
        except Exception as error:messagebox.showerror("戻せませんでした",str(error),parent=window)
    tk.Button(window,text="保存場所を開く",command=lambda:os.startfile(home/"data"),width=26).pack(pady=5)
    tk.Button(window,text="アプリを前の版に戻す",command=revert,width=26,state="normal" if saved.get("previous") else "disabled").pack(pady=5)
    tk.Button(window,text="閉じる",command=window.destroy,width=26).pack(pady=5)
    window.mainloop()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--home",type=Path)
    parser.add_argument("--port",type=int,default=5000)
    parser.add_argument("--serve",action="store_true")
    parser.add_argument("--self-check",action="store_true")
    parser.add_argument("--manage",action="store_true")
    parser.add_argument("--stop",action="store_true")
    args=parser.parse_args()
    if args.self_check:self_check();return
    home=(args.home or runtime.default_home()).resolve()
    if args.serve:serve(home,args.port);return
    if args.manage:manage(home);return
    with runtime.operation_lock(home):
        if args.stop:
            saved=runtime.installed_state(home)
            if saved:runtime.stop(home,saved.get("port",5000))
        else:runtime.launch(home)

if __name__=="__main__":
    try:main()
    except Exception as error:
        if "--self-check" not in sys.argv:
            from launcher import show
            show(error,True)
        sys.exit(1)
