# Milvus 2.5 / 2.6（含 Zilliz Cloud）Python SDK 调研报告

**目标**：用 pymilvus `MilvusClient` 建一个「字符串主键 + 1024 维稠密向量 + BM25 稀疏向量 + 长文本 + 标量/数组字段」的混合检索集合。

**调研方法 / 证据等级**（全文标注）：

| 标记 | 含义 |
|---|---|
| ✅**源码** | 直接读 pymilvus / milvus / milvus-docs 仓库源码或官方 example，最高可信度 |
| ✅**文档** | 官方文档原文（含引用），可信 |
| ⚠️**推理** | 由已核实事实推导，文档未直接陈述，需自行 `run_analyzer` / 小数据验证 |
| ❌**未找到** | 查证失败，明确标注，不要当成 API 使用 |

**重要：milvus.io 的 `/docs/*.html` 和 `/docs/*.md` 全部 5 次重定向失败**，本报告全部改用：
- `raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/...`（文档源）
- `raw.githubusercontent.com/milvus-io/pymilvus/2.6/...`（SDK 源码 + examples）
- 注意：**milvus-docs 是 `v2.6.x` 分支，milvus / pymilvus 是 `2.6` 分支**（写 `v2.6.x` 会 404）
- ⚠️ v2.6.x 文档目录结构已重组，旧扁平路径（`userGuide/full-text-search.md`）**全部 404**。新路径见各节 URL。

---

## 0. 先给结论速查表

| 问题 | 结论 |
|---|---|
| 插入时要不要给稀疏向量？ | **不要**。只给原始文本，BM25 Function 自动算 ✅源码 |
| 混合检索里 BM25 那一路 `data` 传什么？ | **原始查询文本**（`[query_text]`），不是预计算的稀疏向量 ✅源码 |
| BM25 那一路 `param` 的 metric_type | `"BM25"` ✅源码 |
| RRF k=60 | `RRFRanker(k=60)`；`k` 默认就是 60 ✅源码 |
| 稠密索引 AUTOINDEX 还是 HNSW？ | 两者都行。文档示例用 `AUTOINDEX`+`IP`；HNSW 参数名 `M`/`efConstruction` ✅源码 |
| `hybrid_search` 有顶层 `filter` 参数吗？ | **没有**。过滤写在每个 `AnnSearchRequest(expr=...)` 里 ✅源码（2.6 签名） |
| `AnnSearchRequest` 的 `param` 能省吗？ | **不能，必填无默认值**。BM25 那路也要传 `{"metric_type":"BM25"}` ✅源码 |
| 稀疏索引 index_type | `SPARSE_INVERTED_INDEX`，metric_type `BM25` ✅文档 |
| VARCHAR 过滤必须建索引吗？ | **不必须**。「VARCHAR 过滤必须建索引」是**错的** ✅文档（原文反驳） |
| max_length 上限 | **65535**，按**字节**（但官方两处文档自相矛盾）✅/⚠️ |
| `strip_accents` 存在吗？ | **不存在**。Milvus 里叫 `asciifolding` 且**不接受任何参数** ✅源码 |
| `asciifolding` 能把 ö 变成 oe 吗？ | **不能**。`Möller → Moller`（ö→o）✅源码+文档 |
| 内置 analyzer 有哪些？ | **只有 3 个：`standard` / `english` / `chinese`**。`jieba` 是 tokenizer，不是 analyzer ✅源码 |
| 德中英混合推荐？ | `{"tokenizer": "icu", "filter": ["lowercase", "asciifolding"]}`（官方「Mixed or multilingual」推荐）✅文档 |
| analyzer 能改吗？ | **不能**，建集合时定型，改只能删表重建 ✅文档 |

---

## 1. 完整建表代码

### 1.1 关键参数取值（逐个确认）

| 参数 | 取值 | 依据 |
|---|---|---|
| 主键 | `DataType.VARCHAR, is_primary=True, auto_id=False, max_length=512` | ✅源码 example |
| 稠密向量 | `DataType.FLOAT_VECTOR, dim=1024` | ✅源码 |
| 稠密索引 | `index_type="AUTOINDEX", metric_type="L2"` | ✅文档（`AUTOINDEX` 是官方示例首选）；HNSW 亦可用 |
| 稀疏字段 | `DataType.SPARSE_FLOAT_VECTOR`（**不写 dim**） | ✅文档："no dim required for sparse vectors" |
| 稀疏索引 | `index_type="SPARSE_INVERTED_INDEX", metric_type="BM25"` | ✅文档（Java/JS/cURL 示例用 `AUTOINDEX`，Python 示例统一用 `SPARSE_INVERTED_INDEX`，两者都合法） |
| 文本字段 | `DataType.VARCHAR, max_length=65535, enable_analyzer=True, analyzer_params={...}` | ✅文档 |
| 数组字段 | `DataType.ARRAY, element_type=DataType.VARCHAR, max_capacity=N, max_length=M` | ✅文档 |
| Function | `Function(name=..., function_type=FunctionType.BM25, input_field_names=["text"], output_field_names=["sparse"])` | ✅源码 |
| `Function.output_field_names` | 传 `str` 或 `list[str]` **都可以**（官方 example 两种都在用） | ✅源码 |

> **`output_field_names` 两种写法都合法**：`examples/full_text_search/bm25.py` 用 `output_field_names="sparse_vector"`（裸字符串），而文档用 `output_field_names=["sparse"]`（列表）。

### 1.2 权威签名（pymilvus `2.6` 分支源码逐字）

```python
# --- BaseMilvusClient 上的 @classmethod（所以 MilvusClient.create_schema(...) 也能直接调）
@classmethod
def create_schema(cls, **kwargs):            # -> CollectionSchema，内部强制 check_fields=False
    ...
    return CollectionSchema([], **kwargs)

@classmethod
def prepare_index_params(cls, field_name: str = "", **kwargs) -> IndexParams:
    ...

# --- MilvusClient（milvus_client.py @2.6）
def __init__(self, uri: str = "http://localhost:19530", user: str = "",
             password: str = "", db_name: str = "", token: str = "",
             timeout: Optional[float] = None, **kwargs) -> None: ...

def create_collection(self, collection_name: str, dimension: Optional[int] = None,
                      primary_field_name: str = "id", id_type: str = "int",
                      vector_field_name: str = "vector", metric_type: str = "COSINE",
                      auto_id: bool = False, timeout: Optional[float] = None,
                      schema: Optional[CollectionSchema] = None,
                      index_params: Optional[IndexParams] = None, **kwargs): ...

def insert(self, collection_name: str, data: Union[Dict, List[Dict]],
           timeout: Optional[float] = None, partition_name: Optional[str] = "",
           **kwargs) -> Dict: ...

def create_index(self, collection_name: str, index_params: IndexParams,
                 timeout: Optional[float] = None, **kwargs): ...

def load_collection(self, collection_name: str, timeout: Optional[float] = None, **kwargs): ...

# --- orm/schema.py @2.6
class Function:
    def __init__(self, name: str, function_type: FunctionType,
                 input_field_names: Union[str, List[str]],
                 output_field_names: Optional[Union[str, List[str]]] = None,
                 description: str = "", params: Optional[Dict] = None): ...

class CollectionSchema:
    def add_field(self, field_name: str, datatype: DataType, **kwargs): ...
    def add_function(self, function: "Function"): ...

# --- client/types.py @2.6
class FunctionType(IntEnum):
    UNKNOWN = 0
    BM25 = 1
    TEXTEMBEDDING = 2      # 注意：是 TEXTEMBEDDING，不是 TEXT_EMBEDDING
    RERANK = 3
    MINHASH = 4
    # 2.6 里没有 RAW 成员
```

**实际用法上的 3 个要点**：
- `Function` 的 **`function_type` 是第 2 个位置参数**（在 `input_field_names` 之前），建议全部用关键字传参。
- `FieldSchema` 的**具名参数只有 `name` / `dtype` / `description`**，其余（`is_primary` / `auto_id` / `max_length` / `dim` / `element_type` / `max_capacity` / `nullable` / `enable_analyzer` / `enable_match` / `analyzer_params` / `multi_analyzer_params` …）全部通过 `**kwargs` 传入。
- `insert()` 的签名里**没有 `progress_bar`**（官方 example `bm25.py` 里的 `progress_bar=True` 是靠 `**kwargs` 兜住的）。`create_collection()` 的签名里也**没有 `consistency_level`**，同样走 `**kwargs`——官方所有示例都这么用，是合法的。

