#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — 把 book/ 目录里的 Markdown 正文渲染成自包含的单文件 HTML 阅读页。

页面结构与交互严格对齐参考项目 HowToLiveBetter（eternity4719/HowToLiveBetter）：
固定顶栏 + 左侧筛选侧栏 + 右侧内容区，卡片含徽章/说人话/字段行/来源折叠。

用法：
    python build.py                # 渲染全部小节，输出 index.html
    python build.py 1 3 7          # 只渲染指定小节
    python build.py -o out.html    # 指定输出文件

正文格式（book/NN-*.md）：
    # N. 节标题
    （节简介，任意段）

    ### 1. 条目标题
    <!-- 成本标签: 钱=0 时间=少 毅力=是 收益=大 -->
    - 成本：……
    - 说人话：……
    - 收益：……
    - 证据等级：A
    - 来源：……
    - 备注：……

零第三方依赖，Python 3.8+ 可直接运行。生成的 HTML 无外部资源，双击即可离线阅读。
"""

import argparse
import datetime
import html
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOOK = ROOT / "book"
OUT_DEFAULT = ROOT / "index.html"
TITLE = "高性价比运动指南"
SUBTITLE = "没时间去健身房，用最少的时间换回最多的健康"
# 发布到 GitHub 后把这里换成你的仓库地址（顶栏图标 / README / PDF 下载会指向它）
REPO = "https://github.com/kexin1409/how-to-exercise-better"
# PDF 用 Pages 地址直链：浏览器原生打开预览并可另存，避开 GitHub 网页端 PDF 预览抽风
PDF_URL = "https://kexin1409.github.io/how-to-exercise-better/how-to-exercise-better.pdf"

RE_SEC = re.compile(r"^#\s+(.*)$")
RE_ENTRY = re.compile(r"^###\s+(\d+)\.\s*(.*)$")
RE_TAGS = re.compile(r"^<!--\s*成本标签:\s*(.*?)\s*-->")
RE_FIELD = re.compile(r"^-\s*(成本|说人话|收益|证据等级|来源|备注)\s*：\s*(.*)$")

FIELDS = ["成本", "说人话", "收益", "证据等级", "来源", "备注"]

COST_W = {"0": 0, "少": 1, "多": 2}
TIME_W = {"0": 0, "少": 0, "中": 1, "多": 2}
WILL_W = {"0": 0, "否": 0, "些": 1, "是": 2}
RATIO_CLS = {"极高": "r3", "高": "r2", "一般": "r1"}
LABEL = {
    "钱": {"0": "不花钱", "少": "花少量钱", "多": "花不少钱"},
    "时间": {"0": "顺手", "少": "顺手", "中": "花几小时", "多": "每天占时间"},
    "毅力": {"0": "不用毅力", "否": "不用毅力", "些": "要一点毅力", "是": "要很多毅力"},
}


# ---------------------------------------------------------------- 解析

def avail_sections():
    out = []
    if BOOK.is_dir():
        for p in sorted(BOOK.glob("[0-9][0-9]-*.md")):
            m = re.match(r"(\d+)", p.name)
            if m:
                out.append(int(m.group(1)))
    return out


def find_file(n):
    cands = sorted(BOOK.glob("%02d-*.md" % n))
    return cands[0] if cands else None


def parse(path):
    """把一个节文件解析成 {no, title, intro, entries}。"""
    no = int(re.match(r"(\d+)", path.name).group(1))
    title, intro, entries = "", [], []
    cur = None
    last_field = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        m = RE_SEC.match(line)
        if m and not entries and not title:
            title = m.group(1).strip()
            title = re.sub(r"^\d+[.、]\s*", "", title)  # 正文标题自带编号，渲染时统一再加，避免“1. 1.”重复
            continue
        m = RE_ENTRY.match(line)
        if m:
            cur = {"no": int(m.group(1)), "title": m.group(2).strip(),
                   "tags_raw": "", "fields": {}}
            entries.append(cur)
            last_field = None
            continue
        m = RE_TAGS.match(line)
        if m and cur is not None:
            cur["tags_raw"] = m.group(1)
            continue
        m = RE_FIELD.match(line)
        if m and cur is not None:
            cur["fields"][m.group(1)] = m.group(2).strip()
            last_field = m.group(1)
            continue
        if cur is not None:
            if line.strip() and last_field:
                cur["fields"][last_field] += " " + line.strip()
            continue
        if title and not line.startswith("[") and line.strip():
            intro.append(line.strip())
    return {"no": no, "title": title, "intro": intro, "entries": entries}


def parse_tags(raw):
    t = {}
    for k, v in re.findall(r"(钱|时间|毅力|收益|口径)=(\S+)", raw or ""):
        t[k] = v
    return t


def ratio_of(t):
    cs = COST_W.get(t.get("钱", "少"), 1) + TIME_W.get(t.get("时间", "少"), 1) \
        + WILL_W.get(t.get("毅力", "否"), 1)
    b = t.get("收益", "中")
    if b == "大":
        return "极高" if cs == 0 else ("高" if cs <= 2 else "一般")
    if b == "中":
        return "高" if cs == 0 else "一般"
    return "一般"


def level_of(e):
    lv = (e["fields"].get("证据等级") or "C").strip()
    return lv[0].upper() if lv and lv[0].upper() in "ABC" else "C"


def link_count(s):
    return len(re.findall(r"https?://", s or ""))


def esc(s):
    return html.escape(s or "", quote=False)


URL_RE = re.compile(
    r"\[([^\]]+)\]\((https?://[^)\s]+)\)"     # 1,2  [text](url)
    r"|<(https?://[^>\s]+)>"                  # 3    <url>
    r"|(https?://[^\s，。；）】」]+)"           # 4    裸 URL
)


def _inline_base(s):
    s = esc(s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def inline(s, sec_no=None, targets=None):
    """行内 Markdown → HTML：链接、加粗，交叉引用变成可点。"""
    out, last = [], 0
    for m in URL_RE.finditer(s):
        out.append(_xref(_inline_base(s[last:m.start()]), sec_no, targets))
        if m.group(1):
            out.append('<a href="%s" target="_blank" rel="noopener">%s</a>'
                       % (esc(m.group(2)), _xref(_inline_base(m.group(1)), sec_no, targets)))
        else:
            u = m.group(3) or m.group(4)
            out.append('<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(u), esc(u)))
        last = m.start() + len(m.group(0))
    out.append(_xref(_inline_base(s[last:]), sec_no, targets))
    return "".join(out)


def inline_src(s, sec_no=None, targets=None):
    """来源栏：行内文字 + 裸链接换行甩到后面（对齐参考页 urlsLast）。"""
    out, tail, last = [], [], 0
    for m in URL_RE.finditer(s):
        seg = s[last:m.start()]
        out.append(_xref(_inline_base(seg), sec_no, targets))
        if m.group(1):
            out.append('<a href="%s" target="_blank" rel="noopener">%s</a>'
                       % (esc(m.group(2)), _xref(_inline_base(m.group(1)), sec_no, targets)))
        else:
            u = m.group(3) or m.group(4)
            tail.append('<a class="url" href="%s" target="_blank" rel="noopener">%s</a>'
                        % (esc(u), esc(u)))
        last = m.start() + len(m.group(0))
    out.append(_xref(_inline_base(s[last:]), sec_no, targets))
    return "".join(out) + "".join(tail)


XREF_NUMS = r"[\d、]+(?:\s*到\s*\d+)?"
XREF_RE = re.compile(r"第\s*(\d+)\s*节第\s*(%s)\s*条|本节第\s*(%s)\s*条"
                     % (XREF_NUMS, XREF_NUMS))


def _expand(nums):
    m = re.match(r"^(\d+)\s*到\s*(\d+)$", nums.replace(" ", ""))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return list(range(a, min(b, a + 40) + 1))
    return [int(x) for x in re.findall(r"\d+", nums)]


def _xref(s, sec_no, targets):
    """把「见第 X 节第 Y 条」「本节第 Y 条」变成可点引用，解析不到的原样保留。"""
    if sec_no is None or not s:
        return s

    def repl(m):
        secs = [int(m.group(1))] if m.group(1) else [sec_no]
        for sn in secs:
            for it in _expand(m.group(2) or m.group(3)):
                key = "%d-%d" % (sn, it)
                if key in targets:
                    return '<span class="xref" data-go="e-%s">%s</span>' % (key, m.group(0))
        return m.group(0)

    return XREF_RE.sub(repl, s)


def split_src(text):
    """来源栏按「；」拆条；括号和引号里的分号不算分隔符。"""
    parts, buf, depth = [], "", 0
    for i, c in enumerate(text):
        if c in "「『（":
            depth += 1
        if c in "」』）":
            depth = max(0, depth - 1)
        semi = c == "；"
        if semi and depth == 0:
            parts.append(buf)
            buf = ""
            continue
        buf += c
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------- 渲染

def render_entry(e, sec_no, targets):
    t = parse_tags(e["tags_raw"])
    f = e["fields"]
    lv = level_of(e)
    ratio = ratio_of(t)
    anchor = "e-%d-%d" % (sec_no, e["no"])
    note = f.get("备注", "")
    dispute = note.startswith("争议")
    todo = any("待核实" in f.get(k, "") or "TODO" in f.get(k, "")
               for k in ("成本", "收益", "来源", "备注"))
    hay = " ".join([e["title"], f.get("说人话", ""), f.get("成本", ""),
                    f.get("收益", ""), note, f.get("来源", "")]) \
        .replace("**", "").lower()
    hay_attr = esc(hay.replace('"', ""))

    badges = ['<span class="badge %s" title="作者判断：由收益量级（%s）和三项成本合成，与证据等级无关">性价比 %s</span>'
              % (RATIO_CLS[ratio], esc(t.get("收益", "中")), ratio),
              '<span class="badge %s" title="%s">证据 %s 级</span>'
              % (lv, {"A": "荟萃分析或随机对照试验", "B": "有研究支持，但不算最硬",
                      "C": "主要是共识和常识"}[lv], lv)]
    for k in ("钱", "时间", "毅力"):
        if k in t:
            badges.append('<span class="badge plain">%s</span>' % LABEL[k].get(t[k], t[k]))
    if "口径" in t:
        badges.append('<span class="badge plain">%s</span>' % esc(t["口径"]))
    if dispute:
        badges.append('<span class="badge danger">争议</span>')
    if todo:
        badges.append('<span class="badge warn">含待核实</span>')

    human = ""
    if f.get("说人话"):
        human = '<p class="human">%s</p>' % inline(f["说人话"], sec_no, targets)

    rows = []
    for k in ("成本", "收益", "备注"):
        if f.get(k):
            rows.append('<div class="k">%s</div><div class="v%s">%s</div>'
                        % (k, " note" if k == "备注" else "",
                           inline(f[k], sec_no, targets)))

    src = f.get("来源", "")
    parts = split_src(src)
    if len(parts) >= 2:
        src_body = "<ol>%s</ol>" % "".join(
            "<li>%s</li>" % inline_src(p, sec_no, targets) for p in parts)
    else:
        src_body = inline_src(src, sec_no, targets) if src else ""
    n_src = link_count(src)
    cnt = ' <span class="cnt">· %d 条</span>' % n_src if n_src > 1 else ""

    return ('<article class="card" id="%s" data-sec="%d" data-ratio="%s" data-grade="%s"'
            ' data-money="%s" data-time="%s" data-will="%s" data-dispute="%d" data-todo="%d"'
            ' data-t="%s">'
            '<div class="card-h"><span class="idx">%d</span><h3 class="t">%s</h3>'
            '<a class="anchor" href="#%s" aria-label="本条链接">#</a></div>'
            '<div class="badges">%s</div>%s'
            '<div class="rows">%s</div>'
            '<details class="src"><summary>来源%s</summary><div class="body">%s</div></details>'
            '</article>'
            % (anchor, sec_no, ratio, lv,
               esc(t.get("钱", "")), esc(t.get("时间", "")), esc(t.get("毅力", "")),
               1 if dispute else 0, 1 if todo else 0, hay_attr,
               e["no"], esc(e["title"]), anchor,
               "".join(badges), human, "".join(rows), cnt, src_body))


CSS = r"""
:root{
  --bg:#ffffff; --bg-alt:#f6f6f7; --bg-soft:#f6f6f7; --bg-mute:#f1f1f2; --bg-elv:#ffffff;
  --divider:#e2e2e3; --gutter:#e2e2e3;
  --t1:rgba(60,60,67,1); --t2:rgba(60,60,67,.78); --t3:rgba(60,60,67,.56);
  --brand-1:#3451b2; --brand-2:#3a5ccc; --brand-3:#5672cd; --brand-soft:rgba(100,108,255,.14);
  --green-1:#18794e; --green-soft:rgba(16,185,129,.14);
  --yellow-1:#915930; --yellow-soft:rgba(234,179,8,.14);
  --red-1:#b8272c; --red-soft:rgba(244,63,94,.14);
  --gray-1:#565a5f; --gray-soft:rgba(142,150,170,.14);
  --mark:rgba(234,179,8,.32);
  --shadow:0 1px 2px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.06);
  --font:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --nav-h:64px; --side-w:272px;
  color-scheme:light;
}
html.dark{
  --bg:#1b1b1f; --bg-alt:#161618; --bg-soft:#202127; --bg-mute:#2b2b2f; --bg-elv:#202127;
  --divider:#2e2e32; --gutter:#000000;
  --t1:rgba(255,255,245,.86); --t2:rgba(235,235,245,.6); --t3:rgba(235,235,245,.38);
  --brand-1:#a8b1ff; --brand-2:#5c73e7; --brand-3:#3e63dd; --brand-soft:rgba(100,108,255,.16);
  --green-1:#3dd68c; --green-soft:rgba(16,185,129,.16);
  --yellow-1:#f9b44e; --yellow-soft:rgba(234,179,8,.16);
  --red-1:#f66f81; --red-soft:rgba(244,63,94,.16);
  --gray-1:#a4a8ae; --gray-soft:rgba(142,150,170,.16);
  --mark:rgba(234,179,8,.28);
  --shadow:0 1px 2px rgba(0,0,0,.3);
  color-scheme:dark;
}
*{box-sizing:border-box}
html{scroll-padding-top:calc(var(--nav-h) + 16px)}
body{margin:0;background:var(--bg);color:var(--t1);font:14px/1.7 var(--font);-webkit-font-smoothing:antialiased}
a{color:var(--brand-1);text-decoration:none;transition:color .25s}
a:hover{color:var(--brand-2);text-decoration:underline;text-underline-offset:2px}
button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}
:focus-visible{outline:2px solid var(--brand-1);outline-offset:2px;border-radius:4px}
mark{background:var(--mark);color:inherit;border-radius:2px;padding:0 1px}
/* 正文里的「第 X 节第 Y 条」交叉引用：点一下滚过去，目标条目闪一下底色 */
.xref{color:var(--brand-1);cursor:pointer;border-bottom:1px dashed currentColor}
.xref:hover{color:var(--brand-2);border-bottom-style:solid}
.card.flash{animation:xflash 1.8s ease-out}
@keyframes xflash{0%,35%{background:var(--brand-soft)}100%{background:transparent}}
[hidden]{display:none!important}

