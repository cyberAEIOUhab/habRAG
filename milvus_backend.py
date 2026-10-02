"""
Milvus / Zilliz Cloud 后端适配器
=================================
让 Milvus 冒充 chromadb.Collection 的接口（count / get / query），
这样 app.py 与 corpus_lib 的既有调用点**一行都不用改**。

接口对照（已逐一核对过项目里的全部调用点）：
    collection.count()                                    → count(*)
    collection.get(ids=[...])                             → query(chunk_id in [...])
    collection.get(where={...}, include=[...])            → query(filter=表达式)
    collection.get(include=[])["ids"]                     → query_iterator 全表扫
    collection.query(query_embeddings=[[...]], where=...) → search(anns_field="dense")

另有 Chroma 没有的能力，供检索层使用：
    search_sparse(query_text, where, limit)               → BM25 稀疏向量检索

实测要点（均已在本集群验证，勿改）：
  · 命中对象是 dict-like，主键字段在**顶层**：hit["chunk_id"]，没有 hit["id"]
  · sparse 字段**不能**出现在 output_fields 里，会报错
  · 插入时不要提供 sparse 值，由 BM25 Function 自动生成
  · 删除后立即查询可能读到旧值，故统一用 consistency_level="Strong"
"""
import os
import re
import sys

# ★ 自包含的依赖引导：pymilvus 装在项目内的 _libs/ 目录（隔离安装，
#   避免全局 pip 升级 protobuf/pandas 而破坏 Streamlit）。
#   必须放在本模块里，而不是靠调用方预先设置 sys.path ——
#   否则任何直接 `import corpus_lib` 的地方（app.py、pages/、你自己的命令行）
#   都会 ModuleNotFoundError: No module named 'pymilvus'。
#   用 append 而非 insert：让系统已有的 numpy/pandas/protobuf 优先。
_LIBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.append(_LIBS)

META_FIELDS = ["title", "chunk_index", "page_num", "chapter_title", "source_type",
               "language", "stance", "period", "region", "subfield",
               "doc_number", "doc_date", "doc_section", "doc_part"]

# 写入时逐字段的类型归类（与 migrate_to_zilliz.py 的 to_row 保持一致）
SCALAR_STR = ["title", "chapter_title", "source_type", "language", "stance", "period",
              "doc_number", "doc_date", "doc_section"]
SCALAR_INT = ["chunk_index", "page_num", "doc_part"]
ARRAYS = ["region", "subfield"]
WRITE_BATCH = 500

# sparse 由 Function 生成，任何情况下都不要放进 output_fields
_NEVER_OUTPUT = {"sparse"}

MAX_TOPK = 1024          # Serverless 单次查询上限
QUERY_PAGE = 2000        # 分页批次


# ============================================================
# Chroma where 字典 → Milvus 过滤表达式
# ============================================================
_OPS = {"$eq": "==", "$ne": "!=", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}


