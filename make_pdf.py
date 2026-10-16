#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_pdf.py — 把 book/ 目录里的 Markdown 正文排版成 A4 PDF（HowToEatBetter.pdf）。

排版对齐参考项目 HowToLiveBetter 的 PDF：
封面卡片 + 带点线页码的目录 + 前言（问题表/怎么读/证据分级/示例条目）+
各节简介 + 13 节正文（每节另起一页，条目为悬挂缩进的项目符号列表，
链接蓝色可点），带页眉页脚（N / 总页数）和 PDF 书签。

依赖：reportlab（pip install reportlab）。零其他依赖，字体用系统自带中文字体。

用法：
    python make_pdf.py                # 输出 how-to-eat-better.pdf
    python make_pdf.py -o out.pdf    # 指定输出文件
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily, stringWidth
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    Table, TableStyle, NextPageTemplate, KeepTogether,
)
from reportlab.platypus.tableofcontents import TableOfContents

# 复用 build.py 的解析逻辑（模块导入即可，argparse 只在 __main__ 里跑）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as bookbuild  # noqa: E402

ROOT = Path(__file__).resolve().parent
TITLE = bookbuild.TITLE                      # 高性价比饮食指南
SUBTITLE = bookbuild.SUBTITLE                # 用最少的钱、时间和毅力，换回最多的健康
SITE = "https://kexin1409.github.io/how-to-exercise-better/"
REPO_URL = "https://github.com/kexin1409/how-to-exercise-better"

PAGE_W, PAGE_H = A4
M_L, M_R, M_T, M_B = 58, 58, 64, 52
BODY_W = PAGE_W - M_L - M_R

# 主题色（与 index.html 一致）
T1 = HexColor("#3c3c43")   # 正文
T2 = HexColor("#55555c")   # 次级
T3 = HexColor("#8e8e93")   # 弱化
BRAND = HexColor("#3451b2")
GREEN = HexColor("#18794e")
YELLOW = HexColor("#915930")
RED = HexColor("#b8272c")
DIVIDER = HexColor("#e2e2e3")

TOTAL = [0]  # 正文总页数（两遍构建时回填，用于页脚「N / 总数」）


# ---------------------------------------------------------------- 字体

def register_fonts():
    """按文件名模式在常见字体目录里搜索：Windows 用雅黑/宋体，Linux/macOS
    回退到 Noto CJK、文泉驿等，不依赖具体发行版的安装路径。"""
    roots = [
        "C:/Windows/Fonts",
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        str(Path.home() / ".fonts"),
        "/System/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
    ]
    cands = {
        "YH":  ["msyh.ttc", "msyh.ttf", "NotoSansCJK-Regular.ttc",
                "NotoSansCJK-Regular.*", "NotoSansCJK*.ttc", "wqy-microhei.ttc",
                "wqy*.ttc", "DroidSansFallbackFull.ttf"],
        "YHB": ["msyhbd.ttc", "NotoSansCJK-Bold.ttc", "NotoSansCJK-Bold.*",
                "NotoSansCJK*.ttc", "msyh.ttc"],
        "Song": ["simsun.ttc", "NotoSerifCJK-Regular.ttc", "NotoSerifCJK-Regular.*",
                 "NotoSerifCJK*.ttc", "NotoSansCJK-Regular.ttc", "NotoSansCJK*.ttc"],
        "Hei": ["simhei.ttf", "msyhbd.ttc", "NotoSansCJK-Bold.ttc",
                "NotoSansCJK-Bold.*", "NotoSansCJK*.ttc"],
    }
    got = {}       # name -> 显示用来源
    real = {}      # name -> 真实字体文件路径（注册回退时用，避免带后缀的展示串）
    for name, pats in cands.items():
        for pat in pats:
            for root in roots:
                rp = Path(root)
                if not rp.is_dir():
                    continue
                try:
                    hits = sorted(rp.rglob(pat))
                except OSError:
                    continue
                if not hits:
                    continue
                try:
                    pdfmetrics.registerFont(TTFont(name, str(hits[0]), subfontIndex=0))
                    got[name] = str(hits[0])
                    real[name] = str(hits[0])
                    break
                except Exception:
                    # reportlab 的 TTFont 不支持 CFF 轮廓（如 Noto CJK），换下一个候选
                    continue
            if name in got:
                break
        if name not in got:
            # 兜底：粗体/衬线找不到就复用已有字体文件（标题只是不更粗，不会报错）
            fallback = {"YHB": "YH", "Hei": "YHB", "Song": "YH"}.get(name)
            if fallback and fallback in real:
                pdfmetrics.registerFont(TTFont(name, real[fallback], subfontIndex=0))
                got[name] = real[fallback] + " (fallback)"
                real[name] = real[fallback]
            else:
                raise RuntimeError("找不到中文字体：%s（搜索目录：%s，模式：%s）"
                                   % (name, roots, pats))
    print("fonts:", got)
    # 宋体正文的 <b> 用黑体顶上
    registerFontFamily("Song", normal="Song", bold="Hei",
                       italic="Song", boldItalic="Hei")
    registerFontFamily("YH", normal="YH", bold="YHB",
                       italic="YH", boldItalic="YHB")


