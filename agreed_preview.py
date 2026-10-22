"""確認した調整案を保存時に再探索しない。個人情報はサーバー内の短期メモリだけに置く。"""
import copy
import secrets
import time
from flask import current_app,session,request


def remember(kind,signature,plan):
    cache=current_app.extensions.setdefault("agreed_plan_cache",{})
    old=session.pop(kind+"_plan",None)
    if old:
        cache.pop(old,None)
    now=time.monotonic()
    for key in list(cache):
        if now-cache[key][0]>900:
            del cache[key]
    while len(cache)>=32:
        del cache[next(iter(cache))]
    token=secrets.token_hex(24)
    cache[token]=(now,signature,copy.deepcopy(plan))
    session[kind+"_plan"]=token


def recalled(kind,signature):
    token=session.get(kind+"_plan")
    if request.form.get("plan_token") and request.form["plan_token"]!=token:
        raise ValueError("別の画面で調整案が更新されています。変更内容をもう一度確認してください。")
    entry=current_app.extensions.get("agreed_plan_cache",{}).get(token)
    if not entry or time.monotonic()-entry[0]>900 or entry[1]!=signature:
        raise ValueError("確認した調整案の有効期限が切れました。変更内容をもう一度確認してください。")
    return copy.deepcopy(entry[2])


def forget(kind):
    token=session.pop(kind+"_plan",None)
    current_app.extensions.get("agreed_plan_cache",{}).pop(token,None)