/* nav */
.nav{position:fixed;top:0;left:0;right:0;height:var(--nav-h);z-index:30;background:var(--bg);border-bottom:1px solid var(--divider)}
.nav-in{height:100%;display:flex;align-items:center;gap:16px;padding:0 24px}
.title{display:flex;align-items:center;gap:10px;font-weight:600;font-size:16px;color:var(--t1);white-space:nowrap}
.title:hover{text-decoration:none;color:var(--t1)}
.logo{width:24px;height:24px;border-radius:6px;background:linear-gradient(135deg,var(--brand-3),var(--brand-1));display:grid;place-items:center;color:#fff;font-size:12px;font-weight:700}
.logo svg{width:15px;height:15px}
.search{flex:1;max-width:520px;margin-left:auto;position:relative}
.search input{width:100%;height:40px;padding:0 44px 0 40px;border-radius:8px;border:1px solid transparent;background:var(--bg-alt);color:var(--t1);font:inherit;font-size:14px;transition:border-color .25s,background .25s}
.search input:hover{border-color:var(--divider)}
.search input:focus{outline:0;border-color:var(--brand-1);background:var(--bg)}
.search input::placeholder{color:var(--t3)}
.search svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);width:18px;height:18px;fill:none;stroke:var(--t3);stroke-width:2;pointer-events:none}
.search kbd{position:absolute;right:10px;top:50%;transform:translateY(-50%);font:500 11px/1 var(--font);color:var(--t3);border:1px solid var(--divider);border-radius:4px;padding:3px 6px;background:var(--bg-elv);pointer-events:none}
.nav-r{display:flex;align-items:center;gap:8px}
.icon-btn{width:36px;height:36px;border-radius:8px;display:grid;place-items:center;color:var(--t2);transition:background .25s,color .25s}
.icon-btn:hover{background:var(--bg-soft);color:var(--t1)}
.icon-btn svg{width:20px;height:20px;fill:currentColor}
.switch{position:relative;width:40px;height:22px;border-radius:11px;border:1px solid var(--divider);background:var(--bg-mute);transition:border-color .25s,background .25s;flex:none;margin-left:8px}
.switch:hover{border-color:var(--t3)}
.switch .knob{position:absolute;top:1px;left:1px;width:18px;height:18px;border-radius:50%;background:var(--bg-elv);box-shadow:var(--shadow);transition:transform .25s;display:grid;place-items:center}
html.dark .switch .knob{transform:translateX(18px)}
.switch svg{width:12px;height:12px;fill:var(--t2)}
.switch .sun{display:block} .switch .moon{display:none}
html.dark .switch .sun{display:none} html.dark .switch .moon{display:block}
.menu-btn{display:none}
/* PDF 下载横幅（正文内卡片） */
.pdfbar{display:flex;align-items:center;gap:12px;margin:0 0 22px;padding:12px 16px;border:1px solid var(--brand-3);border-radius:12px;background:var(--brand-soft);font-size:14px;color:var(--t1)}
.pdfbar .ic{font-size:19px;line-height:1;flex:none}
.pdfbar .txt{flex:1;min-width:0}
.pdfbar b{color:var(--brand-1)}
.pdfbar a.dl{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:9px;background:var(--brand-1);color:#fff;font-weight:600;white-space:nowrap;flex:none;transition:background .2s,transform .1s}
.pdfbar a.dl:hover{background:var(--brand-2);text-decoration:none}
.pdfbar a.dl:active{transform:translateY(1px)}
.pdfbar a.dl svg{width:15px;height:15px;fill:none;stroke:#fff;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
.pdfbar .x{margin-left:2px;width:28px;height:28px;border-radius:7px;color:var(--t3);font-size:20px;line-height:1;display:grid;place-items:center;flex:none;transition:background .2s,color .2s}
.pdfbar .x:hover{background:var(--bg-soft);color:var(--t1)}
@media(max-width:640px){.pdfbar{flex-wrap:wrap;gap:8px 10px;padding:11px 14px}.pdfbar .txt{order:2;flex-basis:100%;font-size:13px}.pdfbar a.dl{order:1}.pdfbar .x{order:0;margin-left:auto}}

/* sidebar */
.sidebar{position:fixed;top:var(--nav-h);bottom:0;left:0;width:var(--side-w);background:var(--bg-alt);padding:32px 32px 96px;overflow-y:auto;overscroll-behavior:contain;z-index:20}
.group{padding-bottom:20px;margin-bottom:20px;border-bottom:1px solid var(--divider)}
.group:last-of-type{border-bottom:0}
.gt{font-size:14px;font-weight:700;color:var(--t1);line-height:24px;margin-bottom:4px;display:flex;justify-content:space-between;align-items:baseline}
.gt small{font-weight:400;font-size:12px;color:var(--t3)}
.sec-links{display:flex;flex-direction:column}
.sec-link{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:4px 0;font-size:14px;font-weight:500;color:var(--t2);line-height:24px;text-align:left;transition:color .25s;border-radius:0}
.sec-link:hover{color:var(--t1)}
.sec-link[aria-pressed="true"]{color:var(--brand-1)}
.sec-link i{font-style:normal;font-size:12px;color:var(--t3);font-variant-numeric:tabular-nums}
.sec-link.all{padding-bottom:8px;margin-bottom:4px;border-bottom:1px solid var(--divider)}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding-top:6px}
.chip{border:1px solid var(--divider);background:var(--bg-elv);color:var(--t2);border-radius:999px;padding:3px 11px;font-size:12px;font-weight:500;line-height:18px;transition:all .2s}
.chip:hover{border-color:var(--brand-3);color:var(--t1)}
.chip[aria-pressed="true"]{background:var(--brand-soft);border-color:var(--brand-1);color:var(--brand-1)}
.toggle{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--t2);padding:4px 0;cursor:pointer;font-weight:500}
.toggle input{accent-color:var(--brand-1);width:15px;height:15px;margin:0}
.reset{display:inline-flex;align-items:center;gap:6px;margin-top:8px;padding:6px 14px;border:1px solid var(--divider);border-radius:20px;font-size:13px;font-weight:500;color:var(--t2);background:var(--bg-elv);transition:all .25s}
.reset:hover{border-color:var(--brand-1);color:var(--brand-1)}
.hint{font-size:12px;color:var(--t3);line-height:1.6;margin-top:16px}
.hint p{margin:4px 0}
.backdrop{display:none}

