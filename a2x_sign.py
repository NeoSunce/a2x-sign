#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1A2X 社区 (https://1a2x.com) 每日签到 —— 领香蕉
原理与 NodeSeek 版相同：只用 Cookie 登录态，不存密码。
签到入口在「社区成长」页 (/growth) 与首页右侧栏，是一个服务端渲染的
表单（class=daily-checkin，带 _csrf 隐藏字段）。本脚本不写死提交地址：
每次先 GET 页面、解析出当天真实的签到表单（action + 全部隐藏字段）再 POST，
站点小改版也不容易签废。

环境变量：
  A2X_COOKIE   必填，登录态 Cookie 整串（Header String 形式）
  A2X_BASE     可选，默认 https://1a2x.com

退出码：0 = 今日已签到（含重复签到提示）；1 = 失败。
日志绝不打印 Cookie 原文。
"""
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlencode

BASE = os.environ.get("A2X_BASE", "https://1a2x.com").rstrip("/")
COOKIE = os.environ.get("A2X_COOKIE", "").strip()

try:
    from curl_cffi import requests as http  # 与 ns-sign 同款，过 Cloudflare 指纹更稳
    IMPERSONATE = {"impersonate": "chrome"}
except Exception:  # 兜底
    import requests as http
    IMPERSONATE = {}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

ALREADY_WORDS = ("已签到", "今日已签", "已领取", "already checked", "already signed")
SUCCESS_HINTS = ("签到成功", "获得", "香蕉", "banana")


def log(msg):
    print(msg, flush=True)


def fail(msg):
    log("签到失败：" + msg)
    sys.exit(1)


class FormParser(HTMLParser):
    """收集页面里所有 form 及其 input/button，供定位签到表单。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self._form = None
        self._button_text = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._form = {"action": a.get("action", ""), "method": (a.get("method") or "get").lower(),
                          "class": a.get("class", ""), "id": a.get("id", ""), "inputs": [], "buttons": []}
        elif self._form is not None and tag == "input":
            self._form["inputs"].append(a)
        elif self._form is not None and tag == "button":
            self._button_text = ""
            self._form["buttons"].append({"attrs": a, "text": ""})

    def handle_data(self, data):
        if self._form is not None and self._button_text is not None and self._form["buttons"]:
            self._form["buttons"][-1]["text"] += data

    def handle_endtag(self, tag):
        if tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None
        if tag == "button":
            self._button_text = None


def find_checkin_form(html):
    p = FormParser()
    p.feed(html)
    for f in p.forms:
        blob = (f["class"] + " " + f["id"] + " " + f["action"] + " " +
                " ".join(b.get("text", "") for b in f["buttons"]))
        if "checkin" in blob or "签到" in blob or "daily" in blob:
            return f
    return None


def page_state(html):
    """返回 (是否已签到, 香蕉余额或None)。"""
    text = re.sub(r"<[^>]+>", " ", html)
    already = any(w in text for w in ALREADY_WORDS)
    m = re.search(r"余额[^0-9]{0,6}([0-9,]+)\s*香蕉|([0-9,]+)\s*香蕉", text)
    balance = (m.group(1) or m.group(2)) if m else None
    return already, balance


def get_page(sess, url):
    try:
        r = sess.get(url, headers={"User-Agent": UA, "Accept": "text/html"}, timeout=30, **IMPERSONATE)
    except Exception as e:
        fail(f"打开页面出错：{type(e).__name__}")
    try:
        r.encoding = "utf-8"  # 站点是 UTF-8；不强制时中文关键字会被错误解码、匹配不到
    except Exception:
        pass
    return r


def main():
    if not COOKIE:
        fail("没有配置 A2X_COOKIE（GitHub Secret 未填或为空）")

    sess = http.Session()
    sess.headers.update({"Cookie": COOKIE, "User-Agent": UA})

    # 1) 先看成长页，没有签到表单再看首页右侧栏
    target_url, html, form = None, None, None
    for path in ("/growth", "/"):
        r = get_page(sess, BASE + path)
        if r.status_code != 200:
            log(f"打开 {path} 返回 {r.status_code}")
            continue
        if "/login" in (r.url or ""):
            fail("Cookie 已失效（被重定向到登录页），需要重新填 A2X_COOKIE")
        target_url, html = BASE + path, r.text
        form = find_checkin_form(html)
        if form:
            break

    if html is None:
        fail("页面打不开，网络或站点异常")

    already, bal_before = page_state(html)
    if form is None:
        if already:
            log(f"签到成功：今天已经签过到了" + (f"（当前香蕉 {bal_before}）" if bal_before else ""))
            return
        fail("没找到签到表单，也没看到已签到标记——可能未登录或页面改版，需要人工检查")

    # 2) 组装表单数据：全部隐藏/已有字段原样带上 + 提交按钮（若有 name）
    data = {}
    for inp in form["inputs"]:
        name = inp.get("name")
        if not name:
            continue
        t = (inp.get("type") or "text").lower()
        if t in ("checkbox", "radio") and "checked" not in inp:
            continue
        data[name] = inp.get("value", "")
    for b in form["buttons"]:
        ba = b["attrs"]
        if ba.get("name") and (ba.get("type") or "submit").lower() == "submit":
            data[ba["name"]] = ba.get("value", "")
            break

    action = urljoin(target_url, form["action"] or target_url)
    csrf_meta = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
    headers = {"User-Agent": UA, "Referer": target_url,
               "Content-Type": "application/x-www-form-urlencoded"}
    if csrf_meta:
        headers["X-CSRF-Token"] = csrf_meta.group(1)

    log(f"提交签到：POST {action} 字段={sorted(data.keys())}")
    try:
        if form["method"] == "get":
            r = sess.get(action + "?" + urlencode(data), headers=headers, timeout=30, **IMPERSONATE)
        else:
            r = sess.post(action, data=data, headers=headers, timeout=30,
                          allow_redirects=True, **IMPERSONATE)
    except Exception as e:
        fail(f"提交签到出错：{type(e).__name__}")
    try:
        r.encoding = "utf-8"
    except Exception:
        pass
    if "/login" in (r.url or ""):
        fail("提交后被重定向到登录页，Cookie 已失效")
    if r.status_code >= 400:
        fail(f"提交返回 HTTP {r.status_code}")

    # 3) 回查：再打开成长页确认状态
    r2 = get_page(sess, BASE + "/growth")
    html2 = r2.text if r2.status_code == 200 else r.text
    already2, bal_after = page_state(html2)
    body_text = re.sub(r"<[^>]+>", " ", r.text)
    got = re.search(r"(?:获得|奖励|签到成功)[^0-9]{0,8}([0-9]+)\s*香蕉", body_text)

    if already2 or got or any(w in body_text for w in ("签到成功",)):
        reward = got.group(1) if got else None
        msg = "签到成功："
        msg += f"今天签到获得 {reward} 香蕉" if reward else "今日签到已完成"
        if bal_after:
            msg += f"（当前香蕉 {bal_after}）"
        log(msg)
        return
    if already and not form:
        log("签到成功：今天已经签过到了")
        return
    fail("提交后回查不到已签到状态，结果不确定，需要人工检查（已保留完整日志）")


if __name__ == "__main__":
    main()
