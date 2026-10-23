"""通常の保存先と、ブラウザ体験版の利用者別保存先を解決する。"""
from pathlib import Path
from flask import g, has_request_context

def database_path(config):
    if has_request_context() and getattr(g, "demo_database", None):
        return Path(g.demo_database)
    return Path(config["DATABASE"])
