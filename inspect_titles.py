"""
检查 Zilliz 上指定书目的 chunk 内容与文本质量（只读，不修改任何数据）
"""
import os
import re
import sys
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBS = os.path.join(_HERE, "_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.append(_LIBS)
os.chdir(_HERE)
sys.path.insert(0, _HERE)

from pymilvus import MilvusClient

URI = os.environ.get("ZILLIZ_URI", "").strip()
TOKEN = os.environ.get("ZILLIZ_TOKEN", "").strip()
NAME = "habsburg"

TITLES = [
    "The Economics of World War I",
    "Paris 1919: Six Months that Changed the World",
]

OUT = ["title", "chunk_index", "page_num", "chapter_title", "source_type",
       "language", "stance", "period", "region", "subfield", "doc_number", "text"]


def quality(txt):
    """粗略的文本质量指标"""
    if not txt:
        return {}
    n = len(txt)
    letters = sum(1 for c in txt if c.isalpha())
    digits = sum(1 for c in txt if c.isdigit())
    spaces = sum(1 for c in txt if c.isspace())
    other = n - letters - digits - spaces
    words = txt.split()
    single = sum(1 for w in words if len(w) == 1)
    # PDF 提取常见的断词残留：行尾 ¬ 或 词中 -\n
    broken = len(re.findall(r"\w+[¬-]\s*\n\s*\w+", txt)) + txt.count("¬")
    cjk = sum(1 for c in txt if "\u4e00" <= c <= "\u9fff")
    return {
        "chars": n,
        "letters": letters / n,
        "digits": digits / n,
        "spaces": spaces / n,
        "other": other / n,
        "words": len(words),
        "single_char_words": single / max(len(words), 1),
        "broken_hyphen": broken,
        "cjk": cjk,
    }


def main():
    cli = MilvusClient(uri=URI, token=TOKEN)
    total = cli.query(NAME, filter="", output_fields=["count(*)"])[0].get("count(*)")
    print("=" * 90)
    print("Zilliz 生产集合 habsburg  总块数 = %s" % total)
    print("=" * 90)

    for title in TITLES:
        print("\n" + "─" * 90)
        print("《%s》" % title)
        print("─" * 90)
        esc = title.replace("'", "\\'")
        rows = cli.query(NAME, filter="title == '%s'" % esc, output_fields=OUT,
                         limit=3000, consistency_level="Strong")
        print("  chunk 数: %d" % len(rows))
        if not rows:
            print("  （云端也没有这本书）")
            continue

        rows.sort(key=lambda r: r.get("chunk_index") or 0)
        pn = [r.get("page_num") for r in rows if isinstance(r.get("page_num"), int)]
        print("  chunk_index 范围: %s ~ %s" % (rows[0].get("chunk_index"), rows[-1].get("chunk_index")))
        print("  page_num      : %s ~ %s  (有页码的 %d 条)"
              % (min(pn) if pn else "-", max(pn) if pn else "-", len(pn)))
        r0 = rows[0]
        for k in ["source_type", "language", "stance", "period", "region", "subfield", "chapter_title"]:
            print("  %-14s: %r" % (k, r0.get(k)))

        # 质量统计
        qs = [quality(r.get("text") or "") for r in rows]
        qs = [q for q in qs if q]
        if qs:
            avg = lambda k: sum(q[k] for q in qs) / len(qs)
            print("\n  【文本质量】")
            print("    平均长度        %.0f 字符  (min %d / max %d)"
                  % (avg("chars"), min(q["chars"] for q in qs), max(q["chars"] for q in qs)))
            print("    字母占比        %.1f%%" % (avg("letters") * 100))
            print("    数字占比        %.1f%%" % (avg("digits") * 100))
            print("    空白占比        %.1f%%" % (avg("spaces") * 100))
            print("    其他符号占比    %.1f%%   ← 高说明 OCR/排版噪声多" % (avg("other") * 100))
            print("    单字符词占比    %.1f%%   ← 高说明断词严重" % (avg("single_char_words") * 100))
            print("    断词残留(¬/-)   %.1f 处/块" % avg("broken_hyphen"))
            print("    含中文字符      %.1f 个/块" % avg("cjk"))

        # 采样正文
        for label, idx in [("首块", 0), ("中段", len(rows) // 2), ("末块", len(rows) - 1)]:
            r = rows[idx]
            t = (r.get("text") or "").replace("\n", "⏎")
            print("\n  【%s · chunk_index=%s · page=%s】" % (label, r.get("chunk_index"), r.get("page_num")))
            print("    " + t[:420] + (" …" if len(t) > 420 else ""))

    print("\n" + "=" * 90)
    print("（只读检查，未修改任何数据）")
    print("=" * 90)
    return 0


if __name__ == "__main__":
    sys.exit(main())
