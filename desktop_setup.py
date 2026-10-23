"""配布版セットアップ。勤務データを同梱せず、更新時も保持する。"""
import argparse, os, sys, threading, traceback
from pathlib import Path
import desktop_runtime as runtime

def setup_window(package,home):
    import tkinter as tk
    from tkinter import messagebox
    window=tk.Tk();window.title("看護師勤務表 セットアップ");window.geometry("580x360");window.resizable(False,False)
    tk.Label(window,text="看護師勤務表",font=("Yu Gothic",20,"bold")).pack(pady=(24,12))
    updating=(home/"installation.json").exists()
    tk.Label(window,text="アプリを更新します。" if updating else "このパソコンにアプリをインストールします。",font=("Yu Gothic",12)).pack()
    tk.Label(window,text="登録したスタッフや勤務表は、このパソコン内に保存します。\n更新しても入力したデータは残ります。",justify="left").pack(pady=12)
    tk.Label(window,text="保存先："+str(home),wraplength=530,fg="#53635d").pack()
    status=tk.StringVar(value="編集中の入力を保存してから更新してください。" if updating else "")
    tk.Label(window,textvariable=status,wraplength=530).pack(pady=12)
    button=tk.Button(window,text="更新する" if updating else "インストールする",width=26)
    button.pack()
    result=[]
    def poll():
        if not result:window.after(120,poll);return
        ok,text=result[0]
        button.config(state="normal");window.protocol("WM_DELETE_WINDOW",window.destroy)
        if ok:
            messagebox.showinfo("完了",text,parent=window)
            runtime.launch(home);window.destroy()
        else:messagebox.showerror("セットアップできませんでした",text,parent=window)
    def execute():
        button.config(state="disabled");window.protocol("WM_DELETE_WINDOW",lambda:None)
        def work():
            try:result.append((True,runtime.install(package,home,progress=lambda text:window.after(0,status.set,text))))
            except Exception as error:result.append((False,str(error)))
        threading.Thread(target=work,daemon=True).start()
        window.after(120,poll)
    button.config(command=execute)
    window.mainloop()

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--home",type=Path)
    parser.add_argument("--package",type=Path)
    parser.add_argument("--quiet",action="store_true")
    parser.add_argument("--no-shortcuts",action="store_true")
    parser.add_argument("--port",type=int,default=5000)
    args=parser.parse_args()
    home=(args.home or runtime.default_home()).resolve()
    package=args.package or Path(getattr(sys,"_MEIPASS",Path(__file__).parent))/"release.zip"
    try:
        if args.quiet:runtime.install(package,home,args.port,shortcuts=not args.no_shortcuts)
        else:setup_window(package,home)
    except Exception as error:
        try:
            log=home/".runtime/setup-error.log"
            log.parent.mkdir(parents=True,exist_ok=True)
            log.write_text(traceback.format_exc(),encoding="utf-8")
        except OSError:pass
        if not args.quiet:
            from launcher import show
            show(error,True)
        sys.exit(1)
