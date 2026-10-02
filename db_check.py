"""
db_check.py —— 语料库一致性检查脚本（本次新增）

对比三个数据源：
  bookdata.json    —— 书目权威信息（136条）
  metadata.json    —— 内容级标签（stance/subfield/period/region/source_type）
  ChromaDB "habsburg" —— 实际入库的chunk（按title聚合）

报告内容：
  1. 总体统计
  2. 有书目但库内零chunk的书（通常是无文字层的扫描版，需要先OCR）
  3. 库内有chunk但bookdata.json中已不存在的孤儿title
  4. bookdata.json 内部的重复title
  5. metadata.json 与 bookdata.json 互相缺失的书
  6. chunk数异常低（1-19）的书（可能是短篇/摘录，或提取失败）

用法：
  python db_check.py                   # 打印文本报告
  python db_check.py --json out.json   # 同时把报告写成JSON文件

退出码：发现问题（缺失/孤儿/重复/互相缺失）时为1，一切正常为0，便于脚本化调用。
（低chunk书不算"问题"，因为库里本来就有不少合法短篇/书评/论文。）
"""

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import corpus_lib

LOW_CHUNK_THRESHOLD = 20  # 低于该chunk数会在报告里列出供人工判断


def check():
    """执行一致性检查，返回结构化报告字典。"""
    bookdata = corpus_lib.load_bookdata()
    meta_lookup = corpus_lib.load_content_metadata()
    counts = corpus_lib.get_book_counts()

    bookdata_titles = [b["title"] for b in bookdata]
    lookup = {b["title"]: b for b in bookdata}

    # 有书目但库内零chunk的书
    missing_in_db = [
        {
            "title": b["title"],
            "filename": b.get("filename"),
            "is_scanned": b.get("is_scanned"),
            "page_count": b.get("page_count"),
        }
        for b in bookdata
        if counts.get(b["title"], 0) == 0
    ]

    # 库里有chunk但bookdata里没有的书名（孤儿）
    orphans_in_db = sorted(t for t in counts if t not in lookup)

    # bookdata内部重复
    dup_counter = Counter(bookdata_titles)
    duplicate_titles = sorted(t for t, n in dup_counter.items() if n > 1)

    # metadata与bookdata互相缺失
    missing_meta = sorted(t for t in bookdata_titles if t not in meta_lookup)
    orphan_meta = sorted(t for t in meta_lookup if t not in lookup)

    # chunk数异常低（不含零chunk的，零chunk已在missing_in_db列出）
    low_chunk_books = sorted(
        ({"title": t, "chunks": n} for t, n in counts.items() if 0 < n < LOW_CHUNK_THRESHOLD),
        key=lambda x: x["chunks"],
    )

    return {
        "bookdata_books": len(bookdata),
        "db_distinct_titles": len(counts),
        "db_total_chunks": sum(counts.values()),
        "missing_in_db": missing_in_db,
        "orphans_in_db": orphans_in_db,
        "duplicate_titles_in_bookdata": duplicate_titles,
        "bookdata_without_metadata": missing_meta,
        "metadata_without_bookdata": orphan_meta,
        "low_chunk_books": low_chunk_books,
    }


def _problem_count(report):
    """统计"问题"数量（用于退出码）。低chunk书不算问题。"""
    return (
        len(report["missing_in_db"])
        + len(report["orphans_in_db"])
        + len(report["duplicate_titles_in_bookdata"])
        + len(report["bookdata_without_metadata"])
        + len(report["metadata_without_bookdata"])
    )


def _print_report(report):
    line = "=" * 70
    print(line)
    print("habRAG 语料库一致性检查")
    print(line)
    print(f"bookdata.json 书目总数      : {report['bookdata_books']}")
    print(f"ChromaDB 内 distinct title : {report['db_distinct_titles']}")
    print(f"ChromaDB chunk 总数        : {report['db_total_chunks']}")

    print(f"\n[1] 有书目但库内零chunk的书（{len(report['missing_in_db'])} 本）")
    if not report["missing_in_db"]:
        print("  ✅ 无")
    for b in report["missing_in_db"]:
        scan = "扫描版" if b["is_scanned"] else "非扫描"
        print(f"  ⚠️ 《{b['title']}》 [{scan}, {b['page_count']}页]")
        print(f"       文件：{b['filename']}")
        if b["is_scanned"]:
            print("       → 无文字层扫描版，需要先OCR才能入库")

    print(f"\n[2] 库内有chunk但bookdata.json中已不存在的孤儿title（{len(report['orphans_in_db'])} 个）")
    if not report["orphans_in_db"]:
        print("  ✅ 无")
    for t in report["orphans_in_db"]:
        print(f"  ⚠️ {t}")

    print(f"\n[3] bookdata.json 内部重复title（{len(report['duplicate_titles_in_bookdata'])} 个）")
    if not report["duplicate_titles_in_bookdata"]:
        print("  ✅ 无")
    for t in report["duplicate_titles_in_bookdata"]:
        print(f"  ⚠️ {t}")

    print(f"\n[4] bookdata.json 有但 metadata.json 无内容标签（{len(report['bookdata_without_metadata'])} 本）")
    if not report["bookdata_without_metadata"]:
        print("  ✅ 无")
    for t in report["bookdata_without_metadata"]:
        print(f"  ⚠️ {t}")

    print(f"\n[5] metadata.json 有但 bookdata.json 无的书（{len(report['metadata_without_bookdata'])} 本）")
    if not report["metadata_without_bookdata"]:
        print("  ✅ 无")
    for t in report["metadata_without_bookdata"]:
        print(f"  ⚠️ {t}")

    print(f"\n[6] chunk数异常低（1-{LOW_CHUNK_THRESHOLD - 1}）的书（{len(report['low_chunk_books'])} 本，供人工判断）")
    if not report["low_chunk_books"]:
        print("  ✅ 无")
    for b in report["low_chunk_books"]:
        print(f"  ℹ️  {b['chunks']:>4} chunks · {b['title']}")

    print(line)
    n = _problem_count(report)
    if n == 0:
        print("结论：✅ 未发现问题（低chunk书请人工确认）")
    else:
        print(f"结论：⚠️ 发现 {n} 处问题（见上述 [1]-[5] 小节）")
    print(line)


def main():
    parser = argparse.ArgumentParser(description="habRAG 语料库一致性检查")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="把结构化报告写入指定JSON文件")
    args = parser.parse_args()

    report = check()
    _print_report(report)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n结构化报告已写入：{args.json_path}")

    sys.exit(1 if _problem_count(report) else 0)


if __name__ == "__main__":
    main()
