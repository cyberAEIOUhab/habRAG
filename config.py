"""
habRAG 配置
===========
所有**密钥**都从 .env 文件或环境变量读取，本文件里不出现任何明文密钥，
因此可以安全地提交到版本库。

密钥优先级：环境变量 > .env 文件 > 空值
（.env 加载器不会覆盖已存在的环境变量，便于临时覆盖或 CI）

首次使用：把 .env.example 复制为 .env 并填入密钥。
"""
import os

# ============================================================
# 极简 .env 加载器（不依赖 python-dotenv，避免 _libs 路径问题）
# ============================================================
def _load_dotenv(path):
    """逐行解析 KEY=VALUE。已存在的环境变量优先，不被覆盖。"""
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                # 去掉行尾注释（仅当 # 前面有空格时，避免误伤密钥里的 #）
                v = v.split(" #")[0].strip()
                v = v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
    except Exception as e:                      # 配置读取失败不应让程序起不来
        print("[config] 读取 .env 失败：%s" % e)


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(PROJECT_DIR, ".env")
_load_dotenv(ENV_PATH)


def _get(name, default=""):
    return os.environ.get(name, default).strip()


# ============================================================
# ★ 密钥（全部来自 .env / 环境变量，本文件不留明文）
# ============================================================
DEEPSEEK_API_KEY = _get("DEEPSEEK_API_KEY")
GLM_API_KEY = _get("GLM_API_KEY")
SILICONFLOW_API_KEY = _get("SILICONFLOW_API_KEY")
ZILLIZ_TOKEN = _get("ZILLIZ_TOKEN")

# 供启动时自检用：缺失会导致哪些功能不可用
_SECRET_HINTS = {
    "DEEPSEEK_API_KEY": "查询改写(A9)、回答生成、引用核对",
    "SILICONFLOW_API_KEY": "向量嵌入、精排(A8)",
    "GLM_API_KEY": "light 模式的排版修正（缺失不影响主流程）",
    "ZILLIZ_TOKEN": "云端向量库连接（BACKEND=zilliz 时必需）",
}


def missing_secrets():
    """返回当前缺失的密钥列表 [(名称, 影响说明), ...]，用于启动自检。"""
    out = []
    for name, hint in _SECRET_HINTS.items():
        if not globals().get(name):
            out.append((name, hint))
    return out


def check_secrets(verbose=True):
    """启动自检：打印缺失的密钥与影响，返回是否全部齐备。

    注意：GLM_API_KEY 只在 light 模式下用到，缺失不算致命。
    """
    fatal, optional = [], []
    for name, hint in missing_secrets():
        (optional if name == "GLM_API_KEY" else fatal).append((name, hint))
    if verbose:
        if not os.path.isfile(ENV_PATH):
            print("[config] 未找到 %s —— 请先复制 .env.example 为 .env 并填入密钥" % ENV_PATH)
        for name, hint in fatal:
            print("[config] ✗ 缺少 %s（%s）" % (name, hint))
        for name, hint in optional:
            print("[config] · 未设置 %s（%s）" % (name, hint))
        if not fatal and not optional:
            print("[config] 密钥齐备")
    return not fatal


# ============================================================
# 模型与端点（非密钥，可安全提交）
# ============================================================
DEEPSEEK_API_URL = _get("DEEPSEEK_API_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = _get("DEEPSEEK_MODEL", "deepseek-flash")           # 日常使用，速度快成本低
# DEEPSEEK_MODEL = "deepseek-v4-pro"                                # 需要深度分析时用这个
DEEPSEEK_MODEL_LIGHT = _get("DEEPSEEK_MODEL_LIGHT", "deepseek-flash")  # 轻量任务（片段排版/拼写修正）

# ===== 智谱 GLM（完全免费模型，light 模式的核对/排版任务使用）=====
GLM_BASE_URL = _get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
GLM_MODEL = _get("GLM_MODEL", "glm-4.7-flash")                      # 200K 上下文，API 免费

# ===== SiliconFlow (BAAI/bge-m3) Embedding 配置 =====
SILICONFLOW_BASE_URL = _get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
EMBEDDING_MODEL = _get("EMBEDDING_MODEL", "BAAI/bge-m3")            # 付费加速版：Pro/BAAI/bge-m3

# ===== 检索增强（A组）=====
RERANK_MODEL = _get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")      # SiliconFlow 精排（付费，按 token 计费）
RERANK_ENABLED = _get("RERANK_ENABLED", "true").lower() != "false"  # 粗检索后是否精排（失败自动降级）
HYBRID_SEARCH_ENABLED = _get("HYBRID_SEARCH_ENABLED", "true").lower() != "false"
QUERY_REWRITE_ENABLED = _get("QUERY_REWRITE_ENABLED", "true").lower() != "false"
RERANK_CANDIDATES = int(_get("RERANK_CANDIDATES", "30"))            # 送入 rerank 的候选片段数上限


# ============================================================
# 报刊语料（《新自由报》等）
# ============================================================
# 报刊的 chunk 用「系列名, YYYY-MM-DD」作 title（期号级），bookdata 里只有
# 一条系列条目（含 title_prefix），靠 get_book_meta 的前缀回退关联。
#
# ★ 检索默认**排除**报刊：报刊体量是其余语料的 10 倍以上（实测 162 chunk/期，
#   30 年约 175 万），纳入会稀释结果。是否开启由 **agent** 通过工具参数
#   include_press 决定，不是用户开关。
# ★ 但「列书目」类工具（list_books_by_filter / get_book_info）**不排除** ——
#   否则 agent 永远不知道库里有报刊，也就永远不会开启它。
PRESS_TITLE_PREFIXES = [p.strip() for p in
                        _get("HABRAG_PRESS_PREFIXES", "Neue Freie Presse").split("|")
                        if p.strip()]


# ============================================================
# 数据后端选择：本地 Chroma  ↔  Zilliz Cloud Serverless
# ============================================================
# "zilliz" = Zilliz Cloud Serverless（阿里云杭州）← 当前生产后端
# "chroma" = 本地 db/ 目录（原路径，保留作回滚）
#
# 改这里即可切换，也可用环境变量 / .env 覆盖（优先级更高）。
# 回滚到本地：改成 "chroma"。
BACKEND = _get("HABRAG_BACKEND", "zilliz").lower()

# 集群地址（不是密钥，但每个部署各不相同 —— 请在自己的 .env 里填）
# 格式：https://<cluster-id>.serverless.<region>.cloud.zilliz.com.cn
# 中国区 Serverless 目前仅阿里云华东1（杭州）可用。
# ★ 这里故意留空：公开仓库不应把某个人的集群写成默认值。
#   使用时在 .env 里设置 ZILLIZ_URI，否则 BACKEND="zilliz" 会因缺少地址而明确报错。
ZILLIZ_URI = _get("ZILLIZ_URI", "")
ZILLIZ_COLLECTION = _get("ZILLIZ_COLLECTION", "habsburg")

# 本地 Chroma 路径（回滚用，保留）
CHROMA_DB_PATH = _get("CHROMA_DB_PATH", os.path.join(PROJECT_DIR, "db"))