# ---------------------------------------------------------------- 数据

def load_book():
    """返回 (sections, stats)。sections 为 build.parse 的结果列表。"""
    secs, stats = [], {"n": 0, "A": 0, "B": 0, "C": 0, "极高": 0,
                       "高": 0, "一般": 0, "links": 0,
                       "争议": 0, "待核实": 0}
    for n in bookbuild.avail_sections():
        p = bookbuild.find_file(n)
        if not p:
            continue
        sec = bookbuild.parse(p)
        secs.append(sec)
        for e in sec["entries"]:
            t = bookbuild.parse_tags(e["tags_raw"])
            lv = bookbuild.level_of(e)
            stats["n"] += 1
            stats[lv] += 1
            stats[bookbuild.ratio_of(t)] += 1
            stats["links"] += bookbuild.link_count(e["fields"].get("来源", ""))
            note = e["fields"].get("备注", "")
            if note.startswith("争议"):
                stats["争议"] += 1
            if any("待核实" in e["fields"].get(k, "") or "TODO" in e["fields"].get(k, "")
                   for k in ("成本", "收益", "来源", "备注")):
                stats["待核实"] += 1
    return secs, stats


def git_commit():
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(ROOT), capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            return out.stdout.strip()[:7]
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------- 行内标记

def _anchor(url, text):
    u = url.replace("&", "&amp;")
    return '<a href="%s" color="#3451b2"><u>%s</u></a>' % (u, text)