def _q(v):
    """把 Python 值转成 Milvus 表达式字面量（带引号转义）。

    实测语料里可筛选字段（source_type/language/stance/title/period/region/subfield）
    均不含引号、反斜杠、换行；这里仍做转义以防未来新素材引入。
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace("'", "\\'")
    s = s.replace("\n", " ").replace("\r", " ")
    return "'" + s + "'"


def where_to_expr(where):
    """Chroma where 字典 → Milvus 过滤表达式；None / 空 → 空串（表示不过滤）"""
    if not where:
        return ""
    parts = []
    for k, v in where.items():
        if k in ("$and", "$or"):
            joiner = " and " if k == "$and" else " or "
            subs = [where_to_expr(x) for x in v]
            parts.append("(" + joiner.join(s for s in subs if s) + ")")
        elif isinstance(v, dict):
            for op, val in v.items():
                if op == "$contains":                    # region / subfield 数组
                    parts.append("ARRAY_CONTAINS(%s, %s)" % (k, _q(val)))
                elif op == "$in":
                    parts.append("%s in [%s]" % (k, ", ".join(_q(x) for x in val)))
                elif op == "$nin":
                    parts.append("%s not in [%s]" % (k, ", ".join(_q(x) for x in val)))
                elif op in _OPS:
                    parts.append("%s %s %s" % (k, _OPS[op], _q(val)))
                else:
                    raise ValueError("不支持的算子: %s" % op)
        else:
            parts.append("%s == %s" % (k, _q(v)))
    return " and ".join(parts)


def row_to_meta(r):
    """Milvus 行 → Chroma 风格的 meta 字典。
    缺失的字符串字段给 ""（Chroma 的行为），缺失的 doc_* 给 None。"""
    return {
        "title":         r.get("title"),
        "chunk_index":   r.get("chunk_index"),
        "page_num":      r.get("page_num"),
        "chapter_title": r.get("chapter_title") or "",
        "source_type":   r.get("source_type"),
        "language":      r.get("language"),
        "stance":        r.get("stance"),
        "period":        r.get("period"),
        "region":        r.get("region") or [],
        "subfield":      r.get("subfield") or [],
        "doc_number":    r.get("doc_number"),
        "doc_date":      r.get("doc_date"),
        "doc_section":   r.get("doc_section"),
        "doc_part":      r.get("doc_part"),
    }


class MilvusCollection:
    """实现 chromadb.Collection 的 count / get / query 三个方法"""

    def __init__(self, uri, token, name="habsburg"):
        from pymilvus import MilvusClient
        self._cli = MilvusClient(uri=uri, token=token)
        self._name = name

    # ---------------- count ----------------
    def count(self):
        r = self._cli.query(self._name, filter="", output_fields=["count(*)"],
                            consistency_level="Strong")
        return int(r[0].get("count(*)"))

    # ---------------- include → output_fields ----------------
    def _fields(self, include):
        include = include or []
        fields = ["chunk_id"]
        if "metadatas" in include:
            fields += META_FIELDS
        if "documents" in include:
            fields.append("text")
        if "embeddings" in include:
            fields.append("dense")
        return [f for f in fields if f not in _NEVER_OUTPUT]

    # ---------------- get ----------------
    def get(self, ids=None, where=None, include=None, limit=None, offset=0):
        include = include or []
        fields = self._fields(include)

        if ids:
            # 大 id 列表分批，避免表达式过长
            rows = []
            ids = list(ids)
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                filt = "chunk_id in [%s]" % ", ".join(_q(x) for x in chunk)
                rows += self._cli.query(self._name, filter=filt, output_fields=fields,
                                        limit=len(chunk),
                                        consistency_level="Strong")
        elif limit is None:
            # 全表扫（get_book_counts 要 16 万行）→ query_iterator
            it = self._cli.query_iterator(self._name, filter=where_to_expr(where) or "",
                                          output_fields=fields, batch_size=QUERY_PAGE,
                                          consistency_level="Strong")
            rows = []
            while True:
                b = it.next()
                if not b:
                    it.close()
                    break
                rows += b
        else:
            rows = []
            want = limit
            off = offset
            while len(rows) < want:
                n = min(QUERY_PAGE, want - len(rows))
                b = self._cli.query(self._name, filter=where_to_expr(where) or "",
                                    output_fields=fields, limit=n, offset=off,
                                    consistency_level="Strong")
                if not b:
                    break
                rows += b
                off += len(b)
                if len(b) < n:
                    break

        out = {"ids": [r["chunk_id"] for r in rows]}
        if "documents" in include:
            out["documents"] = [r.get("text", "") for r in rows]
        if "metadatas" in include:
            out["metadatas"] = [row_to_meta(r) for r in rows]
        if "embeddings" in include:
            out["embeddings"] = [r.get("dense") for r in rows]
        return out

    # ---------------- query（向量检索）----------------
    def query(self, query_embeddings=None, where=None, n_results=10, include=None):
        include = include or []
        fields = self._fields(include)
        hits = self._cli.search(
            self._name,
            data=[list(map(float, query_embeddings[0]))],
            anns_field="dense",
            search_params={"metric_type": "L2"},
            limit=min(n_results, MAX_TOPK),
            filter=where_to_expr(where) or "",
            output_fields=fields,
            consistency_level="Strong",
        )[0]
        out = {"ids": [[h["chunk_id"] for h in hits]]}
        if "documents" in include:
            out["documents"] = [[h["entity"].get("text", "") for h in hits]]
        if "metadatas" in include:
            out["metadatas"] = [[row_to_meta(h["entity"]) for h in hits]]
        if "distances" in include:
            out["distances"] = [[h["distance"] for h in hits]]
        return out

    # ---------------- add / upsert / delete（写入路径）----------------
    # app.py 只读；但 ingest.py / ingest_new.py / clean.py / pages/2_文献库管理.py
    # 都会写库（重新入库 = 先 delete(where={"title":...}) 再 add），所以必须实现。
    @staticmethod
    def _to_row(cid, doc, emb, meta):
        meta = meta or {}
        row = {"chunk_id": cid, "text": doc or ""}
        if emb is not None:
            row["dense"] = [float(x) for x in emb]
        for k in SCALAR_STR:
            v = meta.get(k)
            row[k] = v if isinstance(v, str) and v else None
        for k in SCALAR_INT:
            v = meta.get(k)
            row[k] = int(v) if isinstance(v, (int, float)) else None
        for k in ARRAYS:
            v = meta.get(k)
            row[k] = list(v) if isinstance(v, (list, tuple)) else []
        # ★ 不要提供 sparse —— 由 BM25 Function 自动生成
        return row

    def _write(self, op, ids, documents, embeddings, metadatas):
        ids = list(ids)
        if not ids:
            return {op: 0}
        n = len(ids)
        docs = list(documents) if documents is not None else [None] * n
        embs = list(embeddings) if embeddings is not None else [None] * n
        metas = list(metadatas) if metadatas is not None else [{}] * n
        rows = [self._to_row(c, d, e, m) for c, d, e, m in zip(ids, docs, embs, metas)]
        if any("dense" not in r for r in rows):
            raise ValueError("add/upsert 必须提供 embeddings（dense 是必填向量字段）")
        fn = self._cli.insert if op == "added" else self._cli.upsert
        for i in range(0, len(rows), WRITE_BATCH):
            fn(self._name, rows[i:i + WRITE_BATCH])
        return {op: len(rows)}

    def add(self, ids, documents=None, embeddings=None, metadatas=None):
        return self._write("added", ids, documents, embeddings, metadatas)

    def upsert(self, ids, documents=None, embeddings=None, metadatas=None):
        return self._write("upserted", ids, documents, embeddings, metadatas)

    def delete(self, ids=None, where=None):
        """Chroma 的 delete(ids=[...]) 或 delete(where={...}) 两种形态"""
        if ids:
            ids = list(ids)
            for i in range(0, len(ids), WRITE_BATCH):
                self._cli.delete(self._name, ids=ids[i:i + WRITE_BATCH])
            return {"deleted": len(ids)}
        if where:
            self._cli.delete(self._name, filter=where_to_expr(where))
            return {"deleted": "by_filter"}
        return {"deleted": 0}

    # ---------------- 全文腿（Chroma 没有的能力）----------------
    def search_sparse(self, query_text, where=None, limit=100):
        """BM25 稀疏向量检索。data 传**原始查询文本**，不是向量。"""
        fields = self._fields(["documents", "metadatas"])
        return self._cli.search(
            self._name,
            data=[query_text],
            anns_field="sparse",
            search_params={"metric_type": "BM25"},
            limit=min(limit, MAX_TOPK),
            filter=where_to_expr(where) or "",
            output_fields=fields,
            consistency_level="Strong",
        )[0]

    def search_dense(self, query_embedding, where=None, limit=100):
        fields = self._fields(["documents", "metadatas"])
        return self._cli.search(
            self._name,
            data=[list(map(float, query_embedding))],
            anns_field="dense",
            search_params={"metric_type": "L2"},
            limit=min(limit, MAX_TOPK),
            filter=where_to_expr(where) or "",
            output_fields=fields,
            consistency_level="Strong",
        )[0]

    # ---------------- 供未改动的 app.py 直接调用 ----------------
    def list_collections(self):
        return self._cli.list_collections()

    def describe(self):
        return self._cli.describe_collection(self._name)
