#!/usr/bin/env python3
"""
验证「报刊默认排除」的完整链路
==============================
覆盖：is_press_title / build_where / where_to_expr / _meta_matches /
      get_book_meta 前缀回退 / search_chunks 端到端
"""
import os
import sys

ROOT = r'C:/Users/notch/Desktop/habRAG'
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, '_libs'))
os.chdir(ROOT)
os.environ['HABRAG_BACKEND'] = 'zilliz'

import config
import corpus_lib as C
from milvus_backend import where_to_expr
from pymilvus import MilvusClient

NFP = 'Neue Freie Presse, 1864-09-01'
RES = []


def check(name, fn):
    try:
        note = fn()
        RES.append((name, 'PASS', str(note or '')))
        print('  %-48s PASS  %s' % (name, note or ''))
    except Exception as e:
        RES.append((name, 'FAIL', '%s: %s' % (type(e).__name__, str(e)[:120])))
        print('  %-48s FAIL  %s: %s' % (name, type(e).__name__, str(e)[:120]))


def main():
    cli = MilvusClient(uri=config.ZILLIZ_URI, token=config.ZILLIZ_TOKEN)

    print('=' * 80)
    print('报刊默认排除 —— 完整链路验证')
    print('=' * 80)
    print()
    print('=== A. 纯函数层（不连库）===')

    def a1():
        assert C.is_press_title(NFP) is True
        assert C.is_press_title('Neue Freie Presse') is True
        assert C.is_press_title('Die Ministerratsprotokolle Österreichs 1848-1867') is False
        assert C.is_press_title('') is False
        assert C.is_press_title(None) is False
        return '前缀判定正确（含 None / 空串）'
    check('A1. is_press_title', a1)

    def a2():
        w = C.build_where(exclude_press=True)
        expr = where_to_expr(w)
        assert 'not (' in expr and 'like' in expr, expr
        return expr
    check('A2. build_where(exclude_press=True) → 表达式', a2)

    def a3():
        w = C.build_where(source_type='primary', exclude_press=True)
        expr = where_to_expr(w)
        assert 'source_type ==' in expr and 'not (' in expr, expr
        return expr
    check('A3. 与其它过滤条件组合', a3)

    def a4():
        w = C.build_where(exclude_press=False)
        assert w is None, w
        return 'exclude_press=False 且无其它条件 → None（不过滤）'
    check('A4. 不排除时不产生多余条件', a4)

    def a5():
        # _meta_matches 是本地 FTS5 腿的镜像，必须同步
        assert C._meta_matches({'title': NFP}, exclude_press=True) is False
        assert C._meta_matches({'title': NFP}, exclude_press=False) is True
        assert C._meta_matches({'title': 'Some Book'}, exclude_press=True) is True
        assert C._meta_matches({}, exclude_press=True) is True
        return '本地 FTS5 腿的镜像判定一致'
    check('A5. _meta_matches 同步（本地后端）', a5)

    print()
    print('=== B. bookdata 元数据回退 ===')

    def b1():
        bd = C.load_bookdata()
        hits = [b for b in bd if b.get('title_prefix')]
        assert len(hits) == 1, 'title_prefix 条目数 = %d' % len(hits)
        return 'bookdata 共 %d 条，带 title_prefix 的 %d 条' % (len(bd), len(hits))
    check('B1. bookdata 里有系列条目', b1)

    def b2():
        m = C.get_book_meta(NFP)
        assert m.get('author') != '未知', '回退失败: %s' % m.get('author')
        assert m.get('title') == 'Neue Freie Presse', m.get('title')
        return '期号级 title 回退到系列：author=%s' % m.get('author')[:30]
    check('B2. ★ get_book_meta 前缀回退', b2)

    def b3():
        m = C.get_book_meta('Die Ministerratsprotokolle Österreichs 1848-1867, Abteilung I, Band 1')
        assert m.get('author') and 'Akademie' in m.get('author', ''), m.get('author')
        return '普通书目仍精确命中：%s' % m.get('author')[:36]
    check('B3. 不破坏原有精确匹配', b3)

    def b4():
        m = C.get_book_meta('__不存在的书名__')
        assert m.get('author') == '未知'
        return '未命中仍返回占位数据（不抛错）'
    check('B4. 未命中时仍安全', b4)

    print()
    print('=== C. 端到端（连库）===')

    def c1():
        r = cli.query(config.ZILLIZ_COLLECTION, filter='', output_fields=['count(*)'])
        return '库内总数 %s' % r[0].get('count(*)')
    check('C1. 库内总数', c1)

    def c2():
        expr = where_to_expr(C.build_where(exclude_press=True))
        r = cli.query(config.ZILLIZ_COLLECTION, filter=expr, output_fields=['count(*)'])
        n = r[0].get('count(*)')
        assert n == 160475, '预期 160475，实际 %s' % n
        return '默认排除 → %d 条（正好是原有语料）' % n
    check('C2. ★ 默认排除报刊', c2)

    def c3():
        r = cli.query(config.ZILLIZ_COLLECTION, filter='title like "Neue Freie Presse%"',
                      output_fields=['count(*)'])
        return '报刊 %s 条' % r[0].get('count(*)')
    check('C3. 报刊条数', c3)

    def c4():
        """只出现在报刊文本里的 OCR 误拼词"""
        r = cli.search(config.ZILLIZ_COLLECTION, data=['Dänemart'], anns_field='sparse',
                       limit=10, filter='not (title like "Neue Freie Presse%")',
                       output_fields=['chunk_id'])
        assert len(r[0]) == 0, '默认排除后仍命中报刊：%d 条' % len(r[0])
        return '默认检索：Dänemart → 0 条（报刊已被挡住）'
    check('C4. ★ 稀疏检索同样被过滤', c4)

    def c5():
        r = cli.search(config.ZILLIZ_COLLECTION, data=['Dänemart'], anns_field='sparse',
                       limit=10, output_fields=['chunk_id', 'title'])
        hits = [h['entity'] for h in r[0]]
        nfp = [h for h in hits if str(h.get('title', '')).startswith('Neue Freie Presse')]
        assert len(nfp) > 0, '不过滤时也命不中 %d 条' % len(hits)
        return '不过滤：Dänemart → %d 条，其中报刊 %d 条' % (len(hits), len(nfp))
    check('C5. 不过滤时报刊可见', c5)

    print()
    print('=== D. search_chunks 端到端 ===')

    def d1():
        r = C.search_chunks(query='Dänemark Friedensverhandlungen',
                            n_results=10, use_rerank=False, use_rewrite=False)
        nfp = [c for c in r if str(c.get('title', '')).startswith('Neue Freie Presse')]
        assert len(nfp) == 0, '默认仍召回了 %d 条报刊' % len(nfp)
        return '默认：%d 条结果，报刊 0 条 ✅' % len(r)
    check('D1. ★ search_chunks 默认排除报刊', d1)

    def d2():
        r = C.search_chunks(query='Dänemark Friedensverhandlungen',
                            n_results=10, use_rerank=False, use_rewrite=False,
                            include_press=True)
        nfp = [c for c in r if str(c.get('title', '')).startswith('Neue Freie Presse')]
        assert len(nfp) > 0, '开启后仍召不回报刊（%d 条结果）' % len(r)
        return '开启：%d 条结果，报刊 %d 条 ✅' % (len(r), len(nfp))
    check('D2. ★ include_press=True 时能召回', d2)

    def d3():
        """报刊的引用标记与元数据"""
        r = C.search_chunks(query='Dänemark Friedensverhandlungen',
                            n_results=5, use_rerank=False, use_rewrite=False,
                            include_press=True)
        nfp = [c for c in r if str(c.get('title', '')).startswith('Neue Freie Presse')]
        if not nfp:
            raise AssertionError('没召回到报刊')
        c = nfp[0]
        m = C.get_book_meta(c['title'])
        return 'citation=%s | author=%s' % (c.get('citation'), str(m.get('author'))[:24])
    check('D3. 报刊片段的引用与元数据', d3)

    npass = sum(1 for r in RES if r[1] == 'PASS')
    print()
    print('=' * 80)
    print('通过 %d / 失败 %d' % (npass, len(RES) - npass))
    for n, s, note in RES:
        if s == 'FAIL':
            print('  [X] %s -> %s' % (n, note))
    print('=' * 80)
    return 0 if npass == len(RES) else 1


if __name__ == '__main__':
    sys.exit(main())