def to_rl(s):
    """Markdown 行内标记 → reportlab 段落标记：链接、加粗。"""
    s = (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    # [text](url)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               lambda m: _anchor(m.group(2), m.group(1)), s)
    # <url>
    s = re.sub(r"&lt;(https?://[^&\s]+)&gt;",
               lambda m: _anchor(m.group(1), m.group(1)), s)
    # 裸 URL
    s = re.sub(r"(?<![\w\"=])(https?://[^\s，。；）】」\]]+)",
               lambda m: _anchor(m.group(1), m.group(1)), s)
    return s


# ---------------------------------------------------------------- 样式

def make_styles():
    S = {}
    S["SecTitle"] = ParagraphStyle(
        "SecTitle", fontName="YHB", fontSize=21, leading=30,
        textColor=HexColor("#1f1f24"), spaceBefore=0, spaceAfter=12,
        keepWithNext=1, wordWrap="CJK")
    S["FrontTitle"] = ParagraphStyle(
        "FrontTitle", parent=S["SecTitle"], spaceBefore=0)
    S["Intro"] = ParagraphStyle(
        "Intro", fontName="Song", fontSize=10.5, leading=18, textColor=T1,
        spaceBefore=0, spaceAfter=8, wordWrap="CJK", alignment=4)  # justify
    S["EntTitle"] = ParagraphStyle(
        "EntTitle", fontName="YHB", fontSize=12.5, leading=19,
        textColor=HexColor("#1f1f24"), spaceBefore=13, spaceAfter=5,
        keepWithNext=1, wordWrap="CJK")
    S["Field"] = ParagraphStyle(
        "Field", fontName="Song", fontSize=10.5, leading=17, textColor=T1,
        leftIndent=14, firstLineIndent=-14, spaceBefore=1.5, spaceAfter=1.5,
        wordWrap="CJK")
    S["TocTitle"] = ParagraphStyle(
        "TocTitle", fontName="YHB", fontSize=21, leading=30,
        textColor=HexColor("#1f1f24"), spaceAfter=16, wordWrap="CJK")
    S["TocLevel0"] = ParagraphStyle(
        "TocLevel0", fontName="Song", fontSize=10.5, leading=21,
        textColor=T1, wordWrap="CJK")
    S["TblCell"] = ParagraphStyle(
        "TblCell", fontName="Song", fontSize=10, leading=15.5, textColor=T1,
        wordWrap="CJK")
    S["TblHead"] = ParagraphStyle(
        "TblHead", fontName="YHB", fontSize=10, leading=15.5, textColor=T1,
        wordWrap="CJK")
    S["ExLine"] = ParagraphStyle(
        "ExLine", fontName="Song", fontSize=9, leading=14.5, textColor=T2,
        wordWrap="CJK")
    S["SecBrief"] = ParagraphStyle(
        "SecBrief", fontName="Song", fontSize=10.5, leading=18.5, textColor=T1,
        spaceBefore=4, spaceAfter=4, wordWrap="CJK")
    return S


# ---------------------------------------------------------------- 页面装饰

def _header_footer(canv, doc):
    page = doc.page
    canv.saveState()
    if page >= 3:  # 页眉（封面、目录页不带）
        canv.setFont("YH", 8.5)
        canv.setFillColor(T3)
        canv.drawString(M_L, PAGE_H - 42, TITLE)
        canv.drawRightString(PAGE_W - M_R, PAGE_H - 42, getattr(doc, "_cur_sec", "前言"))
        canv.setStrokeColor(DIVIDER)
        canv.setLineWidth(0.6)
        canv.line(M_L, PAGE_H - 48, PAGE_W - M_R, PAGE_H - 48)
    if page >= 3:  # 页脚：正文从第 1 页开始计数
        canv.setFont("YH", 8.5)
        canv.setFillColor(T3)
        canv.drawCentredString(PAGE_W / 2, 30, "%d / %d" % (page - 2, TOTAL[0]))
    canv.restoreState()


def _rounded_grad_card(canv, x, y, w, h, r=14):
    """浅色圆角卡片 + 顶部蓝绿双色条（封面）。"""
    canv.saveState()
    p = canv.beginPath()
    p.roundRect(x, y, w, h, r)
    canv.clipPath(p, stroke=0, fill=0)
    canv.setFillColor(HexColor("#f2f5fb"))
    canv.rect(x, y, w, h, stroke=0, fill=1)
    canv.restoreState()
    # 顶部 4px 条：左蓝右绿（只裁出顶部圆角区域）
    canv.saveState()
    p = canv.beginPath()
    p.roundRect(x, y + h - 14, w, 14, r)
    canv.clipPath(p, stroke=0, fill=0)
    canv.setFillColor(BRAND)
    canv.rect(x, y + h - 4, w / 2, 4, stroke=0, fill=1)
    canv.setFillColor(GREEN)
    canv.rect(x + w / 2, y + h - 4, w / 2, 4, stroke=0, fill=1)
    canv.restoreState()


def _pill(canv, x, y, text, font, size, fg, bg, pad=9, h=21):
    w = stringWidth(text, font, size) + pad * 2
    canv.setFillColor(bg)
    canv.roundRect(x, y, w, h, h / 2, stroke=0, fill=1)
    canv.setFillColor(fg)
    canv.setFont(font, size)
    canv.drawString(x + pad, y + (h - size) / 2 + 1, text)
    return w


def draw_cover(canv, doc, secs, stats):
    canv.saveState()
    canv.setFillColor(white)
    canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    cx, cy, cw, ch = 58, 268, PAGE_W - 116, 388
    _rounded_grad_card(canv, cx, cy, cw, ch)

    # 徽章行：蓝底对勾（用线画，雅黑没有 ✓ 字形）+ 站名
    bx, by = cx + 34, cy + ch - 66
    canv.setFillColor(BRAND)
    canv.roundRect(bx, by, 18, 18, 4, stroke=0, fill=1)
    canv.setStrokeColor(white)
    canv.setLineWidth(2)
    canv.setLineCap(1)
    p = canv.beginPath()
    p.moveTo(bx + 4.5, by + 9)
    p.lineTo(bx + 7.8, by + 5.5)
    p.lineTo(bx + 13.5, by + 12.5)
    canv.drawPath(p, stroke=1, fill=0)
    canv.setFillColor(HexColor("#1f1f24"))
    canv.setFont("YHB", 11.5)
    canv.drawString(bx + 26, by + 4.5, TITLE)

    # 主标题（两行，部分着色）；整行宽度自动缩字号，确保不溢出卡片
    line1 = "没时间去健身房，"
    line2a, line2b = "用最少的", "时间和毅力，换回最多的健康"
    size = 27
    while size > 16 and stringWidth(line2a + line2b, "YHB", size) > cw - 68:
        size -= 0.5
    canv.setFont("YHB", size)
    canv.setFillColor(HexColor("#1a1a1e"))
    canv.drawString(cx + 34, by - 56, line1)
    y2 = by - 96
    canv.drawString(cx + 34, y2, line2a)
    w1 = stringWidth(line2a, "YHB", size)
    canv.setFillColor(BRAND)
    canv.drawString(cx + 34 + w1, y2, line2b)

    # 副标题：各节主题串
    short = " · ".join(_short_title(s["title"]) for s in secs)
    canv.setFont("Song", 10)
    canv.setFillColor(T2)
    canv.drawString(cx + 34, y2 - 34, _fit(short, "Song", 10, cw - 68))

    # 统计胶囊
    py = y2 - 72
    px = cx + 34
    px += _pill(canv, px, py, "%d 条建议" % stats["n"], "YHB", 9.5,
                BRAND, HexColor("#e5eaf8")) + 10
    px += _pill(canv, px, py, "A 级证据 %d 条" % stats["A"], "YHB", 9.5,
                GREEN, HexColor("#e2f2ea")) + 10
    px += _pill(canv, px, py, "%d 条原始文献链接" % stats["links"], "YH", 9.5,
                HexColor("#565a5f"), HexColor("#ececef")) + 10
    _pill(canv, px, py, "可按性价比筛选", "YH", 9.5,
          HexColor("#565a5f"), HexColor("#ececef"))

    canv.restoreState()

    # 卡片下方：简介段落（居中）
    desc = ("讲运动到底能换回什么，讲没时间去健身房的人怎么用最低有效剂量把健康要回来，"
            "讲怎么靠走路、爬楼、居家自重训练、HIIT 和力量训练把心肺和肌肉练到位，"
            "讲久坐怎么打断、NEAT 怎么帮你偷偷多消耗，讲怎么把运动塞进忙碌的一天，"
            "讲装备怎么花最少的钱、数据怎么别被它绑架，也讲出差、带娃、膝盖不好和老年人的"
            "特殊做法。%d 条建议，每条写明花掉什么、换回什么、证据有多硬，"
            "来源只引期刊论文和官方文件。不用全做：这是按性价比排好的备选单，不是任务清单"
            "——挑走一两条就算数。" % stats["n"])
    canv.setFont("Song", 10.5)
    canv.setFillColor(T1)
    lines = _wrap_center(desc, "Song", 10.5, 424)
    y = 236
    for ln in lines:
        canv.drawCentredString(PAGE_W / 2, y, ln)
        y -= 18

    # 页脚信息
    now = datetime.datetime.now()
    commit = git_commit()
    y = 128
    canv.setFont("Song", 9)
    canv.setFillColor(T3)
    line1 = "生成于 %s（北京时间）" % now.strftime("%Y-%m-%d %H:%M")
    if commit:
        line1 += "　·　正文提交 " + commit
    canv.drawCentredString(PAGE_W / 2, y, line1)
    canv.setFillColor(BRAND)
    for i, ln in enumerate([
        "正文以在线版为准：%s" % SITE,
        "在线检索与本 PDF 的最新版都在 %s" % REPO_URL,
    ]):
        canv.drawCentredString(PAGE_W / 2, y - 16 - i * 15, ln)
        # 链接注释
        w = stringWidth(ln, "Song", 9)
        canv.linkURL(ln.split("：", 1)[1] if "：" in ln else ln,
                     (PAGE_W / 2 - w / 2, y - 18 - i * 15, w, 11), relative=0)


def _short_title(t):
    return t.split("：", 1)[0].strip()


def _fit(text, font, size, maxw):
    """超宽时截断加省略号。"""
    while text and stringWidth(text, font, size) > maxw:
        text = text[:-2] + "…"
    return text


def _wrap_center(text, font, size, maxw):
    from reportlab.pdfbase.pdfmetrics import stringWidth as sw
    words, lines, cur = text, [], ""
    i = 0
    while i < len(words):
        c = words[i]
        if sw(cur + c, font, size) > maxw and cur:
            lines.append(cur)
            cur = ""
        cur += c
        i += 1
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------- 文档模板

class BookDoc(BaseDocTemplate):
    def afterFlowable(self, f):
        if not isinstance(f, Paragraph):
            return
        st = f.style.name
        if st in ("SecTitle", "FrontTitle"):
            text = f.getPlainText()
            key = getattr(f, "_bm_key", None) or ("h-" + re.sub(r"\W+", "", text)[:24])
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, 0, 0)
            self._cur_sec = _short_title(text)
            if st == "SecTitle" or text in ("前言", "各节简介"):
                self.notify("TOCEntry", (0, text, max(1, self.page - 2), key))
        elif st == "EntTitle":
            key = getattr(f, "_bm_key", None)
            if key:
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(f.getPlainText(), key, 1, 0)