**URL**
- https://raw.githubusercontent.com/milvus-io/pymilvus/2.6/pymilvus/milvus_client/base.py
- https://raw.githubusercontent.com/milvus-io/pymilvus/2.6/pymilvus/milvus_client/milvus_client.py
- https://raw.githubusercontent.com/milvus-io/pymilvus/2.6/pymilvus/orm/schema.py
- https://raw.githubusercontent.com/milvus-io/pymilvus/2.6/pymilvus/client/types.py

### 1.3 可运行代码

```python
"""
Milvus 2.5/2.6 建表：字符串主键 + 1024d 稠密(L2) + BM25 稀疏 + 长文本 + 标量/数组
pip install "pymilvus>=2.6.0"
"""
from pymilvus import (
    MilvusClient, DataType, Function, FunctionType,
    AnnSearchRequest, RRFRanker,
)

# Zilliz Cloud: uri="https://in03-xxxx.serverless.aws-eu-central-1.cloud.zilliz.com", token="<api-key>"
# 自建:        uri="http://localhost:19530", token="root:Milvus"
client = MilvusClient(uri="http://localhost:19530", token="root:Milvus")

COLLECTION = "habrag_chunks"
DIM = 1024
TEXT_FIELD = "text"        # 长文本（1~6KB，中/英/德混合）
SPARSE_FIELD = "sparse"    # BM25 自动产出
DENSE_FIELD = "dense"      # 1024d 稠密

# ---------------------------------------------------------------- 分析器
# 官方对 "Mixed or multilingual content" 的推荐配置（见 §4）
# icu tokenizer 是 Unicode-aware 的，能把 "Hello 世界" 切成 ['Hello',' ','世界']
# 加上 removepunct 去掉 icu 保留的标点 token（⚠️推理，见 §4.3）
ANALYZER_PARAMS = {
    "tokenizer": "icu",
    "filter": ["lowercase", "asciifolding", "removepunct"],
}

# ---------------------------------------------------------------- 1) schema
if client.has_collection(COLLECTION):
    client.drop_collection(COLLECTION)

schema = client.create_schema(auto_id=False, enable_dynamic_field=False)

# 主键：VARCHAR，形如 "深入理解计算机系统::0"
schema.add_field(
    field_name="chunk_id",
    datatype=DataType.VARCHAR,
    is_primary=True,
    auto_id=False,
    max_length=512,          # 字节数；"书名::块序号" 远小于 512
    description="书名::块序号",
)

# 1024 维稠密向量，float32，L2
schema.add_field(
    field_name=DENSE_FIELD,
    datatype=DataType.FLOAT_VECTOR,
    dim=DIM,
)

# 长文本字段：1~6KB 中/英/德混合。enable_analyzer 必须为 True，BM25 才能工作
schema.add_field(
    field_name=TEXT_FIELD,
    datatype=DataType.VARCHAR,
    max_length=65535,        # 上限就是 65535（字节），直接拉满最省事
    enable_analyzer=True,
    analyzer_params=ANALYZER_PARAMS,
    # enable_match=True,     # 只有要用 TEXT_MATCH / PHRASE_MATCH 过滤时才需要
)

# 稀疏向量字段：由 Function 产出，插入时不赋值
schema.add_field(
    field_name=SPARSE_FIELD,
    datatype=DataType.SPARSE_FLOAT_VECTOR,   # 注意：sparse 不写 dim
)

# 标量字段
schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=64)
schema.add_field(field_name="page_num",    datatype=DataType.INT64)
schema.add_field(
    field_name="region",
    datatype=DataType.ARRAY,
    element_type=DataType.VARCHAR,   # VARCHAR 数组必须同时给 max_length
    max_capacity=32,                 # 取值 1..4096
    max_length=128,
)

# ---------------------------------------------------------------- 2) BM25 Function
bm25_fn = Function(
    name="text_bm25",
    function_type=FunctionType.BM25,
    input_field_names=[TEXT_FIELD],       # BM25 只接受 1 个字段
    output_field_names=[SPARSE_FIELD],    # 传字符串也可以
)
schema.add_function(bm25_fn)

# ---------------------------------------------------------------- 3) index
index_params = client.prepare_index_params()

# 稠密：AUTOINDEX + L2（想显式控制就换 HNSW，见下方注释）
index_params.add_index(
    field_name=DENSE_FIELD,
    index_name="dense_idx",
    index_type="AUTOINDEX",
    metric_type="L2",
)
# HNSW 等价写法（pymilvus IndexParam 支持把参数当 kwargs 直接传）：
# index_params.add_index(
#     field_name=DENSE_FIELD, index_name="dense_idx",
#     index_type="HNSW", metric_type="L2",
#     M=32, efConstruction=200,
# )

# 稀疏 BM25
index_params.add_index(
    field_name=SPARSE_FIELD,
    index_name="sparse_bm25_idx",
    index_type="SPARSE_INVERTED_INDEX",
    metric_type="BM25",                    # 必须是 BM25
    params={
        "inverted_index_algo": "DAAT_MAXSCORE",  # 或 "DAAT_WAND" / "TAAT_NAIVE"
        "bm25_k1": 1.2,                          # 官方给的取值范围 [1.2, 2.0]
        "bm25_b": 0.75,
    },
)

# 标量索引（可选但强烈建议；见 §7）
index_params.add_index(field_name="source_type", index_name="source_type_idx", index_type="BITMAP")
index_params.add_index(field_name="page_num",    index_name="page_num_idx",    index_type="STL_SORT")
index_params.add_index(field_name="region",      index_name="region_idx",      index_type="BITMAP")

# ---------------------------------------------------------------- 4) create
client.create_collection(
    collection_name=COLLECTION,
    schema=schema,
    index_params=index_params,
    consistency_level="Strong",
)
print("created:", client.describe_collection(COLLECTION))
```

**注意**：标量索引 **不传 `metric_type`**；`metric_type` 只给向量字段（稀疏那路给 `"BM25"`）。

**URL**
- 建表 + Function + 索引（完整官方 Python 片段）：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/full-text-search.md
- 多向量 schema（dense + sparse + BM25 同时存在）：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/multi-vector-search.md
- 官方最简 BM25 可运行 example：https://raw.githubusercontent.com/milvus-io/pymilvus/2.6/examples/full_text_search/bm25.py
- `add_index` 参数会被 flatten（`params={}` 与 kwargs 合并）：https://raw.githubusercontent.com/milvus-io/pymilvus/master/pymilvus/milvus_client/index.py
- ARRAY 字段（`max_capacity` 1..4096、VARCHAR 元素必须给 `max_length`）：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/array_data_type.md

---

## 2. 插入代码 —— **不需要**提供稀疏向量

### 你的理解是正确的 ✅

官方文档原文（`full-text-search.md`，Insert text data 小节）：

> "After setting up your collection and index, you're ready to insert text data. **In this process, you need only to provide the raw text.** The built-in function we defined earlier automatically generates the corresponding sparse vector for each text entry."

`multi-vector-search.md` 原文：

> "Since this example uses the built-in BM25 function to generate sparse embeddings from the text field, **you do not need to supply sparse vectors manually.** However, if you opt not to use BM25, you must precompute and provide the sparse embeddings yourself."

pymilvus 官方 example 的注释也写着：

> "# We need a sparse vector field to perform full text search with BM25, but **you don't need to provide data for it when inserting data.**"

**推论（⚠️推理）**：插入时既不要给 `sparse` 赋值，也别给 `{}` 之类的空值——直接**省略该 key**。官方所有示例都是省略。

```python
rows = [
    {
        "chunk_id": "深入理解计算机系统::0",
        # 稠密向量：list[float] 或 numpy.ndarray 都行，长度必须 == 1024
        "dense": [0.0123] * DIM,
        # 长文本：中/英/德混合，1~6KB
        "text": (
            "Kapitel 3: Speicherhierarchie. 存储层次结构是计算机系统的核心概念之一。"
            "The memory hierarchy exploits locality of reference to bridge the "
            "growing gap between processor and memory speeds. "
            "Öffnungszeiten und Größe der Caches variieren je nach Prozessorgeneration."
        ),
        "source_type": "pdf",
        "page_num": 42,
        "region": ["CN", "DE"],       # 多值字符串数组
        # >>> 这里绝对不要出现 "sparse" <<<
    },
    {
        "chunk_id": "深入理解计算机系统::1",
        "dense": [0.0456] * DIM,
        "text": "Kapitel 4: Pipelining. 流水线技术通过重叠执行提高吞吐率。",
        "source_type": "epub",
        "page_num": 88,
        "region": ["US"],
    },
]

res = client.insert(collection_name=COLLECTION, data=rows)
print(res)   # {'insert_count': 2, 'ids': ['深入理解计算机系统::0', ...], ...}
```