/* content */
.content{padding:calc(var(--nav-h) + 40px) 48px 128px calc(var(--side-w) + 48px)}
.doc{max-width:900px;margin:0 auto}
.doc-head{margin-bottom:28px}
.doc-head h1{font-size:32px;line-height:40px;font-weight:700;letter-spacing:-.02em;margin:0 0 8px}
.doc-head p{margin:0;color:var(--t2);font-size:16px}
.doc-head .stat{color:var(--t3);font-size:14px;margin-top:6px}
.doc-head .stat b{color:var(--brand-1);font-weight:600}
.sec-block{margin-top:40px}
.sec-h{display:flex;align-items:baseline;gap:12px;padding-top:24px;border-top:1px solid var(--divider);margin-bottom:8px}
.sec-h h2{font-size:24px;line-height:32px;font-weight:600;letter-spacing:-.02em;margin:0}
.sec-h .shown{margin-left:auto;font-size:13px;color:var(--t3);font-variant-numeric:tabular-nums}
.intro{margin:0 0 12px;color:var(--t2);font-size:14px;max-width:72ch}
.intro:last-of-type{margin-bottom:20px}

.card{background:var(--bg-soft);border:1px solid transparent;border-radius:12px;padding:22px 24px 18px;margin-bottom:16px;transition:border-color .25s,background .25s;content-visibility:auto;contain-intrinsic-size:auto 300px}
.card:hover{border-color:var(--divider)}
.card-h{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px}
.card-h h3{margin:0;font-size:18px;line-height:28px;font-weight:600;letter-spacing:-.01em;flex:1;min-width:0;overflow-wrap:anywhere}
.card-h .idx{color:var(--t3);font-size:14px;line-height:28px;font-variant-numeric:tabular-nums;min-width:22px}
.card-h .anchor{opacity:0;color:var(--brand-1);font-size:16px;line-height:28px;font-weight:500;transition:opacity .2s}
.card:hover .anchor,.anchor:focus-visible{opacity:1}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.badge{display:inline-block;border-radius:10px;padding:0 10px;line-height:20px;font-size:12px;font-weight:600;white-space:nowrap}
.badge.A{background:var(--green-soft);color:var(--green-1)}
.badge.B{background:var(--yellow-soft);color:var(--yellow-1)}
.badge.C{background:var(--gray-soft);color:var(--gray-1)}
.badge.danger{background:var(--red-soft);color:var(--red-1)}
.badge.warn{background:var(--yellow-soft);color:var(--yellow-1)}
.badge.plain{background:var(--gray-soft);color:var(--t2);font-weight:500}
.badge.r3{background:var(--brand-soft);color:var(--brand-1)}
.badge.r2{background:var(--green-soft);color:var(--green-1)}
.badge.r1{background:var(--gray-soft);color:var(--gray-1)}
.human{margin:0 0 14px;padding:10px 14px;border-left:2px solid var(--brand-1);background:var(--brand-soft);border-radius:0 6px 6px 0;font-size:15px;line-height:1.75;color:var(--t1);overflow-wrap:anywhere}
.rows{display:grid;grid-template-columns:auto 1fr;gap:8px 16px;font-size:14px;line-height:1.75}
.rows .k{color:var(--t3);font-weight:500;font-size:13px;line-height:1.75;padding-top:1px}
.rows .v{color:var(--t1);min-width:0;overflow-wrap:anywhere}
.rows .v.note{color:var(--t2)}
.rows .v strong,.human strong,.intro strong,.src .body strong{font-weight:600;color:var(--t1)}
.src{margin-top:14px;border-top:1px solid var(--divider);padding-top:10px}
.src summary{list-style:none;cursor:pointer;font-size:13px;font-weight:500;color:var(--t2);display:flex;align-items:center;gap:6px;user-select:none}
.src summary::-webkit-details-marker{display:none}
.src summary::before{content:"";width:6px;height:6px;border-right:1.5px solid var(--t3);border-bottom:1.5px solid var(--t3);transform:rotate(-45deg);transition:transform .2s;margin-right:2px}
.src[open] summary::before{transform:rotate(45deg)}
.src .body{padding-top:8px;font-size:13px;line-height:1.75;color:var(--t2);overflow-wrap:anywhere}
.src summary .cnt{color:var(--t3);font-weight:400}
/* 一条来源一行，序号挂在左边，长 URL 单独一行不挤正文 */
.src .body ol{margin:0;padding:0;list-style:none;counter-reset:s}
.src .body li{counter-increment:s;position:relative;padding-left:20px;margin-bottom:8px}
.src .body li:last-child{margin-bottom:0}
.src .body li::before{content:counter(s) ".";position:absolute;left:0;top:0;font-size:12px;color:var(--t3);font-variant-numeric:tabular-nums}
.src .body a.url{display:block;font-size:12px;color:var(--t3)}
.src .body a.url:hover{color:var(--brand-1)}
.empty{border:1px dashed var(--divider);border-radius:12px;padding:40px 24px;text-align:center;color:var(--t2);margin-top:24px}
.empty button{margin-top:12px;padding:7px 16px;border:1px solid var(--divider);border-radius:20px;font-weight:500;background:var(--bg-elv)}
.empty button:hover{border-color:var(--brand-1);color:var(--brand-1)}
.foot{margin-top:64px;padding-top:24px;border-top:1px solid var(--divider);color:var(--t3);font-size:13px;line-height:1.7}