# ---------------------------------------------------------------- 故事

def sec_brief(sec):
    intro = " ".join(sec["intro"])
    m = re.search(r"口径[：:]\s*([^。]+)。?", intro)
    first = intro.split("。")[0].strip()
    if not first.endswith("。"):
        first += "。"
    brief = "%d. %s：%s" % (sec["no"], sec["title"], first)
    if m:
        brief += "口径：%s。" % m.group(1).strip()
    return brief


def q_table_rows(secs):
    return [
        ("到底是谁说「必须练满 1 小时、必须去健身房」，最低有效剂量是什么？", 1),
        ("剂量-反应曲线长什么样，拐点（性价比最高点）落在哪？", 2),
        ("心肺耐力的最低剂量是多少，周末突击（周末战士）管不管用？", 3),
        ("高强度间歇 HIIT 真的 15 分钟顶 1 小时吗，怎么安全地做？", 4),
        ("力量训练的最低剂量是多少，在家练能不能替代健身房？", 5),
        ("走路和 NEAT 为什么是最容易坚持的「运动药」？", 6),
        ("运动零食（exercise snacks）是什么，怎么塞进碎片时间？", 7),
        ("居家无器械训练怎么安排，一个房间能不能练全身？", 8),
        ("久坐到底多伤，每 30 分钟起来动一动有用吗？", 9),
        ("拉伸和灵活性需要练多少，动态热身和静态拉伸分别怎么做？", 10),
        ("怎么把运动塞进忙碌的一天，习惯怎么才不掉链子？", 11),
        ("睡眠、饮食怎么和运动配合，让效果翻倍而不是互相抵消？", 12),
        ("装备和花费怎么花最少的钱，哪些钱根本不用花？", 13),
        ("步数、心率、体重这些指标看什么，怎么别被数据绑架？", 14),
        ("流传最广的运动说法里，哪些是错的？", 15),
        ("出差、带娃、办公室、膝盖不好、老年人分别怎么办？", 16),
    ]


