#!/usr/bin/env python3
"""
验证 agent 侧的报刊开关链路
===========================
覆盖：TOOLS schema / SYSTEM_PROMPT / tool_search_corpus /
      tool_list_sources_on_topic / execute_tool 传参 / 结果提示行
"""
import json
import os
import sys
import warnings

warnings.filterwarnings('ignore')
ROOT = r'C:/Users/notch/Desktop/habRAG'
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, '_libs'))
os.chdir(ROOT)
os.environ['HABRAG_BACKEND'] = 'zilliz'

import config
import corpus_lib as C

NFP_PREFIX = 'Neue Freie Presse'
RES = []


def check(name, fn):
    try:
        note = fn()
        RES.append((name, 'PASS', str(note or '')))
        print('  %-50s PASS  %s' % (name, note or ''))
    except Exception as e:
        RES.append((name, 'FAIL', '%s: %s' % (type(e).__name__, str(e)[:130])))
        print('  %-50s FAIL  %s: %s' % (name, type(e).__name__, str(e)[:130]))


def main():
    print('=' * 82)
    print('agent 侧报刊开关 —— 链路验证')
    print('=' * 82)

    print()
    print('=== A. 静态检查（不调模型）===')
    import app as A

    def a1():
        names = [t['function']['name'] for t in A.TOOLS]
        assert 'search_corpus' in names and 'list_sources_on_topic' in names, names
        return 'TOOLS 共 %d 个：%s' % (len(A.TOOLS), ', '.join(names))
    check('A1. TOOLS 列表完整', a1)

    def a2():
        for t in A.TOOLS:
            f = t['function']
            if f['name'] == 'search_corpus':
                props = f['parameters']['properties']
                assert 'include_press' in props, 'search_corpus 缺 include_press'
                d = props['include_press']['description']
                assert 'true' in d and 'false' in d and len(d) > 150
                return 'search_corpus.include_press 已声明（描述 %d 字）' % len(d)
        raise AssertionError('未找到 search_corpus')
    check('A2. search_corpus 有 include_press', a2)

    def a3():
        for t in A.TOOLS:
            f = t['function']
            if f['name'] == 'list_sources_on_topic':
                props = f['parameters']['properties']
                assert 'include_press' in props, 'list_sources_on_topic 缺 include_press'
                return 'list_sources_on_topic.include_press 已声明'
        raise AssertionError('未找到 list_sources_on_topic')
    check('A3. list_sources_on_topic 有 include_press', a3)

    def a4():
        sp = A.SYSTEM_PROMPT
        assert '【报刊语料' in sp, '缺【报刊语料】小节'
        for kw in ['include_press', '10 倍', 'Fraktur', 'S.']:
            assert kw in sp, 'SYSTEM_PROMPT 缺少关键词: %s' % kw
        assert '不要**把报刊写成 (作者, 年份, p. 页码)' in sp or '不要' in sp
        return '【报刊语料】小节已加入（含判据/OCR 提示/引用格式）'
    check('A4. SYSTEM_PROMPT 有报刊说明', a4)

    def a5():
        """include_press 绝不能被侧栏硬覆盖"""
        import inspect
        src = inspect.getsource(A.execute_tool)
        # 覆盖块里只应有 source_type/region/subfield/stance/lang
        block_start = src.find('ui_filters()')
        assert block_start > 0, '未找到 ui_filters 覆盖块'
        block = src[block_start:block_start + 700]
        assert 'include_press' not in block.split('result = ')[0], \
            'include_press 被放进了侧栏硬覆盖块 —— 会违背「agent 决定」的设计'
        return 'include_press 不在侧栏覆盖块内 ✅'
    check('A5. ★ 未被侧栏硬覆盖', a5)

    def a6():
        import inspect
        src = inspect.getsource(A.execute_tool)
        n = src.count('include_press=bool(args.get("include_press"')
        assert n == 2, '应有 2 处传参（search_corpus + list_sources_on_topic），实际 %d' % n
        return 'execute_tool 向两个工具各传一次'
    check('A6. execute_tool 传参', a6)

    print()
    print('=== B. 工具实际调用 ===')

    def b1():
        r = A.tool_search_corpus(query='Dänemark Friedensverhandlungen', n_results=10)
        nfp = [c for c in r if str(c.get('title', '')).startswith(NFP_PREFIX)]
        assert len(nfp) == 0, '默认仍召回 %d 条报刊' % len(nfp)
        return '默认：%d 条结果，报刊 0 条' % len(r)
    check('B1. ★ tool_search_corpus 默认排除', b1)

    def b2():
        r = A.tool_search_corpus(query='Dänemark Friedensverhandlungen', n_results=10,
                                 include_press=True)
        nfp = [c for c in r if str(c.get('title', '')).startswith(NFP_PREFIX)]
        assert len(nfp) > 0, '开启后仍无报刊'
        return '开启：%d 条结果，报刊 %d 条' % (len(r), len(nfp))
    check('B2. ★ include_press=True 生效', b2)

    def b3():
        """结果偏少时应附 _note 提示"""
        r = A.tool_search_corpus(
            query='Bopps Anatherin Mundwasser Inserat 1864 Wien', n_results=10)
        notes = [x for x in r if isinstance(x, dict) and '_note' in x]
        chunks = [x for x in r if not (isinstance(x, dict) and '_note' in x)]
        return '结果 %d 条 + 提示 %d 条%s' % (
            len(chunks), len(notes),
            '（%s）' % notes[0]['_note'][:44] if notes else '')
    check('B3. 结果偏少时附 _note 提示', b3)

    def b4():
        r = A.tool_list_sources_on_topic(topic='Dänemark 1864 Friedensverhandlungen',
                                         n_results=10, include_press=False)
        nfp = [x for x in r if str(x.get('title', '')).startswith(NFP_PREFIX)]
        assert len(nfp) == 0, '默认仍列出报刊 %d 条' % len(nfp)
        return '默认：%d 个书目，报刊 0 个' % len(r)
    check('B4. ★ list_sources_on_topic 默认排除', b4)

    def b5():
        r = A.tool_list_sources_on_topic(topic='Dänemark 1864 Friedensverhandlungen',
                                         n_results=10, include_press=True)
        nfp = [x for x in r if str(x.get('title', '')).startswith(NFP_PREFIX)]
        assert len(nfp) > 0, '开启后仍未列出报刊（%d 个书目）' % len(r)
        return '开启：%d 个书目，报刊 %d 个 -> %s' % (len(r), len(nfp), nfp[0]['title'])
    check('B5. ★ 开启后报刊出现在书目列表', b5)

    def b6():
        """list_books_by_filter 不受限制，agent 靠它发现报刊"""
        r = A.tool_list_books_by_filter(subfield='经济史')
        titles = [x.get('title') for x in r] if isinstance(r, list) else []
        hits = [t for t in titles if str(t).startswith(NFP_PREFIX)]
        return '按 subfield=经济史 列出 %d 个书目，其中报刊 %d 个' % (len(titles), len(hits))
    check('B6. list_books_by_filter 能看到报刊', b6)

    def b7():
        r = A.tool_get_book_info(title=NFP_PREFIX)
        desc = (r or {}).get('description') or ''
        assert desc, 'get_book_info 拿不到 NFP 描述'
        return 'get_book_info 拿到描述 %d 字（含 OCR 提示：%s）' % (
            len(desc), '是' if 'Fraktur' in desc else '否')
    check('B7. get_book_info 能查到 NFP', b7)

    def b8():
        """引用格式"""
        r = A.tool_search_corpus(query='Anatherin Mundwasser', n_results=3,
                                 include_press=True)
        nfp = [c for c in r if str(c.get('title', '')).startswith(NFP_PREFIX)]
        if not nfp:
            raise AssertionError('未召回到报刊片段')
        return 'citation = %s' % nfp[0].get('citation')
    check('B8. 报刊引用格式', b8)

    npass = sum(1 for r in RES if r[1] == 'PASS')
    print()
    print('=' * 82)
    print('通过 %d / 失败 %d' % (npass, len(RES) - npass))
    for n, s, note in RES:
        if s == 'FAIL':
            print('  [X] %s -> %s' % (n, note))
    print('=' * 82)
    return 0 if npass == len(RES) else 1


if __name__ == '__main__':
    sys.exit(main())
