"""清理指定书目的残留 chunk。

★ 后端由 config.BACKEND 决定（chroma 本地 / zilliz 云端）——
   不要在这里直接建 Chroma 客户端，否则会绕过 BACKEND 开关。

★ 必须有 __main__ 保护：本文件会**真的删除数据**，
   没有保护时任何 `import clean` 都会静默执行删除。
"""
from corpus_lib import get_collection

TARGETS = [
    "The Economics of World War I",
    "Paris 1919: Six Months that Changed the World",
]


def main():
    collection = get_collection()
    for title in TARGETS:
        before = collection.get(where={"title": title}, include=[])
        n = len(before["ids"])
        if n > 0:
            collection.delete(where={"title": title})
            print(f"已清理《{title}》残留的{n}个chunk")
        else:
            print(f"《{title}》未发现残留数据")


if __name__ == "__main__":
    main()