### 两个必须知道的限制（都来自 `full-text-search.md` 的 FAQ）

1. **`sparse` 字段不能出现在 `output_fields` 里**，否则报错。官方原文：
   > "These vectors are stored in the sparse field but **cannot be included in `output_fields`**"
2. 稀疏向量**查不出来**，这是设计如此（它是内部检索索引）。要拿稀疏向量就只能自己预先算、不用 BM25 Function。

```python
# ❌ output_fields 里带 sparse -> 报错
# ✅
client.search(
    collection_name=COLLECTION,
    data=["Speicherhierarchie"],
    anns_field=SPARSE_FIELD,
    output_fields=["chunk_id", "text"],
    limit=3,
    search_params={"metric_type": "BM25"},
)
```

**URL**
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/full-text-search.md
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/multi-vector-search.md
- https://raw.githubusercontent.com/milvus-io/pymilvus/2.6/examples/full_text_search/bm25.py

---

## 3. 混合检索：`AnnSearchRequest` + `RRFRanker(k=60)`

### 3.1 你问的三个关键点，先直接回答

**Q：BM25 那一路 `data` 传原始文本还是预计算的稀疏向量？**
→ **传原始查询文本**。官方 `hello_hybrid_bm25.py` 原文注释：

> "# provide **raw text query** for full text search, while use the sparse vector as ANNS field"

`full-text-search.md` 参数表原文：

> "`data`: Raw query text in natural language. Milvus automatically converts your text query into sparse vectors using the BM25 function — **do not provide pre-computed vectors.**"

**Q：`param` 里 metric_type 填什么？**
→ **`"BM25"`**。官方源码逐字：

```python
full_text_search_params = {"metric_type": "BM25"}
full_text_search_req = AnnSearchRequest([query], "sparse_vector", full_text_search_params, limit=k)
```

**Q：`RRFRanker(k=60)` 怎么用？**
→ pymilvus **`2.6` 分支**源码逐字（`pymilvus/client/abstract.py`）：

```python
class RRFRanker(BaseRanker):
    def __init__(
        self,
        k: int = 60,
    ):
        self._strategy = RANKER_TYPE_RRF
        self._k = k
```

`k` 的**默认值就是 60**，所以 `RRFRanker()` 和 `RRFRanker(k=60)` 完全等价。
（同一个文件里 `WeightedRanker(self, *nums, norm_score: bool = True)` 是变参的，用法 `WeightedRanker(0.8, 0.2)`。若你想给稠密/稀疏不同权重就用它。）

### 3.2 `AnnSearchRequest` 权威签名（pymilvus `2.6` 分支源码逐字）

```python
class AnnSearchRequest:
    def __init__(
        self,
        data: Union[List, utils.SparseMatrixInputType],
        anns_field: str,
        param: Dict,
        limit: int,
        expr: Optional[str] = None,
        expr_params: Optional[dict] = None,
        filter: Optional[str] = None,
    ):
        self._data = data
        self._anns_field = anns_field
        self._param = param
        self._limit = limit

        if expr is not None and filter is not None:
            raise ParamError(message="Provide either 'expr' or 'filter', not both.")
        resolved = filter if filter is not None else expr
        if resolved is not None and not isinstance(resolved, str):
            raise DataTypeNotMatchException(message=ExceptionsMessage.ExprType % type(resolved))
        self._expr = resolved
        self._expr_params = expr_params
```

要点：
- **`param` 是必填位置参数，没有默认值**（类型标注是裸的 `param: Dict`，既不是 `= {}` 也不是 `= None`），在 **2.6 和 master 两个分支上都是如此**。所以官方 `multi-vector-search.md` 里那段省掉 `param` 的 sparse 请求，在 pymilvus 2.6 上会直接
  `TypeError: __init__() missing 1 required positional argument: 'param'` —— **以 pymilvus example 为准：BM25 那路也必须传 `param={"metric_type": "BM25"}`**。
- `expr` 和 `filter` **两个都可以**（`filter` 是 `expr` 的别名，属性 `.filter` 就是返回 `self._expr`），但**不能同时传**，否则抛 `ParamError(message="Provide either 'expr' or 'filter', not both.")`。这是源码里显式检查的。
- 一个 `AnnSearchRequest` **只支持一条 query**（官方原文："In Hybrid Search, each `AnnSearchRequest` supports only one query data."），所以 `data` 要写成 `[query]` / `[vec]` 的列表。
- master 分支只是多了一个 `function_chains` 参数（2.6 没有），其余完全一致。

### 3.3 `MilvusClient.hybrid_search` 完整签名（pymilvus `2.6` 源码逐字）

```python
def hybrid_search(
    self,
    collection_name: str,
    reqs: List[AnnSearchRequest],
    ranker: Union[BaseRanker, Function],
    limit: int = 10,
    output_fields: Optional[List[str]] = None,
    timeout: Optional[float] = None,
    partition_names: Optional[List[str]] = None,
    **kwargs,
) -> List[List[dict]]:
    """Conducts multi vector similarity search with a rerank for rearrangement.

    Args:
        collection_name(``string``): The name of collection.
        reqs (``List[AnnSearchRequest]``): The vector search requests.
        ranker (``Union[BaseRanker, Function]``): The ranker.
        limit (``int``): The max number of returned record, also known as `topk`.

        partition_names (``List[str]``, optional): The names of partitions to search on.
        output_fields (``List[str]``, optional):
            The name of fields to return in the search result.  Can only get scalar fields.
        round_decimal (``int``, optional):
            The specified number of decimal places of returned distance.
            Defaults to -1 means no round to returned distance.
        timeout (``float``, optional): A duration of time in seconds to allow for the RPC.
        **kwargs (``dict``): Optional search params

            * *offset* (``int``, optinal)
                offset for pagination.

            * *consistency_level* (``str/int``, optional)
                Which consistency level to use when searching in the collection.
    """
```

**参数逐个确认（这是本节最重要的结论）：**

| 你要的参数 | 在 2.6 签名里？ | 说明 |
|---|---|---|
| `collection_name` | ✅ 具名 | 必填 |
| `reqs` | ✅ 具名 | **必填，无默认值**，`List[AnnSearchRequest]` |
| `ranker` | ✅ 具名 | **必填，无默认值**。`RRFRanker(k=60)` 或 `Function(RERANK)` |
| `limit` | ✅ 具名 | `int = 10` |
| `output_fields` | ✅ 具名 | `Optional[List[str]] = None`（**只能取标量字段**，不能含 sparse 字段） |
| `partition_names` | ✅ 具名 | `Optional[List[str]] = None` |
| `timeout` | ✅ 具名 | `Optional[float] = None` |
| **`filter`** | ❌ **不在签名里** | **`hybrid_search` 没有顶层 `filter` 参数**（`search` / `query` 才有 `filter: str = ""`） |
| **`expr`** | ❌ **不在签名里** | 同上 |
| `search_params` | ❌ 不在签名里 | 检索参数在各 `AnnSearchRequest.param` 里 |
| `anns_field` | ❌ 不在签名里 | 在各 `AnnSearchRequest` 里 |
| `group_by_field` | ❌ 不在签名里 | — |
| `offset` | ⚠️ 只在 `**kwargs` 文档里 | 分页用 |
| `consistency_level` | ⚠️ 只在 `**kwargs` 文档里 | 可传，会覆盖建表时的设置 |
| `round_decimal` | ⚠️ 文档里有、签名里没有 | 只能走 `**kwargs` |

> **⚠️ 重要修正**：既然 `hybrid_search` 没有顶层 `filter`，那**过滤条件必须写在每个 `AnnSearchRequest` 的 `expr=`/`filter=` 里**。这也正是官方文档示范并且源码显式支持的做法（`expr` 与 `filter` 二选一，同时传会抛 `ParamError`）。

**调用形态**（官方 example 验证过两种写法，都合法）：

```python
# 写法 A（examples/hybrid_search.py）：位置参数
hybrid_res = milvus_client.hybrid_search(
    collection_name, req_list, RRFRanker(), default_limit, output_fields=["random"]
)
# 位置顺序即：collection_name, reqs, ranker, limit

# 写法 B（examples/simple_rerank.py）：关键字参数（推荐，可读性好）
hybrid_res = milvus_client.hybrid_search(
    collection_name, [req, req], ranker=ranker, limit=3, output_fields=["ts"]
)
```

