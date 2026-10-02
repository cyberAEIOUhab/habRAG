"""
pages/2_文献库管理.py —— 文献库管理页（本次新增，独立于 app.py）

功能：
  1. 概览：书目/片段统计 + 每本书的入库状态表（可按零片段书目过滤）
  2. 一致性检查：复用 db_check.py 的检查逻辑（缺失书/孤儿/重复/标签缺失/低chunk）
  3. 单书操作：重新入库（先删除该书现有chunk再重跑 ingest 流程）、仅删除chunks
     ⚠️ 这两个操作会真实修改 ChromaDB，请谨慎使用；重新入库会调用 embedding API。

启动方式不变：streamlit run app.py 后，左侧导航会出现本页。
"""

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

import corpus_lib
import db_check
import ingest

st.set_page_config(page_title="文献库管理", layout="wide")
st.title("🗄️ 文献库管理")
st.caption(f"原始文件目录（ingest 的 SOURCE_DIR）：`{ingest.SOURCE_DIR}`")


@st.cache_data(ttl=300, show_spinner=False)
def load_report():
    return db_check.check()


@st.cache_data(ttl=300, show_spinner=False)
def load_overview():
    books = corpus_lib.load_bookdata()
    counts = corpus_lib.get_book_counts()
    meta_lookup = corpus_lib.load_content_metadata()
    rows = []
    for b in books:
        t = b["title"]
        m = meta_lookup.get(t, {})
        # source_type 在book级条目直接有；chapter级条目取第一章的
        st_ = m.get("source_type")
        if st_ is None and m.get("chapters"):
            st_ = m["chapters"][0].get("source_type")
        rows.append({
            "书名": t,
            "chunks": counts.get(t, 0),
            "语言": b.get("language"),
            "年份": b.get("year"),
            "优先级": b.get("priority_tier"),
            "史料类型": st_,
            "立场": m.get("stance"),
            "扫描版": "是" if b.get("is_scanned") else "否",
        })
    df = pd.DataFrame(rows)
    return df, {b["title"]: b for b in books}, meta_lookup