def _table(data, col_widths, styles):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, HexColor("#c9c9cd")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, DIVIDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def make_story(secs, stats, S):
    story = []

    # ---- 封面（由 onPage 绘制，不放流式内容）
    story.append(NextPageTemplate("main"))
    story.append(PageBreak())

    # ---- 目录
    story.append(Paragraph("目录", S["TocTitle"]))
    toc = TableOfContents()
    toc.levelStyles = [S["TocLevel0"]]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(PageBreak())

    # ---- 前言
    story.append(Paragraph("前言", S["FrontTitle"]))
    story.append(Paragraph(
        "讲运动到底能换回什么，讲没时间去健身房的人怎么用最低有效剂量把健康要回来，"
        "讲怎么靠走路、爬楼、居家自重训练、HIIT 和力量训练把心肺和肌肉练到位，"
        "讲久坐怎么打断、NEAT 怎么帮你偷偷多消耗，讲怎么把运动塞进忙碌的一天，"
        "讲装备怎么花最少的钱、数据怎么别被它绑架，也讲出差、带娃、膝盖不好和老年人的"
        "特殊做法。%d 条建议，每条写明花掉什么、换回什么、证据有多硬，"
        "来源只引期刊论文和官方文件。不用全做：这是按性价比排好的备选单，不是任务清单"
        "——挑走一两条就算数。" % stats["n"], S["Intro"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("这本书想回答的问题", S["EntTitle"]))
    rows = [[Paragraph("问题", S["TblHead"]), Paragraph("去哪看", S["TblHead"])]]
    for q, n in q_table_rows(secs):
        sec = next(s for s in secs if s["no"] == n)
        rows.append([Paragraph(q, S["TblCell"]),
                     Paragraph(to_rl("%d. %s" % (n, _short_title(sec["title"]))), S["TblCell"])])
    story.append(_table(rows, [BODY_W - 150, 150], S))
    story.append(Spacer(1, 10))

    story.append(Paragraph("怎么读", S["EntTitle"]))
    for b in [
        "不用全做：这是一份按性价比排好的备选单，不是任务清单。挑走一两条就算数，剩下的放着，需要时再回来查。",
        "想按条件挑：打开在线检索页（%s），可以按关键词、章节、证据等级来筛，也可以按「花不花钱、"
        "花多少时间、要不要毅力」这三样筛，几个条件能叠着用。页面上的内容直接取自 book/ 目录里的正文，正文一改，页面跟着改。" % SITE,
        "条目之间会互相指路（「见第 4 节第 7 条」这种）：在线检索页里点一下就能跳过去。在这份 PDF 里点不动，"
        "但每处指路都写明了指向哪一条，不翻过去也知道说的是什么。",
        "想按顺序读：每节内的条目按性价比从高到低排列，从每节前几条开始看就行。",
        "只想看结论最硬的：在在线检索页里勾选证据等级 A，只留下有具体数字、来自荟萃分析或大型试验的 %d 条。" % stats["A"],
        "只想看最值得做的：勾选性价比「极高」，得到 %d 条几乎不花钱、不花时间、不太需要毅力，收益又落在最大一档的条目。" % stats["极高"],
        "想让 AI 帮你查：仓库里带了正文，把问题原样丢给能读文件的 AI 助手，让它先查相关条目、再按书里的口径回答，并注明出自第几节第几条。查不到就说查不到，不自己编数字。",
    ]:
        story.append(Paragraph("• " + b, S["Field"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("证据分级", S["EntTitle"]))
    rows = [[Paragraph("等级", S["TblHead"]), Paragraph("含义", S["TblHead"])]]
    for lv, mean in [
        ("A", "有具体数字可查，出处是多项研究合并起来的荟萃分析、跟踪很多人很多年的大型队列，"
              "或者随机分组的试验（RCT），能说出降了多少（HR、RR、下降百分比）"),
        ("B", "有研究支持，但说不出一个确切数字；或者只有小样本、单独一项研究撑着"),
        ("C", "作者自己的经验，或者大家公认的做法，没有直接的研究文献"),
    ]:
        rows.append([Paragraph(lv, S["TblHead"]), Paragraph(mean, S["TblCell"])])
    story.append(_table(rows, [46, BODY_W - 46], S))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "全书 %d 条中 A 级 %d 条、B 级 %d 条、C 级 %d 条，另有 %d 条标注了争议、%d 条含待核实内容。"
        "有争议的条目会在备注里列出反方证据。所有来源只引原始文献（期刊论文附 DOI 或 PubMed 链接，"
        "或 WHO/CDC/国家卫健委等官方机构报告），不引二手转述。"
        % (stats["n"], stats["A"], stats["B"], stats["C"], stats["争议"], stats["待核实"]),
        S["Intro"]))

    story.append(Paragraph("性价比档", S["EntTitle"]))
    story.append(Paragraph(
        "证据等级只回答「这个数字可不可信」，不回答「这件事值不值得做」。所以每条还另外标了两样："
        "收益量级（好处有多大：大/中/小）和口径（换回的是哪一类东西：慢病/死亡率/时间等）。"
        "拿收益量级加上三项成本（钱、时间、毅力），合出一个性价比档：几乎不花什么成本、换回的好处又大的，"
        "是「极高」；其次「高」，再次「一般」。不同口径之间不做比较——「死亡率低 12%%」和「每天省 10 分钟」"
        "不在一把尺子上。全书 %d 条中性价比极高 %d 条、高 %d 条、一般 %d 条。"
        % (stats["n"], stats["极高"], stats["高"], stats["一般"]), S["Intro"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("每条建议长这样", S["EntTitle"]))
    ex_sec = next(s for s in secs if s["no"] == 4)
    ex = next(e for e in ex_sec["entries"] if e["no"] == 2)
    f = ex["fields"]
    t = bookbuild.parse_tags(ex["tags_raw"])
    ex_lines = [
        "### %d. %s" % (ex["no"], ex["title"]),
        "<!-- 成本标签: %s -->" % ex["tags_raw"],
    ]
    for k in ("成本", "说人话", "收益", "证据等级", "来源", "备注"):
        if f.get(k):
            ex_lines.append("- %s：%s" % (k, f[k]))
    ex_tbl = Table([[ [Paragraph(to_rl(l), S["ExLine"]) for l in ex_lines] ]],
                   colWidths=[BODY_W])
    ex_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#f6f6f7")),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(ex_tbl)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "「说人话」把「收益」栏里研究里的写法，翻成「爬楼不喘了、腰不酸了」这样的日常说法。"
        "它只用「收益」栏已经写到的内容，不添新数字，只看这一行就够拿主意。"
        "「收益」栏里原样留着全部数字，想自己核对就看那一栏。", S["Intro"]))
    story.append(PageBreak())

    # ---- 各节简介
    story.append(Paragraph("各节简介", S["FrontTitle"]))
    for sec in secs:
        story.append(Paragraph(to_rl(sec_brief(sec)), S["SecBrief"]))
    story.append(PageBreak())

    # ---- 正文各节
    for sec in secs:
        story.append(Paragraph("%d. %s" % (sec["no"], sec["title"]), S["SecTitle"]))
        for para in sec["intro"]:
            story.append(Paragraph(to_rl(para), S["Intro"]))
        story.append(Spacer(1, 2))
        for e in sec["entries"]:
            f = e["fields"]
            tp = Paragraph("%d. %s" % (e["no"], e["title"]), S["EntTitle"])
            tp._bm_key = "e-%d-%d" % (sec["no"], e["no"])
            block = [tp]
            for k in ("成本", "说人话", "收益", "证据等级", "来源", "备注"):
                if f.get(k):
                    block.append(Paragraph("• %s：%s" % (k, to_rl(f[k])), S["Field"]))
            story.append(KeepTogether(block))
        if sec["no"] != secs[-1]["no"]:
            story.append(PageBreak())
    return story


# ---------------------------------------------------------------- 构建

def _on_cover(canv, doc):
    draw_cover(canv, doc, doc._secs, doc._stats)


def build_once(out_path, secs, stats, S):
    doc = BookDoc(str(out_path), pagesize=A4,
                  leftMargin=M_L, rightMargin=M_R, topMargin=M_T, bottomMargin=M_B,
                  title=TITLE, author="kexin1409",
                  subject=SUBTITLE, creator="make_pdf.py")
    doc._cur_sec = "目录"
    doc._secs, doc._stats = secs, stats
    frame_cover = Frame(M_L, M_B, BODY_W, PAGE_H - M_T - M_B, id="cover")
    frame_main = Frame(M_L, M_B, BODY_W, PAGE_H - M_T - M_B, id="main")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame_cover], onPage=_on_cover),
        PageTemplate(id="main", frames=[frame_main], onPageEnd=_header_footer),
    ])
    story = make_story(secs, stats, S)
    doc.multiBuild(story)
    return doc.page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=str(ROOT / "how-to-exercise-better.pdf"))
    args = ap.parse_args()

    register_fonts()
    secs, stats = load_book()
    S = make_styles()

    # 第一遍：数出正文总页数；第二遍：回填后正式输出
    tmp = ROOT / "_pdf_pass1.pdf"
    n = build_once(tmp, secs, stats, S)
    TOTAL[0] = max(1, n - 2)
    tmp.unlink(missing_ok=True)
    build_once(args.out, secs, stats, S)

    print("done: %s" % args.out)
    print("sections=%d entries=%d A=%d B=%d C=%d 极高=%d 高=%d 一般=%d links=%d "
          "争议=%d 待核实=%d 正文页数=%d"
          % (len(secs), stats["n"], stats["A"], stats["B"], stats["C"],
             stats["极高"], stats["高"], stats["一般"], stats["links"],
             stats["争议"], stats["待核实"], TOTAL[0]))


if __name__ == "__main__":
    main()