> ⚠️ **易踩坑**：`MilvusClient.hybrid_search()` 的融合器关键字是 **`ranker=`**；
> 而老 ORM 的 `Collection.hybrid_search()` 用的是 **`rerank=`**。
> 官方 `hello_hybrid_bm25.py` 里是 `col.hybrid_search([...], rerank=RRFRanker(), limit=k, output_fields=["text"])`——**别把 `rerank` 抄到 `MilvusClient` 上**。
>
> 另注：`Collection.hybrid_search()`（ORM）内部会对调换 `reqs`/`ranker` 位置做兼容，但 `MilvusClient` **不做**，所以位置参数顺序必须对。

### 3.4 完整混合检索代码

```python
import numpy as np

def embed(texts: list[str]) -> list[list[float]]:
    """占位：换成你自己的 1024 维 embedding 模型。"""
    rng = np.random.default_rng(42)
    return rng.random((len(texts), DIM), dtype=np.float32).tolist()

query_text = "Kapitel über Speicherhierarchie 存储层次结构"
query_dense = embed([query_text])[0]          # list[float], 长度 1024

# ---- 公共过滤条件（写在每个 request 的 expr 里）
FILTER = 'page_num >= 10 and ARRAY_CONTAINS_ANY(region, ["CN", "DE"])'

# ---- 第 1 路：稠密向量（L2）
dense_req = AnnSearchRequest(
    data=[query_dense],                        # 预计算的稠密向量
    anns_field=DENSE_FIELD,
    param={"metric_type": "L2"},               # 与建索引时的 metric_type 一致
    limit=50,                                  # 每路召回数，建议远大于最终 limit
    expr=FILTER,                               # 也可以用 filter=FILTER
)

# ---- 第 2 路：BM25 稀疏（传原始文本！）
sparse_req = AnnSearchRequest(
    data=[query_text],                         # <<< 原始查询文本，不是稀疏向量
    anns_field=SPARSE_FIELD,
    param={"metric_type": "BM25"},             # <<< 必须是 BM25
    limit=50,
    expr=FILTER,
)

# ---- RRF 融合，k=60
res = client.hybrid_search(
    collection_name=COLLECTION,
    reqs=[dense_req, sparse_req],
    ranker=RRFRanker(k=60),                    # k 默认就是 60
    limit=10,                                  # 融合后的最终 topK
    output_fields=["chunk_id", "text", "source_type", "page_num", "region"],
    # ⚠️ 不要放 SPARSE_FIELD，会报错
)

for hits in res:
    for hit in hits:
        print(hit["distance"], hit["id"], hit["entity"]["chunk_id"], hit["entity"]["page_num"])
```

**关于 `metric_type="BM25"` 的检索参数细节**：官方 BM25 example 里 `client.search` 用的是
`search_params={"metric_type": "BM25", "params": {}}`；`multi-language-analyzers.md` 里还多一个
**平级**（不是嵌在 `params` 里）的 `"drop_ratio_search"` 和 `"analyzer_name"`：

```python
search_params = {
    "metric_type": "BM25",
    "analyzer_name": "english",   # 查询侧指定的 analyzer
    "drop_ratio_search": "0",
}
```

> ⚠️**推理/未验证**：`analyzer_name` 在 **`AnnSearchRequest.param` 里能否同样生效**，官方未给示例。若你用多语言分析器且混合检索需要指定查询语言，**建议先按单字段 analyzer 走（查询自动复用字段 analyzer），或实测 `param={"metric_type":"BM25","analyzer_name":"..."}`**。

**URL**
- 官方 dense+BM25+RRF 完整可运行 example（最有价值）：https://raw.githubusercontent.com/milvus-io/pymilvus/2.6/examples/hybrid_search/hello_hybrid_bm25.py
- `AnnSearchRequest` / `RRFRanker` 源码：https://raw.githubusercontent.com/milvus-io/pymilvus/master/pymilvus/client/abstract.py
- `MilvusClient.hybrid_search` 用法：https://raw.githubusercontent.com/milvus-io/pymilvus/master/examples/hybrid_search.py
- `hybrid_search(..., ranker=...,)`: https://raw.githubusercontent.com/milvus-io/pymilvus/master/examples/simple_rerank.py
- 文档 hybrid search：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/multi-vector-search.md

---

## 4. Analyzer / 分词器

### 4.1 `enable_analyzer` 怎么设 ✅文档

在 `add_field` 里作为字段参数：

```python
schema.add_field(
    field_name="text",
    datatype=DataType.VARCHAR,     # ✅ 已核实：只确认 VARCHAR 支持
    max_length=65535,
    enable_analyzer=True,
    analyzer_params=ANALYZER_PARAMS,   # 可选；不写就是 standard
)
```

- 不写 `analyzer_params` → 默认用 `standard` analyzer。官方原文："If you omit analyzer configurations during collection creation, Milvus uses the `standard` analyzer for all text processing by default."
- `enable_match=True` 是 **`TEXT_MATCH` / `PHRASE_MATCH` 过滤**额外需要的，**BM25 不需要**。
- `enable_analyzer` 作用在 **VARCHAR** 上是已核实的；作用在 `ARRAY<VARCHAR>` / `JSON` 上 ❌**未找到**任何文档或源码支持（`array_data_type.md` 通篇没提 analyzer）。

### 4.2 内置 analyzer —— **只有 3 个**（你的假设需要修正）

**❌ 纠正**：`standard / english / chinese / jieba` 这个列表**不准确**。
- **内置 analyzer 名字只有 3 个**：`standard`、`english`、`chinese`
- **`jieba` 是 tokenizer，不是 analyzer 名字**，不存在 `{"type": "jieba"}`

源码级证据（`milvus` 仓库 `2.6` 分支，tantivy-binding，`build_template` 穷举）：

```rust
fn build_template(self, type_: &str) -> Result<TextAnalyzer> {
    match type_ {
        "standard" => Ok(standard_analyzer(self.get_stop_words_option()?)),
        "chinese"  => Ok(chinese_analyzer(self.get_stop_words_option()?)),
        "english"  => Ok(english_analyzer(self.get_stop_words_option()?)),
        other_ => Err(TantivyBindingError::InternalError(format!(
            "unknown build-in analyzer type: {}", other_))),
    }
}
```

三个内置 analyzer 的构成（官方表格）：

| Analyzer | 语言 | 组件 | 说明 |
|---|---|---|---|
| `standard` | 大多数空格分词语言（英/法/**德**/西…） | tokenizer `standard` + filter `lowercase` | 通用；单语言场景下专用 analyzer 更好 |
| `english` | 英语 | tokenizer `standard` + filter `lowercase`, `stemmer`, `stop` | 英语内容推荐 |
| `chinese` | 中文 | tokenizer `jieba` + filter `cnalphanumonly` | 默认简体词典 |

**`chinese` + 德语的一个坑（⚠️推理）**：`cnalphanumonly` 的语义是「丢掉含非中文/非英文字母/非数字字符的 token」。德语 `Möller` 里的 `ö` 不属于「中文字符、英文字母、数字」，**整个 token 可能被丢弃**。
→ 如果走 `chinese` 路线，filter 顺序必须把 `asciifolding` 放在 `cnalphanumonly` **之前**（filter 按声明顺序执行），让 `Möller→Moller` 先变成纯 ASCII：
```python
{"tokenizer": "jieba", "filter": ["asciifolding", "lowercase", "cnalphanumonly"]}
```
**这一点请用 `run_analyzer` 实测确认**（见 4.5）。

**URL**
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/choose-the-right-analyzer-for-your-use-case.md
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/analyzer-overview.md
- 源码 `build_template`：https://raw.githubusercontent.com/milvus-io/milvus/2.6/internal/core/thirdparty/tantivy/tantivy-binding/src/analyzer/build_in_analyzer.rs

### 4.3 英/德/中混合，推荐哪个？

**推荐（官方 "Mixed or multilingual content" 段落给的 Basic multilingual configuration）：**

```python
ANALYZER_PARAMS = {
    "tokenizer": "icu",
    "filter": ["lowercase", "asciifolding"],
}
```

官方原文（推荐 icu 的理由）：
> "Use a custom analyzer with the `icu` tokenizer for unicode-aware tokenization."
> "**When to use icu**: Mixed languages where language identification is impractical."

`icu` 是 Unicode-aware 的世界分词，`"Hello 世界 مرحبا"` → `['Hello', ' ', '世界', ' ', 'مرحبا']`。

