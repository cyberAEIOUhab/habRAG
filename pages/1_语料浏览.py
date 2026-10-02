"""
pages/1_语料浏览.py —— 语料浏览页（本次新增，独立于 app.py）

功能：按书目/章节/页码直接翻阅已入库的原始片段（chunk），不经过语义检索与生成。
- 左侧选择书目（含片段数）、章节、页内全文过滤
- 右侧显示书目元数据与逐片段内容（PDF页码、章节、立场、学科视角等标注）

启动方式不变：streamlit run app.py 后，左侧导航会出现本页。
说明：显示的页码是 PDF 页码（非印刷页码），项目已知问题。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

import corpus_lib

st.set_page_config(page_title="语料浏览", layout="wide")
st.title("📚 语料浏览")
st.caption("直接翻阅已入库的原始片段（chunk），不经过语义检索与生成。页码为 PDF 页码（非印刷页码）。")

PAGE_SIZE = 15  # 每页显示的片段数


@st.cache_data(ttl=600, show_spinner=False)
def load_book_list():
    counts = corpus_lib.get_book_counts()
    return sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))


@st.cache_data(ttl=600, show_spinner=False)
def load_book_chunks(title):
    return corpus_lib.get_chunks_for_book(title)


@st.cache_data(ttl=600, show_spinner=False)
def load_bookdata_lookup():
    return corpus_lib.get_bookdata_lookup()


@st.cache_data(ttl=600, show_spinner=False)
def load_chapters(title):
    return corpus_lib.get_chapters_for_book(title)


def reset_page():
    st.session_state.browse_page = 0


books = load_book_list()
bookdata = load_bookdata_lookup()
titles = [t for t, _ in books]
labels = [f"{t}（{n} 片段）" for t, n in books]

with st.sidebar:
    st.header("选择书目")
    if not titles:
        st.warning("库中没有可浏览的书目。")
        st.stop()
    sel_label = st.selectbox("书目（按片段数排序）", labels, key="browse_book", on_change=reset_page)
    sel_title = titles[labels.index(sel_label)]

    chunks = load_book_chunks(sel_title)
    chapters = load_chapters(sel_title)
    chapter_opts = ["全部章节"] + chapters
    sel_chapter = st.selectbox("章节", chapter_opts, key="browse_chapter", on_change=reset_page)

    search_term = st.text_input("全文过滤（在该书内搜索）", key="browse_search", on_change=reset_page)

    st.caption("提示：在管理页可查看/重跑入库；本书以外还有书目未入库（扫描版）的情况见管理页。")
    if st.button("重置本页修正显示"):
        st.session_state.browse_fixed = {}
        st.rerun()

# ---- 书目元数据 ----
meta = bookdata.get(sel_title, {})
col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
col1.markdown(f"### 《{sel_title}》")
col2.metric("片段数", len(chunks))
col3.metric("页数", meta.get("page_count") or "-")
col4.metric("语言", meta.get("language") or "-")
st.markdown(
    f"**{meta.get('author', '未知')}** · {meta.get('year', '未知年份')} · "
    f"出版社：{meta.get('publisher') or '未知'}"
)
with st.expander("书目简介（来自 bookdata.json）"):
    st.write(meta.get("description") or "（无简介）")

# ---- 过滤 ----
filtered = []
for c in chunks:
    if sel_chapter != "全部章节" and c.get("chapter_title") != sel_chapter:
        continue
    if search_term and search_term.strip() and search_term.strip().lower() not in c.get("text", "").lower():
        continue
    filtered.append(c)

# ---- 分页 ----
st.session_state.setdefault("browse_page", 0)
total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
st.session_state.browse_page = min(st.session_state.browse_page, total_pages - 1)
page = st.session_state.browse_page

c1, c2, c3, c4 = st.columns([1, 1, 2, 1])
if c1.button("⬅️ 上一页", disabled=page == 0, key="browse_prev"):
    st.session_state.browse_page -= 1
    st.rerun()
if c2.button("下一页 ➡️", disabled=page >= total_pages - 1, key="browse_next"):
    st.session_state.browse_page += 1
    st.rerun()
c3.markdown(f"**第 {page + 1} / {total_pages} 页** · 筛选后共 {len(filtered)} 个片段")
if c4.button("回到开头", key="browse_first"):
    st.session_state.browse_page = 0
    st.rerun()

start = page * PAGE_SIZE
for i, c in enumerate(filtered[start:start + PAGE_SIZE], start=start + 1):
    chapter = f" · 章节《{c['chapter_title']}》" if c.get("chapter_title") else ""
    page_txt = f"PDF页码 {c['page_num']}" if c.get("page_num") and c["page_num"] != -1 else "无页码（EPUB/DOCX）"
    st.markdown(f"##### 片段 {i} · {c.get('citation','未知来源')}{chapter} · {page_txt}")

    badges = []
    if c.get("source_type"):
        badges.append(f"史料类型: {c['source_type']}")
    if c.get("language"):
        badges.append(f"语言: {c['language']}")
    if c.get("stance"):
        badges.append(f"立场: {c['stance']}")
    if c.get("subfield"):
        badges.append(f"学科: {'/'.join(c['subfield'])}")
    if c.get("region"):
        regions = "/".join(c["region"]) if isinstance(c["region"], list) else c["region"]
        badges.append(f"地区: {regions}")
    if c.get("period"):
        badges.append(f"时期: {c['period']}")
    st.caption(" · ".join(badges) if badges else "无标签")
    fixed_map = st.session_state.get("browse_fixed")
    if fixed_map is None:
        fixed_map = {}
        st.session_state.browse_fixed = fixed_map
    cid = c.get("chunk_id")
    fixed = fixed_map.get(cid)
    if fixed:
        st.text(fixed)
        st.caption("🪄 已修正排版（本次浏览生效，结果已入全局缓存）")
    else:
        st.text(c.get("text", ""))
        if st.button("🪄 修正排版", key=f"fix_{cid}_{i}"):
            fixed_map[cid] = corpus_lib.get_corrected_text(c)
            st.rerun()
    st.caption(f"chunk_id: {c.get('chunk_id')}")
    st.markdown("---")