def tail_log(n=40):
    try:
        with open(ingest.LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception as e:
        return f"无法读取日志：{e}"


df, book_lookup, meta_lookup = load_overview()
report = load_report()

# ============================================================
# 概览
# ============================================================
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("书目总数", len(df))
m2.metric("库内书名数", report["db_distinct_titles"])
m3.metric("片段总数", report["db_total_chunks"])
m4.metric("零片段书目", len(report["missing_in_db"]))
m5.metric("孤儿title", len(report["orphans_in_db"]))

st.markdown("### 📖 书目清单")
only_zero = st.checkbox("只看零片段书目（有书目但没入库）", key="admin_only_zero")
view = df[df["chunks"] == 0] if only_zero else df
st.dataframe(view, width="stretch", height=520,
             column_config={"书名": st.column_config.TextColumn(width="large")})

if only_zero and not view.empty:
    st.warning(
        "这些书有书目记录但库里没有任何片段。多数是无文字层的扫描版（扫描版=是），"
        "需要先 OCR 提取文字后才能用下方“重新入库”操作。"
    )

# ============================================================
# 一致性检查
# ============================================================
st.markdown("### 🧪 一致性检查")
st.caption("对比 bookdata.json / metadata.json / ChromaDB 三方。低chunk书不算问题，仅供人工确认。")
if st.button("运行一致性检查", key="admin_check"):
    report = load_report.clear()  # 清除缓存强制重查
    report = load_report()
    st.success("检查完成（结果见下方各小节）")

with st.expander(f"检查结果详情（点击展开）", expanded=True):
    st.markdown(f"**缺片段书目（{len(report['missing_in_db'])} 本）**")
    if report["missing_in_db"]:
        for b in report["missing_in_db"]:
            scan = "扫描版" if b["is_scanned"] else "非扫描"
            st.markdown(f"- ⚠️ 《{b['title']}》[{scan}, {b['page_count']}页] `{b['filename']}`")
    else:
        st.success("无")

    st.markdown(f"**孤儿title（库里有、bookdata无，{len(report['orphans_in_db'])} 个）**")
    if report["orphans_in_db"]:
        for t in report["orphans_in_db"]:
            st.markdown(f"- ⚠️ `{t}`")
    else:
        st.success("无")

    st.markdown(f"**bookdata 内部重复title（{len(report['duplicate_titles_in_bookdata'])} 个）**")
    if report["duplicate_titles_in_bookdata"]:
        for t in report["duplicate_titles_in_bookdata"]:
            st.markdown(f"- ⚠️ `{t}`")
    else:
        st.success("无")

    st.markdown(f"**metadata 与 bookdata 互相缺失（{len(report['bookdata_without_metadata']) + len(report['metadata_without_bookdata'])} 本）**")
    if report["bookdata_without_metadata"]:
        st.markdown("bookdata 有而 metadata 无：")
        for t in report["bookdata_without_metadata"]:
            st.markdown(f"- ⚠️ `{t}`")
    if report["metadata_without_bookdata"]:
        st.markdown("metadata 有而 bookdata 无：")
        for t in report["metadata_without_bookdata"]:
            st.markdown(f"- ⚠️ `{t}`")
    if not report["bookdata_without_metadata"] and not report["metadata_without_bookdata"]:
        st.success("无")

    st.markdown(f"**低chunk书目（1-19 个片段，{len(report['low_chunk_books'])} 本）**")
    if report["low_chunk_books"]:
        for b in report["low_chunk_books"]:
            st.markdown(f"- ℹ️ {b['chunks']} chunks · 《{b['title']}》")
    else:
        st.success("无")

# ============================================================
# 单书操作
# ============================================================
st.markdown("### 🛠️ 单书操作")
st.caption("以下操作会真实修改 ChromaDB：重新入库 = 删除该书现有chunk → 重跑 ingest（调用 embedding API，可能耗时数分钟）。")
sel_title = st.selectbox("选择书目", df["书名"].tolist(), key="admin_book_sel")

if sel_title:
    book = book_lookup[sel_title]
    n_chunks = int(df.loc[df["书名"] == sel_title, "chunks"].iloc[0])
    st.markdown(
        f"**《{sel_title}》** · {book.get('author')} · {book.get('year')} · "
        f"当前库内片段数：**{n_chunks}**"
    )
    with st.expander("bookdata.json 条目"):
        st.json(book)
    with st.expander("metadata.json 条目"):
        st.json(meta_lookup.get(sel_title, {"error": "无对应条目"}))

    confirmed = st.checkbox("我确认执行此操作（会真实修改数据库）", key="admin_confirm")

    op1, op2 = st.columns(2)
    if op1.button("🔄 重新入库该书（先删除现有chunks再重跑ingest）", key="admin_reingest",
                  disabled=not confirmed):
        collection = corpus_lib.get_collection()
        buf = io.StringIO()
        try:
            with st.spinner(f"正在重新入库《{sel_title}》..."):
                collection.delete(where={"title": sel_title})
                with contextlib.redirect_stdout(buf):
                    ok = ingest.process_book(book, meta_lookup, collection)
            if ok:
                st.success(f"《{sel_title}》重新入库完成。")
            else:
                st.error(f"《{sel_title}》入库失败（可能原文无文字层或文件缺失），详见下方日志。")
        except Exception as e:
            st.error(f"操作异常：{e}")
        st.code(buf.getvalue() or "（无输出）")
        st.caption("本次操作日志（含 ingest_log.txt 末尾）：")
        st.code(tail_log())
        st.cache_data.clear()

    if op2.button("🗑️ 仅删除该书的全部chunks", key="admin_delete", disabled=not confirmed):
        collection = corpus_lib.get_collection()
        try:
            before = len(collection.get(where={"title": sel_title}, include=[])["ids"])
            collection.delete(where={"title": sel_title})
            after = len(collection.get(where={"title": sel_title}, include=[])["ids"])
            st.success(f"已删除《{sel_title}》的 {before} 个chunk（删除后剩余 {after}）。")
        except Exception as e:
            st.error(f"删除失败：{e}")
        st.cache_data.clear()

st.divider()
st.caption("提示：重新入库对无文字层的扫描版无效（会输出“过滤后没有剩余内容”），"
           "此类书目需先 OCR。入库依赖 ingest.py 的 SOURCE_DIR 中的原始文件。")