**⚠️ 我建议额外加 `removepunct`**（文档明确说 icu 会把标点/空格留成独立 token，而 `removepunct` 正是为 jieba/lindera/icu 这种 tokenizer 准备的）：
```python
{"tokenizer": "icu", "filter": ["lowercase", "asciifolding", "removepunct"]}
```
（第 1 节的代码已经这么写。）

**另一条路：中文优先 —— `chinese` 或 `jieba`**
如果你的语料**中文占绝对主体**、英德只是零散术语，用 `jieba` 对中文分词质量更好：

```python
# 方式 1：内置 chinese（jieba + cnalphanumonly）
{"type": "chinese"}

# 方式 2：自定义，兼顾德文变音
{"tokenizer": "jieba", "filter": ["asciifolding", "lowercase", "cnalphanumonly"]}
```

**第三条路（最精确，但需要额外字段）：多语言分析器 / 语言识别**

- `multi_analyzer_params`：按行里的某个 VARCHAR 字段选分析器（pymilvus 官方 example 已验证 `by_field` 用法）：

```python
multi_analyzer_params = {
    "analyzers": {
        "english":  {"type": "english"},
        "chinese":  {"type": "chinese"},
        "German":   {"tokenizer": "standard",
                     "filter": ["lowercase", {"type": "stemmer", "language": "german"}]},
        "default":  {"tokenizer": "icu"},     # 必须有 default 兜底
    },
    "by_field": "language",                    # 必须是集合里已存在的 VARCHAR 字段
    "alias": {"cn": "chinese", "en": "english", "de": "German"},   # 可选
}
schema.add_field(field_name="language", datatype=DataType.VARCHAR, max_length=16, nullable=True)
schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535,
                 enable_analyzer=True, multi_analyzer_params=multi_analyzer_params)
```
查询时用 `search_params={"metric_type": "BM25", "analyzer_name": "German"}` 指定。

- `language_identifier` tokenizer（自动识别，beta Milvus **2.5.15+**）：

```python
analyzer_params = {
    "tokenizer": {
        "type": "language_identifier",
        "identifier": "whatlang",        # 或 "lingua"（两者语言命名不同！）
        "analyzers": {
            "default":  {"tokenizer": "standard"},
            "English":  {"type": "english"},
            "German":   {"tokenizer": "standard",
                         "filter": ["lowercase", {"type": "stemmer", "language": "german"}]},
            "Mandarin": {"tokenizer": "jieba"},
        },
    }
}
```
⚠️ 注意 `whatlang` 返回 `Mandarin`，`lingua` 返回 `Chinese`——名字必须和引擎输出对齐。

**德语专项能力（都已核实存在）**
- `stemmer` + `"language": "german"` ✅（支持列表含 `german`）
- `stop` + `stop_words: ["_german_"]` ✅（内置停用词表别名含 `_german_`）
- `decompounder`（德语复合词拆分）：`"dampfschifffahrt"` → `['dampf','schiff','fahrt']`，参数是 `word_list`
- **没有**德语专用 analyzer / tokenizer

**URL**
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/choose-the-right-analyzer-for-your-use-case.md
- 多语言分析器：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/multi-language-analyzers.md
- 语言识别：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/tokenizer/language-identifier.md
- stemmer：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/filter/stemmer-filter.md
- decompounder：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/filter/decompounder-filter.md
- jieba：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/tokenizer/jieba-tokenizer.md

### 4.4 ⚠️ 关于 `lowercase` / `strip_accents`：**`strip_accents` 在 Milvus 里不存在**

**❌ `strip_accents`：NOT FOUND。** 查证范围：v2.6.x 文档、v3.0.x 文档、Milvus 2.6 Rust filter 注册表、tantivy 实现。结论：
- Milvus **没有任何叫 `strip_accents` 的参数**（这是 Elasticsearch / Bleve 的概念）
- 对应的东西叫 **`asciifolding`**，而且它是一个**无参 filter**（源码里是 unit struct，无法接收参数），只能写成 `"filter": ["asciifolding"]`

**`lowercase`**：是独立的 **filter**（不是 tokenizer 参数），写成 `"filter": ["lowercase"]`，**也不接受任何参数**。
- ❌「`standard` tokenizer 支持 `lowercase` 参数」：**NOT FOUND**。`standard` tokenizer 文档里**没有任何参数**，`lowercase` 只能作为独立 filter 使用。
- `standard` **analyzer** 的 lowercase 行为是内置写死的，不可配置。
- `standard` / `english` analyzer 的**唯一**可选参数是 `stop_words`（默认 `_english_`）；`chinese` **不接受任何参数**。

**analyzer_params 的两条互斥代码路径（源码级，很重要）**：
- 有 `"type"` → 走内置模板，**只认 `stop_words`**；此时写 `tokenizer`/`filter` 无意义
- 没有 `"type"` → 只认 `tokenizer` 和 `filter` 两个 key；**此时写 `stop_words` 会直接报错** `unknown analyzer option key: stop_words`

### 4.5 🎯 `strip_accents` 能解决 "ö" ↔ "oe" 或 "ö" ↔ "o" 的匹配吗？

**结论（源码 + 文档双重核实）：**

| 你的需求 | 能否用 `asciifolding` 解决 |
|---|---|
| 搜 `o` → 命中 `ö` | ✅ **能**。两边都折叠成 `o` |
| 搜 `Moller` → 命中 `Möller` | ✅ **能** |
| 搜 `oe` → 命中 `ö` | ❌ **不能**。`ö` 索引成 `o`，不是 `oe` |
| 搜 `Moeller` → 命中 `Möller` | ❌ **不能** |
| 搜 `ss` → 命中 `ß` | ✅ **能**（`ß → ss`） |
| 搜 `oe` → 命中 `œ` | ✅ **能**（连字 `œ → oe`） |

**决定性证据 1 —— 官方文档给的期望输出**（`ascii-folding-filter.md`）：

```
Input:  "Café Möller serves crème brûlée and piñatas."
Output: ['Cafe', 'Moller', 'serves', 'creme', 'brulee', 'and', 'pinatas']
```

注意 **`Möller → Moller`，不是 `Moeller`**。

**决定性证据 2 —— tantivy（Milvus 底层库）的折叠表逐字**：

```rust
'\u{00F6}' // ö  [LATIN SMALL LETTER O WITH DIAERESIS]
=> Some("o"),                     // <<< 单字符 "o"，不是 "oe"

'\u{00DF}' // ß  [LATIN SMALL LETTER SHARP S]
=> Some("ss"),                    // <<< 只有连字和 ß 才会 1→2 展开

'\u{0153}' | // œ  [LATIN SMALL LIGATURE OE]
=> Some("oe"),                    // <<< "oe" 只可能来自连字 œ，不可能来自 ö
```

**「ASCII folding 会做 1→2 展开」这个说法在德语元音上是错的** —— 展开只发生在连字（`œ→oe`, `æ→ae`, `ﬀ→ff`, `ﬆ→st`）和 `ß→ss` 上，**ö/ä/ü 一律折叠成单字母**。

**有没有任何 Milvus analyzer 做德语元音展开（ä→ae, ö→oe, ü→ue）？**
→ ❌ **没有**。Milvus 2.6 的 11 个 filter 里没有任何德语元音展开功能。尤其**没有 Lucene/ES 的 `german_normalization`**。

**`stemmer` + `language: "german"` 呢？** 这里有一个**未验证的灰色地带**，需要你实测：
- 链路已核实：Milvus `{"type":"stemmer","language":"german"}` → `rust_stemmers::Algorithm::German` → Snowball German 算法
- Snowball German 的预处理规则（官方文档逐字）里有：`(b) replace ae with ä, (c) replace oe with ö, (d) replace ue with ü (unless preceded by q)`，以及最后 "remove the umlaut accent from a, o, u"
- **方向是 `oe → ö`，而不是 `ö → oe`**；且最后去掉变音符号。理论上 `Möller` 和 `Moeller` 会归并到同一个词干
- ⚠️ **但**：Snowball 官方 changelog 说 "Snowball 3.0.0: Handle ASCII transliterations of umlauts (merging the 'german2' variant into the standard algorithm)" —— 也就是说这些规则**历史上只在 `german2` 变体里**。我**无法核实** pymilvus/Milvus 2.6 实际链接的 `rust-stemmers` 版本编译进了哪一版 Snowball。→ **`language="german"` 能否让 `oe ↔ ö` 互匹配，标记为 ❌未验证**

