"""架空データだけを扱う、利用者ごとに独立した公開体験版。"""
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from flask import abort, g, redirect, request, session
from demo_seed import seed_database

class DemoStore:
    def __init__(self, root, limit=256, ttl=86400):
        self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.limit=limit
        self.ttl=ttl
        self.guard=threading.Lock()
        self.active={}
        self.locks={}

    def open(self, token):
        if not isinstance(token,str) or not re.fullmatch(r"[0-9a-f]{64}",token):
            token=secrets.token_hex(32)
        with self.guard:
            now=time.time()
            for folder in self.root.iterdir():
                if folder.is_dir() and not folder.is_symlink() and re.fullmatch(r"[0-9a-f]{64}",folder.name):
                    if not self.active.get(folder.name) and now-folder.stat().st_mtime>self.ttl:
                        shutil.rmtree(folder)
                        self.locks.pop(folder.name,None)
            folder=self.root/token
            if folder.is_symlink():
                abort(400)
            if not folder.exists():
                count=sum(p.is_dir() for p in self.root.iterdir())
                if count>=self.limit:
                    abort(503,description="ただいま利用者が多いため、しばらくしてからお試しください。")
                folder.mkdir()
            self.active[token]=self.active.get(token,0)+1
            lock=self.locks.setdefault(token,threading.Lock())
        lock.acquire()
        try:
            database=folder/"demo.sqlite3"
            if not database.exists():
                pending=folder/"initializing.sqlite3"
                pending.unlink(missing_ok=True)
                try:
                    seed_database(pending)
                    os.replace(pending,database)
                except BaseException:
                    pending.unlink(missing_ok=True)
                    raise
            folder.touch()
        except BaseException:
            lock.release()
            with self.guard:
                self.active[token]-=1
            raise
        return token,folder/"demo.sqlite3",lock

    def close(self, token, lock):
        with self.guard:
            (self.root/token).touch()
            self.active[token]-=1
        lock.release()

def register_web_demo(app, root, secure=True):
    app.config.update(DEMO_MODE=True,WEB_DEMO=True,SESSION_COOKIE_SECURE=secure,
                      SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_NAME="scheduler_demo",
                      SESSION_COOKIE_SAMESITE="Lax",PERMANENT_SESSION_LIFETIME=86400,
                      TRUSTED_HOSTS=[".onrender.com","localhost","127.0.0.1"])
    store=DemoStore(root)
    app.extensions["web_demo_store"]=store
    def prepare():
        if request.routing_exception:
            return
        if request.path in ("/health","/favicon.ico") or request.path.startswith("/static/"):
            return
        token,path,lock=store.open(session.get("web_demo_id"))
        g.demo_token=token
        g.demo_lock=lock
        g.demo_database=path
        session["web_demo_id"]=token
        session.permanent=True
        session.setdefault("csrf_token",secrets.token_hex(32))
    # Run before existing backup hooks, including for the first POST.
    app.before_request_funcs.setdefault(None,[]).insert(0,prepare)
    @app.after_request
    def protect(response):
        if getattr(g,"demo_token",None) and not getattr(g,"demo_reset",False):
            session["web_demo_id"]=g.demo_token
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="same-origin"
        response.headers["X-Frame-Options"]="SAMEORIGIN"
        response.headers["X-Robots-Tag"]="noindex, nofollow"
        return response
    @app.teardown_request
    def release(error):
        lock=g.pop("demo_lock",None)
        if lock:
            store.close(g.demo_token,lock)
    def demo_health():
        return {"status":"ok"}
    if "app_health" in app.view_functions:
        app.view_functions["app_health"]=demo_health
    else:
        app.add_url_rule("/health","demo_health",demo_health)
    @app.post("/demo/reset")
    def reset():
        expected=session.get("csrf_token","")
        if not expected or not secrets.compare_digest(expected,request.form.get("csrf_token","")):
            abort(400)
        session.clear()
        g.demo_reset=True
        return redirect("/?month=2026-11")

def create_web_app(root=None, secure=True):
    from app import app
    secret=os.environ.get("DEMO_SECRET_KEY")
    if not secret:
        raise RuntimeError("DEMO_SECRET_KEYを設定してください。")
    app.secret_key=secret
    register_web_demo(app,root or os.environ.get("DEMO_STORAGE_DIR","/tmp/nurse-scheduler-demo"),secure)
    return app