@media (max-width:960px){
  :root{--nav-h:56px}
  .nav-in{padding:0 16px;gap:10px}
  .search{max-width:none}
  .search kbd{display:none}
  .menu-btn{display:grid}
  .sidebar{transform:translateX(-100%);transition:transform .25s;box-shadow:none;padding:24px 24px 96px;width:min(var(--side-w),86vw)}
  .sidebar.open{transform:none;box-shadow:0 8px 24px rgba(0,0,0,.2)}
  .backdrop{display:block;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:15;opacity:0;pointer-events:none;transition:opacity .25s}
  .backdrop.on{opacity:1;pointer-events:auto}
  .content{padding:calc(var(--nav-h) + 24px) 20px 96px}
  .doc-head h1{font-size:26px;line-height:34px}
  .card{padding:18px 16px 14px;border-radius:10px}
  .card-h h3{font-size:16px;line-height:24px}
  .card-h .idx{line-height:24px}
  .human{padding:9px 12px;font-size:14px;margin-bottom:12px}
  .rows{grid-template-columns:1fr;gap:4px}
  .rows .k{padding-top:6px}
  .rows .k:first-child{padding-top:0}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media print{
  .nav,.sidebar,.backdrop{display:none!important}
  .content{padding:0}
  .card{break-inside:avoid;border:1px solid #ddd}
  a{color:inherit;text-decoration:none}
}
"""

JS = r"""
(function(){
  var $=function(s,c){return (c||document).querySelector(s)};
  var $$=function(s,c){return Array.prototype.slice.call((c||document).querySelectorAll(s))};
  var root=document.documentElement;

  /* ---------- 主题 ---------- */
  var sw=$('#theme');
  function setTheme(d){
    root.classList.toggle('dark',d);
    try{localStorage.setItem('theme',d?'dark':'light')}catch(e){}
  }
  if(sw)sw.addEventListener('click',function(){setTheme(!root.classList.contains('dark'))});

  /* ---------- PDF 下载横幅 ---------- */
  var pdfbar=$('#pdfbar'), pdfbarX=$('#pdfbarX');
  if(pdfbar){
    var dismissed=false;
    try{dismissed=localStorage.getItem('pdfbar-dismissed')==='1'}catch(e){}
    if(!dismissed)pdfbar.hidden=false;
    if(pdfbarX)pdfbarX.addEventListener('click',function(){
      pdfbar.hidden=true;
      try{localStorage.setItem('pdfbar-dismissed','1')}catch(e){}
    });
  }

  /* ---------- 筛选状态 ---------- */
  var DIMS=['sec','ratio','grade','money','time','will'];
  var state={q:'',sec:new Set(),ratio:new Set(),grade:new Set(),money:new Set(),time:new Set(),will:new Set(),dispute:false,todo:false};
  var cards=$$('.card'), blocks=$$('.sec-block');
  var meta=cards.map(function(c){return{
    el:c, sec:c.dataset.sec, ratio:c.dataset.ratio, grade:c.dataset.grade,
    money:c.dataset.money, time:c.dataset.time, will:c.dataset.will,
    dispute:c.dataset.dispute==='1', todo:c.dataset.todo==='1', hay:c.dataset.t||'' };});

  function readUrl(){
    var p=new URLSearchParams(location.search);
    state.q=p.get('q')||'';
    for(const d of DIMS) state[d]=new Set((p.get(d)||'').split(',').filter(Boolean));
    state.dispute=p.get('dispute')==='1'; state.todo=p.get('todo')==='1';
  }
  function writeUrl(){
    var p=new URLSearchParams();
    if(state.q)p.set('q',state.q);
    for(const d of DIMS) if(state[d].size)p.set(d,[...state[d]].join(','));
    if(state.dispute)p.set('dispute','1'); if(state.todo)p.set('todo','1');
    var qs=p.toString();
    try{history.replaceState(null,'',(qs?'?'+qs:location.pathname)+location.hash)}catch(e){}
  }
  function syncControls(){
    var q=$('#q'); if(q&&q.value!==state.q)q.value=state.q;
    $$('[data-dim] [data-v]').forEach(function(b){
      var dim=b.parentElement.dataset.dim;
      b.setAttribute('aria-pressed',String(state[dim].has(b.dataset.v)));
    });
    var all=$('.sec-link.all');
    if(all)all.setAttribute('aria-pressed',String(state.sec.size===0));
    var fd=$('#f-dispute'),ft=$('#f-todo');
    if(fd)fd.checked=state.dispute; if(ft)ft.checked=state.todo;
  }

  /* ---------- 搜索高亮 ---------- */
  function clearMarks(){
    $$('mark').forEach(function(m){var p=m.parentNode;m.replaceWith(document.createTextNode(m.textContent));p.normalize();});
  }
  function hl(card,terms){
    if(!terms.length)return;
    var walker=document.createTreeWalker(card,NodeFilter.SHOW_TEXT,{acceptNode:function(n){
      if(!n.nodeValue.trim())return NodeFilter.FILTER_REJECT;
      var p=n.parentNode;
      if(p&&(p.nodeName==='MARK'||p.nodeName==='SCRIPT'||p.nodeName==='STYLE'))return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;}});
    var nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(function(n){
      var v=n.nodeValue,low=v.toLowerCase(),hit=false;
      for(var t of terms){if(low.indexOf(t)>=0){hit=true;break}}
      if(!hit)return;
      var re=new RegExp('('+terms.map(function(t){return t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')}).join('|')+')','gi');
      var out=v.replace(re,'\u0000$1\u0000');
      var frag=document.createDocumentFragment();
      out.split('\u0000').forEach(function(seg){
        var isHit=terms.some(function(t){return seg.toLowerCase()===t});
        frag.appendChild(isHit?Object.assign(document.createElement('mark'),{textContent:seg})
          :document.createTextNode(seg));});
      n.replaceWith(frag);});
  }

  /* ---------- 应用筛选 ---------- */
  function apply(){
    var terms=state.q.toLowerCase().split(/\s+/).filter(Boolean);
    var shown=0, perSec={};
    for(const m of meta){
      var ok=true, e=m;
      if(state.sec.size&&!state.sec.has(e.sec))ok=false;
      if(ok&&state.ratio.size&&!state.ratio.has(e.ratio))ok=false;
      if(ok&&state.grade.size&&!state.grade.has(e.grade))ok=false;
      if(ok&&state.money.size&&!state.money.has(e.money))ok=false;
      if(ok&&state.time.size&&!state.time.has(e.time))ok=false;
      if(ok&&state.will.size&&!state.will.has(e.will))ok=false;
      if(ok&&state.dispute&&!e.dispute)ok=false;
      if(ok&&state.todo&&!e.todo)ok=false;
      if(ok&&terms.length&&!terms.every(function(t){return e.hay.indexOf(t)>=0}))ok=false;
      if(m.el.hidden===ok)m.el.hidden=!ok;
      if(ok){shown++;perSec[e.sec]=(perSec[e.sec]||0)+1;clearMarks();hl(m.el,terms);}
    }
    for(const b of blocks){
      var n=perSec[b.dataset.sec]||0;
      b.hidden=n===0;
      var k=b.querySelector('.shown .k'); if(k)k.textContent=n;
    }
    $('#cnt').textContent=shown;
    $('#empty').hidden=shown!==0;
    syncControls(); writeUrl();
  }

  /* ---------- 事件 ---------- */
  var sb=$('#sidebar'),bd=$('#backdrop'),mb=$('#menu');
  function setMenu(on){sb.classList.toggle('open',on);bd.classList.toggle('on',on);mb.setAttribute('aria-expanded',String(on));}
  var toTop=function(){setMenu(false);scrollTo({top:0});};
  $$('[data-dim]').forEach(function(g){g.addEventListener('click',function(ev){
    var b=ev.target.closest('[data-v]'); if(!b)return;
    var dim=g.dataset.dim,v=b.dataset.v,set=state[dim];
    if(dim==='sec'){
      // 章节单选：再点一次已选中的不取消，要看全部点「全部章节」
      if(v==='')set.clear(); else{set.clear();set.add(v);}
    }else{
      set.has(v)?set.delete(v):set.add(v);
    }
    apply(); toTop();
  });});
  var fd=$('#f-dispute'),ft=$('#f-todo');
  if(fd)fd.addEventListener('change',function(e){state.dispute=e.target.checked;apply();toTop();});
  if(ft)ft.addEventListener('change',function(e){state.todo=e.target.checked;apply();toTop();});
  var tm;
  $('#q').addEventListener('input',function(e){
    clearTimeout(tm); tm=setTimeout(function(){state.q=e.target.value.trim();apply();},120);
  });
  var reset=function(){state.q='';for(const d of DIMS)state[d].clear();state.dispute=false;state.todo=false;apply();toTop();};
  $('#reset').addEventListener('click',reset);
  $('#reset2').addEventListener('click',reset);
  document.addEventListener('keydown',function(e){
    if(e.key==='/'&&!/INPUT|TEXTAREA/.test(document.activeElement.tagName)){e.preventDefault();$('#q').focus();}
    if(e.key==='Escape'){if(document.activeElement.id==='q')document.activeElement.blur();setMenu(false);}
  });
  mb.addEventListener('click',function(){setMenu(!sb.classList.contains('open'))});
  bd.addEventListener('click',function(){setMenu(false)});

  /* ---------- 交叉引用：点一下滚过去，目标条目闪一下 ---------- */
  document.addEventListener('click',function(e){
    var x=e.target.closest('.xref'); if(!x)return;
    var t=document.getElementById(x.dataset.go); if(!t)return;
    t.scrollIntoView({behavior:'smooth',block:'start'});
    t.classList.remove('flash'); void t.offsetWidth; t.classList.add('flash');
  });

  /* ---------- 启动 ---------- */
  readUrl(); apply();
})();
"""


def source_rev():
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h %ad", "--date=short"],
                             cwd=ROOT, capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


CHIP_GROUPS = [
    ("ratio", "性价比", "作者判断，与证据等级无关",
     [("极高", "极高"), ("高", "高"), ("一般", "一般")]),
    ("grade", "证据等级", "荟萃/RCT · 有研究 · 共识",
     [("A", "A 级"), ("B", "B 级"), ("C", "C 级")]),
    ("money", "花钱", "",
     [("0", "不花钱"), ("少", "少"), ("多", "多")]),
    ("time", "花时间", "",
     [("少", "顺手"), ("中", "几小时"), ("多", "每天占用")]),
    ("will", "要毅力", "",
     [("否", "不用"), ("些", "一点"), ("是", "很多")]),
]


def main():
    ap = argparse.ArgumentParser(description="渲染单文件饮食指南阅读页")
    ap.add_argument("sections", nargs="*", help="节号，如 1 2 16；缺省 all")
    ap.add_argument("-o", "--out", default=str(OUT_DEFAULT))
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    want_all = args.all or not args.sections or "all" in args.sections
    avail = avail_sections()
    if not avail:
        sys.exit("没找到 book/NN-*.md 正文文件。")
    if want_all:
        secs = avail
    else:
        secs = []
        for s in args.sections:
            if s.isdigit() and int(s) in avail:
                secs.append(int(s))
            else:
                print("跳过不存在的节：%s" % s, file=sys.stderr)

    data = [parse(find_file(n)) for n in secs]
    data = [s for s in data if s["entries"]]

    # 第一遍：收集全部条目锚点，交叉引用才有得跳
    targets = set()
    for s in data:
        for e in s["entries"]:
            targets.add("%d-%d" % (s["no"], e["no"]))

    stats = {"n": 0, "A": 0, "B": 0, "C": 0, "极高": 0, "高": 0, "一般": 0, "links": 0}
    blocks, sidebar_secs = [], []
    for s in data:
        cards = []
        for e in s["entries"]:
            t = parse_tags(e["tags_raw"])
            r = ratio_of(t)
            lv = level_of(e)
            stats["n"] += 1
            stats[lv] += 1
            stats[r] += 1
            stats["links"] += link_count(e["fields"].get("来源", ""))
            cards.append(render_entry(e, s["no"], targets))
        intro = "".join('<p class="intro">%s</p>' % inline(p)
                        for p in s["intro"])
        blocks.append(
            '<section class="sec-block" id="sec-%d" data-sec="%d">'
            '<div class="sec-h"><h2>%d. %s</h2>'
            '<span class="shown"><span class="k">%d</span> / %d</span></div>%s%s</section>'
            % (s["no"], s["no"], s["no"], esc(s["title"]),
               len(s["entries"]), len(s["entries"]), intro, "".join(cards)))
        sidebar_secs.append(
            '<button class="sec-link" data-v="%d" aria-pressed="false">'
            '<span>%d. %s</span><i>%d</i></button>'
            % (s["no"], s["no"], esc(s["title"]), len(s["entries"])))

    if not blocks:
        sys.exit("没有可渲染的正文。")

    total = stats["n"]
    n_secs = len(data)
    sidebar = (
        '<div class="group"><div class="gt">章节</div>'
        '<div class="sec-links" id="f-sec" data-dim="sec">'
        '<button class="sec-link all" data-v="" aria-pressed="true">'
        '<span>全部章节</span><i>%d</i></button>%s</div></div>' % (total, "".join(sidebar_secs))
    )
    for dim, gt, small, opts in CHIP_GROUPS:
        chips = "".join('<button class="chip" data-v="%s" aria-pressed="false">%s</button>'
                        % (esc(v), esc(label)) for v, label in opts)
        sidebar += ('<div class="group"><div class="gt">%s%s</div>'
                    '<div class="chips" data-dim="%s">%s</div></div>'
                    % (esc(gt), ('<small>%s</small>' % esc(small)) if small else "",
                       dim, chips))
    sidebar += ('<div class="group">'
                '<label class="toggle"><input type="checkbox" id="f-dispute"> 只看标了争议的</label>'
                '<label class="toggle"><input type="checkbox" id="f-todo"> 只看有待核实的</label>'
                '<button class="reset" id="reset">清空筛选</button></div>'
                '<div class="hint">'
                '<p>章节一次只看一个，其余组可多选。同一组多选是「或」，不同组之间是「且」。</p>'
                '<p>每节内按条目顺序排，检索不改变顺序。</p>'
                '<p>正文与标签来自仓库 book/ 下的 %d 个文件，改正文后跑 <code>python build.py</code> 即可更新本页。</p>'
                '</div>' % n_secs)

    rev = source_rev()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    desc = ("循证运动指南：%d 条建议，覆盖运动原理、最低有效剂量、心肺与力量训练、"
            "走路与 NEAT、运动零食、居家无器械、久坐打断、拉伸柔韧、时间管理、"
            "睡眠饮食协同、装备花费、指标追踪、常见误区与特殊人群。"
            "每条写明成本、收益、证据等级和原始出处。" % total)

    page = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s · %(sub)s</title>
<meta name="description" content="%(desc)s">
<meta name="keywords" content="运动,锻炼,健身,最低有效剂量,HIIT,力量训练,走路,NEAT,运动零食,久坐,循证,性价比,健康,心肺耐力">
<meta name="author" content="%(title)s">
<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">
<meta name="theme-color" content="#3451b2" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#1b1b1f" media="(prefers-color-scheme: dark)">
<link rel="icon" href="data:image/svg+xml,%%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%%3E%%3Crect width='64' height='64' rx='14' fill='%%233451b2'/%%3E%%3Cpath d='M17 33l10 11 20-24' fill='none' stroke='white' stroke-width='7' stroke-linecap='round' stroke-linejoin='round'/%%3E%%3C/svg%%3E">
<meta property="og:type" content="website">
<meta property="og:title" content="%(title)s">
<meta property="og:description" content="%(desc)s">
<meta property="og:locale" content="zh_CN">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Book","name":"%(title)s","inLanguage":"zh-CN",
"bookFormat":"https://schema.org/EBook","numberOfPages":%(n)d,
"abstract":"%(desc)s",
"about":["运动","锻炼","健身","健康","最低有效剂量","HIIT","力量训练"],"isAccessibleForFree":true,
"license":"https://creativecommons.org/licenses/by/4.0/"}
</script>
<script>(function(){try{var s=localStorage.getItem('theme');var d=s?s==='dark':matchMedia('(prefers-color-scheme: dark)').matches;if(d)document.documentElement.classList.add('dark')}catch(e){}})();</script>
<style>%(css)s</style>
</head>
<body>

<noscript>
  <div style="max-width:760px;margin:0 auto;padding:32px 20px;line-height:1.7">
    <h1>%(title)s</h1>
    <p>%(sub)s。全书 %(ns)s 节 %(n)d 条，每条写明成本、收益、证据等级和原始出处。</p>
    <p>本页的筛选功能需要 JavaScript。正文可直接阅读仓库 book/ 目录下的 Markdown 文件。</p>
  </div>
</noscript>

<header class="nav">
  <div class="nav-in">
    <button class="icon-btn menu-btn" id="menu" aria-label="打开筛选" aria-expanded="false"><svg viewBox="0 0 24 24"><path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/></svg></button>
    <a class="title" href="#"><span class="logo" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M6 12.5l4 4 8-9.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span>%(title)s</span></a>
    <label class="search">
      <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5" stroke-linecap="round"/></svg>
      <input id="q" type="search" placeholder="搜索条目" autocomplete="off" aria-label="搜索条目">
      <kbd>/</kbd>
    </label>
    <div class="nav-r">
      <a class="icon-btn" href="%(repo)s/blob/main/README.md" title="查看 README.md" aria-label="README"><svg viewBox="0 0 24 24"><path d="M6 2h9l5 5v15H6zm8 1.5V8h4.5zM8 12h8v1.5H8zm0 3.5h8V17H8z"/></svg></a>
      <a class="icon-btn" href="%(repo)s" target="_blank" rel="noopener" title="在 GitHub 上查看源仓库" aria-label="GitHub 仓库"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17.3 5.6 18.3 6 18.3 6c.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .3"/></svg></a>
      <button class="switch" id="theme" aria-label="切换深色模式" title="切换深色模式"><span class="knob"><svg class="sun" viewBox="0 0 24 24"><path d="M12 4a1 1 0 0 1 1 1v1a1 1 0 1 1-2 0V5a1 1 0 0 1 1-1zm0 13a1 1 0 0 1 1 1v1a1 1 0 1 1-2 0v-1a1 1 0 0 1 1-1zm8-6a1 1 0 1 1 0 2h-1a1 1 0 1 1 0-2zM5 11a1 1 0 1 1 0 2H4a1 1 0 1 1 0-2zm12.07-5.07a1 1 0 0 1 0 1.41l-.7.71a1 1 0 1 1-1.42-1.41l.71-.71a1 1 0 0 1 1.41 0zM8.05 16.95a1 1 0 0 1 0 1.41l-.7.71a1 1 0 1 1-1.42-1.41l.71-.71a1 1 0 0 1 1.41 0zm9.02 0l.7.71a1 1 0 1 1-1.41 1.41l-.71-.7a1 1 0 0 1 1.42-1.42zM6.34 5.93l.71.71a1 1 0 0 1-1.41 1.41l-.71-.7a1 1 0 0 1 1.41-1.42zM12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8z"/></svg><svg class="moon" viewBox="0 0 24 24"><path d="M12.1 22c-5.5 0-10-4.5-10-10 0-4.8 3.4-8.9 8-9.8.5-.1.9.4.7.9A8 8 0 0 0 20.9 13c.5-.2 1 .2.9.7-.9 4.7-5 8.3-9.7 8.3z"/></svg></span></button>
    </div>
  </div>
</header>

<div class="backdrop" id="backdrop"></div>
<aside class="sidebar" id="sidebar">
%(sidebar)s
</aside>

<main class="content">
  <div class="doc">
    <div class="pdfbar" id="pdfbar" hidden>
      <span class="ic" aria-hidden="true">📄</span>
      <span class="txt">这本书也出了 <b>PDF 版</b>（可打印、离线读、随手做批注）。想留一份慢慢看？</span>
      <a class="dl" href="%(pdf)s" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>点击下载 PDF</a>
      <button class="x" id="pdfbarX" aria-label="关闭提示">×</button>
    </div>
    <div class="doc-head">
      <h1>%(title)s</h1>
      <p>每一条都回答两个问题：花掉什么，换回什么。</p>
      <p>不用全做：这是一份按性价比排好的备选单，不是任务清单。挑走一两条就算数，剩下的需要时再回来查——想挑省力的，左边把「花钱」选「不花钱」、「要毅力」选「不用」，剩下的就是。正文里带虚线的「第 X 节第 Y 条」可以点，点一下就地滚到那条。</p>
      <div class="stat" aria-live="polite">当前显示 <b id="cnt">–</b> 条，共 <span id="tot">%(n)d</span> 条。每节内按性价比从高到低排，从每节前几条看起最划算。</div>
    </div>
    <div id="list">
      %(blocks)s
      <div class="empty" id="empty" hidden>
        没有匹配的条目。去掉一个筛选条件，或换个更短的关键词。
        <div><button id="reset2">清空筛选</button></div>
      </div>
    </div>
    <div class="foot">
      <b>%(title)s</b> · 共 <b>%(n)d</b> 条：证据等级 A <b>%(A)d</b> / B <b>%(B)d</b> / C <b>%(C)d</b>；性价比 极高 <b>%(r3)d</b> / 高 <b>%(r2)d</b> / 一般 <b>%(r1)d</b>；文献外链 <b>%(links)d</b> 条。<br>
      性价比档是作者按「收益量级 + 三项成本」算出的判断，不是证据；它与证据等级是两回事。「一般」不等于不该做。<br>
      书里的内容可能过时，也可能有错。真去看病、买药，以医生和药师的说法为准。发现写错了欢迎提 issue。<br>
      正文以 CC BY 4.0 发布（见 LICENSE），构建脚本与页面代码以 MIT 发布（见 LICENSE-CODE）。页面由 build.py 生成于 %(now)s。%(rev)s
    </div>
  </div>
</main>

<script>%(js)s</script>
</body>
</html>
""" % {
        "title": TITLE, "sub": SUBTITLE,
        "desc": desc, "n": total, "ns": n_secs,
        "A": stats["A"], "B": stats["B"], "C": stats["C"],
        "r3": stats["极高"], "r2": stats["高"], "r1": stats["一般"],
        "links": stats["links"], "css": CSS, "js": JS,
        "sidebar": sidebar, "blocks": "".join(blocks),
        "repo": REPO, "pdf": PDF_URL, "now": now,
        "rev": ("，正文版本 %s" % rev) if rev else "",
    }

    out = Path(args.out)
    out.write_text(page, encoding="utf-8")
    print("已生成 %s（%d 节，%d 条：A %d / B %d / C %d；性价比 极高 %d / 高 %d / 一般 %d；外链 %d 条）"
          % (out, n_secs, total, stats["A"], stats["B"], stats["C"],
             stats["极高"], stats["高"], stats["一般"], stats["links"]))


if __name__ == "__main__":
    main()