**给你的实操建议（如果 `oe ↔ ö` 是硬需求）：**
1. **首选：自己归一化文本再入库**。Milvus 侧没有任何 filter 能做这件事。你可以：
   - 保留原文字段 `text` 用于展示；
   - 另加一个 `text_bm25` 字段，存**你自己归一化过的副本**（`ä→ae`, `ö→oe`, `ü→ue`, `ß→ss`），**BM25 Function 挂在这个字段上**。
   - 一个集合可以有多个 VARCHAR 字段，每个挂一个独立 BM25 Function（官方原文："If multiple `VARCHAR` fields require BM25 processing, define **one BM25 function per field**"）。
   - 查询侧对 query 文本做**同样**的归一化。
2. **次选：靠 `asciifolding` 把标准降到 `ö↔o`**（能覆盖大部分德语检索场景，因为用户也很少严格区分 `Moller`/`Moeller`）。
3. **先实测再决定**：
```python
for params in [
    {"tokenizer": "standard", "filter": ["lowercase", "asciifolding"]},
    {"tokenizer": "standard", "filter": ["lowercase", {"type": "stemmer", "language": "german"}]},
    {"tokenizer": "standard", "filter": ["lowercase", "asciifolding",
                                        {"type": "stemmer", "language": "german"}]},
]:
    print(params, "->", client.run_analyzer("Möller Moeller Moller öffnen", params))
```

### 4.6 `run_analyzer` —— 建表前必用的验证工具 ✅源码

`client.run_analyzer(text, analyzer_params)` 可在**不建集合**的情况下看分词结果（Milvus 2.5.11+，文档里所有 analyzer 示例都用它）：

```python
client = MilvusClient(uri="http://localhost:19530", token="root:Milvus")
print(client.run_analyzer(
    "Café Möller 机器学习 Kapitel über Speicherhierarchie",
    ANALYZER_PARAMS,
))
```

**强烈建议**：在你确定 `ANALYZER_PARAMS` 之前，先把中/英/德三种样本各跑一遍 `run_analyzer`，因为 **analyzer 一旦建表就永久固定**。

### 4.7 ⚠️ analyzer 不可修改 ✅文档

`keyword-match.md` / `phrase-match.md` 的 "Considerations" 原文：

> "Once you've defined an analyzer in your schema, **its settings become permanent for that collection**. If you decide that a different analyzer would better suit your needs, you may consider **dropping the existing collection and creating a new one** with the desired analyzer configuration."

`alter_collection_field` 能改的只有 VARCHAR 的 `max_length`、ARRAY 的 `max_capacity`、和 `mmap.enabled`，**没有 analyzer**。

**URL**
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/filter/ascii-folding-filter.md
- 折叠表源码：https://raw.githubusercontent.com/zilliztech/tantivy/main/src/tokenizer/ascii_folding_filter.rs
- Milvus filter 注册表（穷举 11 个 filter）：https://raw.githubusercontent.com/milvus-io/milvus/2.6/internal/core/thirdparty/tantivy/tantivy-binding/src/analyzer/filter/filter.rs
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/analyzer/filter/stop-filter.md
- Snowball German 算法：https://snowballstem.org/algorithms/german/stemmer.html

---

## 5. 过滤表达式语法

**统一入口**：`filter=` 字符串（`AnnSearchRequest` 里 `expr=` / `filter=` 等价）。
运算符**大小写不敏感**（源码语法文件里每个关键字都有大小写两套）。

### 5.1 操作符速查（全部已核实）

```python
# (a) 等值 / 不等 —— 字符串和数字都用 ==
'source_type == "pdf"'
'source_type != "epub"'
'page_num == 42'

# 注意：Milvus 用 == 而不是 =；字符串可以用单引号或双引号
"source_type == 'pdf'"

# (b) 范围
'page_num > 10'
'page_num >= 10'
'page_num < 100'
'page_num <= 100'
'page_num != 0'

# (b2) LIKE 前缀/中缀/后缀（% 任意长度，_ 恰好一个字符）
'source_type LIKE "pd%"'
'source_type LIKE "%df%"'
'text LIKE "%Speicher%"'
```
文档原文："The `LIKE` operator uses the `%` symbol as a wildcard, which can match any number of characters (including zero)." 以及 "In most cases, **infix** or **suffix** matching is significantly slower than prefix matching."（中缀/后缀很慢；要快就建 NGRAM 索引）

```python
# (c) 布尔
'page_num > 100 AND source_type == "pdf"'
'source_type == "pdf" OR source_type == "epub"'
'NOT source_type == "epub"'
# && || ! 也合法（源码语法确认）
'page_num > 100 && source_type == "pdf"'
'source_type == "pdf" || source_type == "epub"'
'!(source_type == "epub")'
```

源码依据（`internal/parser/planparserv2/Plan.g4`，Milvus 2.6 分支逐字）：
```antlr
AND: '&&' | 'and' | 'AND';
OR:  '||' | 'or'  | 'OR';
NOT: '!'  | 'not' | 'NOT';
IN:  'in' | 'IN';
LIKE:'like'| 'LIKE';
EXISTS: 'exists' | 'EXISTS';
ISNULL: 'is null' | 'IS NULL';
ISNOTNULL: 'is not null' | 'IS NOT NULL';
```

```python
# (d) in / not in
'source_type in ["pdf", "epub", "docx"]'
'source_type not in ["pdf"]'
# ⚠️ not in 的文档示例 ❌未找到（只有语法保证）；不放心可以写 'not (source_type in ["pdf"])'
```

```python
# (e) 数组：包含任意一个元素  <<< 你要的
'ARRAY_CONTAINS_ANY(region, ["CN", "DE"])'
# 数组：包含指定元素
'ARRAY_CONTAINS(region, "CN")'
# 数组：包含全部指定元素
'ARRAY_CONTAINS_ALL(region, ["CN", "DE"])'
# 数组长度
'ARRAY_LENGTH(region) < 10'
# 下标访问
'ratings[0] > 4'
```
参数顺序固定是 **`(字段名, 表达式)`**。官方示例逐字：`filter = 'ARRAY_CONTAINS_ANY(history_temperatures, [23, 24])'`

```python
# (f) 判空 / 判存在
'source_type IS NOT NULL'
'source_type IS NULL'
'page_num IS NOT NULL AND page_num > 10'
'region IS NULL'
'region IS NOT NULL'
```
- 大小写不敏感："The operators are case-insensitive, so you can use `IS NULL` or `is null`"
- **空字符串 `""` 不算 NULL**（文档原文："An empty string `""` is not treated as a null value for a `VARCHAR` field."）
- ⚠️ 要让字段真的能存 NULL，建表时该字段必须 `nullable=True`（Milvus 2.5 引入 nullable/default）。没设 `nullable=True` 的字段不会有 NULL 值，`IS NULL` 永远匹配不到。
- ❌ `exists` 关键字：**语法里有，但官方文档找不到任何使用示例**。建议统一用 `IS NOT NULL`。

### 5.2 组合成实际过滤器

```python
FILTER = (
    'page_num >= 10 '
    'and ARRAY_CONTAINS_ANY(region, ["CN", "DE"]) '
    'and source_type in ["pdf", "epub"] '
    'and chunk_id != "" '
)
```

### 5.3 转义引号 ⚠️（最容易踩的坑）

官方 "Escape rules in `filter` expressions" 原文（markdown 源码里显示为双反斜杠，**实际 Python 字符串里是单反斜杠**）：

| 场景 | 写法 |
|---|---|
| 单引号串里的单引号 | `'It\'s milvus'` |
| 双引号串里的双引号 | `"He said \"Hi\""` |
| 反斜杠本身 | `\\` |
| 制表符 / 换行 | `\t` / `\n` |

```python
# Python 里别忘了再转义一层
f = "text == 'It\\'s milvus'"      # 实际发给 Milvus 的是 text == 'It\'s milvus'
f = 'text == "He said \\"Hi\\""'
```
> ⚠️ 文档 markdown 里渲染成 `\\'` 是因为它自己转义了 code span。**真正的转义符是单反斜杠**（语法文件 `EscapeSequence: '\\' ['"?abfnrtv\\] | ...` 确认）。不要照抄双反斜杠进 Python。

**URL**
- 比较/逻辑/NULL：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/boolean/basic-operators.md
- 数组操作符：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/boolean/array-operators.md
- in / 模板化 CJK：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/boolean/boolean.md
- 转义规则：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/search-query-get/keyword-match.md
- 语法文件：https://raw.githubusercontent.com/milvus-io/milvus/2.6/internal/parser/planparserv2/Plan.g4
- ❌ 旧路径 `site/en/userGuide/boolean.md`、`site/en/userGuide/array-operators.md` 在 v2.6.x 已 404（搬到 `search-query-get/boolean/` 下了）

---

## 6. VARCHAR `max_length` 限制

### 6.1 上限 = **65535** ✅文档

`string.md` 原文：
> "Specify the `max_length`, which defines the maximum number of **bytes** the `VARCHAR` field can store. **The valid range for `max_length` is from 1 to 65,535.**"

`about/limitations.md` 的表格也印证：
```
| VARCHAR | 65,535 |
```

### 6.2 字节还是字符？⚠️ **官方文档自相矛盾**

| 文档 | 说法 |
|---|---|
| `userGuide/schema/string.md`（建表页） | "the maximum number of **bytes**" |
| `userGuide/schema/alter-collection-field.md` | "constrains the maximum number of **characters**" |

→ **按字节规划最安全**。理由：建表说明页写 bytes，且 Milvus 服务端是 Go，对 string 取 `len()` 得到的就是 UTF-8 字节数。

> ❌ **未找到**：官方没有任何一句话明确说明「非 ASCII/CJK 字符占多字节」。`string.md`、`schema.md`、`reference/schema.md`、`limitations.md`、`array_data_type.md`、`use-json-fields.md`、`ngram.md`、`alter-collection-field.md` 全都没有。

### 6.3 UTF-8 中文怎么算（⚠️推理，非文档引用）

UTF-8 下：
- ASCII（英/德基本字母）：1 字节
- 拉丁扩展（ä ö ü ß é）：**2 字节**
- CJK 汉字 / 日文假名：**3 字节**
- emoji：4 字节

所以：

| 内容 | 字节数 |
|---|---|
| 65535 个纯英文字符 | 65535 字节 → **刚好用满** |
| 65535 个汉字 | 196605 字节 → **远超上限** |
| `max_length=65535` 能装的中文上限 | **约 21845 个汉字**（65535 / 3） |

**对你的场景（1~6KB 混合文本）**：
- 如果 "6KB" 指 6000 **字节** → `max_length=8192` 就够
- 如果 "6KB" 指 6000 **字符**且含大量中文 → 最坏 6000×3 = 18000 字节 → `max_length=32768`
- **建议直接 `max_length=65535` 拉满**，反正 VARCHAR 是变长存储，`max_length` 只是校验上限，不预分配空间

### 6.4 数组元素的 `max_length` ✅文档

`array_data_type.md` 原文：
> "When `element_type` is set to `VARCHAR`, you must also specify the `max_length` for array elements."
> "The number of elements in an ARRAY field must be less than or equal to the maximum capacity defined when the Array was created, as specified by `max_capacity`. The value should be an integer within the range from **1** to **4096**."

- `max_capacity`: **1 ~ 4096**
- 元素的 `max_length`：官方示例直接用 `max_length=65535`；❌**未找到**独立于 VARCHAR 的 1..65535 的另一套区间
- `element_type` 可以是任何标量类型，**除了 `JSON`**
- 建表后只能改 `max_capacity`，**不能改 `element_type`**

```python
schema.add_field(field_name="region", datatype=DataType.ARRAY,
                 element_type=DataType.VARCHAR, max_capacity=32, max_length=128)
```

**URL**
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/string.md
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/about/limitations.md
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/array_data_type.md
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/alter-collection-field.md

---

## 7. 标量字段索引

### 7.1 ❌「VARCHAR 过滤必须建索引」是**错的**

官方原文（`string.md` 和 `array_data_type.md` 的 "Set index params" 小节都有这句）：

> "Indexing helps improve search and query performance. In Milvus, **indexing is mandatory for vector fields but optional for scalar fields.**"

旁证（`use-json-fields.md`）：
> "Indexing JSON fields is **optional**. You can still query or filter by JSON paths without an index, but it may result in slower performance due to **brute-force search**."

所以：
- **VARCHAR / INT / BOOL / ARRAY / JSON 过滤全部不强制建索引**，没索引就是退化成全表扫描（慢，但能跑）
- **强制建索引的只有向量字段**（原文："Create an index on your vector fields (mandatory for each vector field in a collection)"）
- 每个标量字段**最多一个**索引（"Each scalar field supports one index."）

**结论：对你的场景建议建，但不是「必须」。** 不建也能过滤，只是慢了。

### 7.2 索引类型 ↔ 字段类型映射 ✅文档

| 字段类型 | 可用索引 | 官方推荐 |
|---|---|---|
| **VARCHAR** | `INVERTED`, `BITMAP`, `Trie`(旧), `NGRAM`(为 LIKE) | **`INVERTED`** |
| BOOL | `BITMAP`, `INVERTED` | `BITMAP` |
| INT8/16/32/64 | `INVERTED`, `STL_SORT` | 范围过滤选 `STL_SORT` |
| FLOAT / DOUBLE | `INVERTED` | — |
| ARRAY（BOOL/INT/VARCHAR 元素） | `BITMAP`, `INVERTED` | `BITMAP` |
| JSON | `INVERTED` | — |
| GEOMETRY | `RTREE`（2.6.4+ beta） | — |

`scalar_index.md` 里 AUTOINDEX 的行为原文：
> "When calling the `create_index` method, if the `index_type` is not specified, Milvus automatically selects the most suitable index type based on the data type."（VARCHAR / INT / FLOAT / DOUBLE → 倒排索引）

`INVERTED` 最通用（原文："INVERTED indexes support **all** scalar field types"）；`BITMAP` **不支持** FLOAT/DOUBLE/JSON（原文："Bitmap indexes do not support the following data types: `FLOAT`, `DOUBLE` ... `JSON`"）。

### 7.3 针对你的字段的推荐

| 字段 | 推荐 index_type | 理由 |
|---|---|---|
| `source_type`（如 pdf/epub/docx，低基数） | **`BITMAP`** | 官方："most effective when the cardinality of a field is **less than 500**" |
| `page_num`（INT64，范围过滤） | **`STL_SORT`** | 官方：支持 `==`/`!=`/`>`/`<`/`>=`/`<=`，复杂度从 O(n) 降到 **O(log n + m)** |
| `region`（VARCHAR 数组，多值任意匹配） | **`BITMAP`** | 映射表对 ARRAY 推荐 BITMAP；`ARRAY_CONTAINS_ANY` 正是其用例 |
| `chunk_id`（VARCHAR 主键，高基数） | `INVERTED`（可选） | INVERTED 是 VARCHAR 推荐类型；主键本身已有内部索引 |
| 若以后要 `LIKE '%xxx%'` | **`NGRAM`** | 官方："The `NGRAM` index in Milvus is built to accelerate `LIKE` queries" |

### 7.4 建标量索引的代码 ✅源码

标量索引 **不传 `metric_type`**（只有向量字段传）：

```python
index_params = client.prepare_index_params()

# ---- 标量：不带 metric_type ----
index_params.add_index(
    field_name="source_type",
    index_name="source_type_idx",
    index_type="BITMAP",
)
index_params.add_index(
    field_name="page_num",
    index_name="page_num_idx",
    index_type="STL_SORT",
)
index_params.add_index(
    field_name="region",
    index_name="region_idx",
    index_type="BITMAP",
)

# ---- 向量：带 metric_type ----
index_params.add_index(
    field_name="dense",
    index_name="dense_idx",
    index_type="AUTOINDEX",
    metric_type="L2",
)
```

**也可以事后单独加**（集合已存在时）：
```python
client.create_index(
    collection_name=COLLECTION,
    index_params=client.prepare_index_params().add_index(
        field_name="source_type", index_name="source_type_idx", index_type="BITMAP"
    ),
)
```
> 注：`add_index` 的返回值是 `None`（它是 `list.append` 的包装），**别写成 `index_params = client.prepare_index_params().add_index(...)`**——那样会拿到 `None`。要分两步写。

**`AUTOINDEX` 也可以**：只给 `field_name` + `index_name`，Milvus 自动选：
```python
index_params.add_index(field_name="source_type", index_type="AUTOINDEX", index_name="st_idx")
```

**URL**
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/reference/scalar_index.md
- https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/indexes/index-explained.md
- BITMAP 细节（"cardinality < 500"）：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/indexes/scalar/bitmap.md
- INVERTED：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/indexes/scalar/inverted.md
- STL_SORT：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/indexes/scalar/stl-sort.md
- NGRAM：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/indexes/scalar/ngram.md
- pymilvus 标量索引示例：https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.6.x/site/en/userGuide/schema/string.md

---

## 8. 明确「未找到」清单（不要当成 API 用）

1. ❌ `strip_accents` —— Milvus 2.6 和 v3.0.x 文档、Rust filter 注册表、tantivy 实现里**都不存在**。等价物是无参的 `asciifolding`。
2. ❌ `standard` tokenizer 的 `lowercase` 参数 —— tokenizer 无参数；`lowercase` 只是独立 filter。
3. ❌ `icu` tokenizer 的 `locale` 参数 —— `IcuTokenizer::new()` 用 `WordBreakOptions::default()`，完全忽略参数。
4. ❌ 德语专用 analyzer/tokenizer —— 不存在。德语能力只有 `stemmer.language="german"`、`stop_words: ["_german_"]`、`decompounder`。
5. ❌ `german_normalization` filter（Lucene/ES 有，Milvus 没有）。
6. ❌ 任何能把 `ö` 变成 `oe` 的 Milvus filter。
7. ❌ `stemmer language="german"` 使 `oe ↔ ö` 互匹配 —— **未验证**（Snowball 3.0 才把 german2 的 ASCII 转写规则并入标准算法，无法核实 Milvus 2.6 链接的 rust-stemmers 版本）。**必须用 `run_analyzer` 实测。**
8. ❌ `not in` 的官方文档示例 —— 只有 ANTLR 语法保证能解析。
9. ❌ `exists` 过滤关键字的官方文档示例 —— 只有语法保证。
10. ❌ 明确说明「max_length 对 CJK 按 UTF-8 字节计数」的官方语句 —— 而且文档自相矛盾（`string.md` 说 bytes，`alter-collection-field.md` 说 characters）。
11. ❌ ARRAY 元素 `max_length` 独立于 VARCHAR 的区间说明。
12. ❌ 「标量索引不需要 metric_type」的明确文字 —— 只能靠所有官方示例都不传它来推断。
13. ❌ `TEXT_SIMILARITY` —— Milvus 2.6 文档和语法里都没有。（有 `TEXT_MATCH` 和 `PHRASE_MATCH`，见下）
14. ❌ `enable_analyzer` 支持 `ARRAY<VARCHAR>` / `JSON` 的证据 —— `array_data_type.md` 通篇未提 analyzer。
15. ❌ `analyzer_name` 在 `AnnSearchRequest.param` 里是否能生效 —— 官方只在 `client.search` 的 `search_params` 里示范过。
16. ✅ **已解决（不再是未找到项）**：`MilvusClient.hybrid_search` 在 pymilvus **2.6 源码里确实没有顶层 `filter`/`expr` 参数**。过滤条件必须写在各个 `AnnSearchRequest(expr=...)` 里。
17. ⚠️ `client/grpc_handler.py` 未能取到（raw 超时 / jsdelivr 返回 octet-stream），所以「`hybrid_search` 收到多余的 `filter=` kwarg 时是静默忽略还是报错」**未验证**。但公开签名没声明它，**按不支持处理**。
18. ❌ `MilvusClient.insert` 的 `progress_bar` 参数 —— 不在 2.6 签名里（官方 example 靠 `**kwargs` 兜住）。功能是否真的生效**未验证**。
19. ❌ 内置 `ngram` tokenizer 的用户可用性 —— 2.6 源码里存在 `ngram_tokenizer_with_chars.rs`，但**不在 tokenizer dispatch 的 match 分支里**，也没有文档页。真正在生产的是 `NGRAM` **索引**（为 `LIKE` 加速），那个是文档化的。

---

## 9. 附：全流程可运行脚本（把 §1/§2/§3 串起来）

```python
"""
pip install "pymilvus>=2.6.0"
Milvus 2.6 standalone:  docker run -d --name milvus -p 19530:19530 milvusdb/milvus:v2.6.0 milvus run standalone
"""
from pymilvus import (
    MilvusClient, DataType, Function, FunctionType,
    AnnSearchRequest, RRFRanker,
)

COLLECTION, DIM = "habrag_chunks", 1024
TEXT_FIELD, SPARSE_FIELD, DENSE_FIELD = "text", "sparse", "dense"

client = MilvusClient(uri="http://localhost:19530", token="root:Milvus")

ANALYZER_PARAMS = {
    "tokenizer": "icu",
    "filter": ["lowercase", "asciifolding", "removepunct"],
}

# ---------- 0) 先验证 analyzer（可选但强烈建议） ----------
print(client.run_analyzer(
    "Café Möller 机器学习 Kapitel über Speicherhierarchie", ANALYZER_PARAMS))

# ---------- 1) schema ----------
if client.has_collection(COLLECTION):
    client.drop_collection(COLLECTION)

schema = client.create_schema(auto_id=False, enable_dynamic_field=False)

schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR,
                 is_primary=True, auto_id=False, max_length=512)
schema.add_field(field_name=DENSE_FIELD, datatype=DataType.FLOAT_VECTOR, dim=DIM)
schema.add_field(field_name=TEXT_FIELD, datatype=DataType.VARCHAR, max_length=65535,
                 enable_analyzer=True, analyzer_params=ANALYZER_PARAMS)
schema.add_field(field_name=SPARSE_FIELD, datatype=DataType.SPARSE_FLOAT_VECTOR)
schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=64)
schema.add_field(field_name="page_num", datatype=DataType.INT64)
schema.add_field(field_name="region", datatype=DataType.ARRAY,
                 element_type=DataType.VARCHAR, max_capacity=32, max_length=128)

schema.add_function(Function(
    name="text_bm25", function_type=FunctionType.BM25,
    input_field_names=[TEXT_FIELD], output_field_names=[SPARSE_FIELD],
))

# ---------- 2) index ----------
ip = client.prepare_index_params()
ip.add_index(field_name=DENSE_FIELD, index_name="dense_idx",
             index_type="AUTOINDEX", metric_type="L2")
ip.add_index(field_name=SPARSE_FIELD, index_name="sparse_bm25_idx",
             index_type="SPARSE_INVERTED_INDEX", metric_type="BM25",
             params={"inverted_index_algo": "DAAT_MAXSCORE",
                     "bm25_k1": 1.2, "bm25_b": 0.75})
ip.add_index(field_name="source_type", index_name="source_type_idx", index_type="BITMAP")
ip.add_index(field_name="page_num",    index_name="page_num_idx",    index_type="STL_SORT")
ip.add_index(field_name="region",      index_name="region_idx",      index_type="BITMAP")

client.create_collection(collection_name=COLLECTION, schema=schema,
                         index_params=ip, consistency_level="Strong")

# ---------- 3) insert（不给 sparse） ----------
rows = [{
    "chunk_id": "深入理解计算机系统::0",
    "dense": [0.01] * DIM,
    "text": ("Kapitel 3: Speicherhierarchie. 存储层次结构利用局部性原理，"
             "弥补处理器与内存之间的速度差距。Größe und Öffnungszeiten "
             "der Caches variieren je nach Prozessorgeneration."),
    "source_type": "pdf",
    "page_num": 42,
    "region": ["CN", "DE"],
}]
print(client.insert(collection_name=COLLECTION, data=rows))

client.load_collection(COLLECTION)

# ---------- 4) hybrid search ----------
query_text = "Speicherhierarchie 存储层次结构"
query_dense = [0.02] * DIM       # 换成真实 1024d embedding

FILTER = 'page_num >= 10 and ARRAY_CONTAINS_ANY(region, ["CN", "DE"])'

dense_req = AnnSearchRequest(data=[query_dense], anns_field=DENSE_FIELD,
                             param={"metric_type": "L2"}, limit=50, expr=FILTER)
sparse_req = AnnSearchRequest(data=[query_text], anns_field=SPARSE_FIELD,
                              param={"metric_type": "BM25"}, limit=50, expr=FILTER)

res = client.hybrid_search(
    collection_name=COLLECTION,
    reqs=[dense_req, sparse_req],
    ranker=RRFRanker(k=60),
    limit=10,
    output_fields=["chunk_id", "text", "source_type", "page_num", "region"],
)
for hits in res:
    for h in hits:
        print(f"{h['distance']:.6f}  {h['id']}  p{h['entity']['page_num']}")
```

---

*报告完成时间：调研覆盖 milvus-docs `v2.6.x`、pymilvus `2.6`/`master`、milvus `2.6`、zilliztech/tantivy。milvus.io 全程未使用（重定向失败）。*
