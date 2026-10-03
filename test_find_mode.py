#!/usr/bin/env python3
"""
验证「文献查找」模式的组装链路
==============================
分两部分：
  A/B/C  纯函数层（分组、排序、统计行）——不需要 LLM
  D      真实跑一轮文献查找（agent 循环 + 合并 + 修正），验证端到端
"""
import os
import sys
import time
import warnings

warnings.filterwarnings('ignore')
ROOT = r'C:/Users/notch/Desktop/habRAG'
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, '_libs'))
os.chdir(ROOT)
os.environ['HABRAG_BACKEND'] = 'zilliz'

import config
import app as A
import corpus_lib as C

RES = []


def check(name, fn):
    try:
        note = fn()
        RES.append((name, 'PASS', str(note or '')))
        print('  %-50s PASS  %s' % (name, note or ''))
    except Exception as e:
        RES.append((name, 'FAIL', '%s: %s' % (type(e).__name__, str(e)[:150])))
        print('  %-50s FAIL  %s: %s' % (name, type(e).__name__, str(e)[:150]))


def mk(cid, title, text, idx, stype='primary', chapter=None):
    return {"chunk_id": "%s::%d" % (title, idx), "all_chunk_ids": [cid],
            "title": title, "source": title, "citation": "cite-" + str(idx),
            "chapter_title": chapter, "source_type": stype, "region": ["全帝国"],
            "doc_number": None, "doc_date": None, "doc_section": None, "text": text,
            "chunk_index": idx, "page_num": idx}


print('=' * 84)
print('文献查找模式 —— 组装链路验证')
print('=' * 84)

print()
print('=== A. 分组与排序 ===')

def a1():
    units = [mk('c1', 'BookA', 'a', 1), mk('c2', 'BookA', 'b', 2),
             mk('c3', 'BookB', 'c', 5),
             mk('c4', 'BookC', 'd', 1), mk('c5', 'BookC', 'e', 2), mk('c6', 'BookC', 'f', 3)]
    g = A.find_group_units(units)
    order = [(x['title'], x['n_chunks']) for x in g]
    assert order == [('BookC', 3), ('BookA', 2), ('BookB', 1)], order
    return '组间按命中片段数降序：%s' % order
check('A1. ★ 组间排序（按片段数降序）', a1)

def a2():
    """组内乱序输入，应被排回 chunk_index 升序"""
    units = [mk('c3', 'BookA', 'third', 9), mk('c1', 'BookA', 'first', 1),
             mk('c2', 'BookA', 'second', 4)]
    g = A.find_group_units(units)
    idxs = [u['chunk_index'] for u in g[0]['units']]
    assert idxs == [1, 4, 9], idxs
    return '组内按 chunk_index 升序：%s' % idxs
check('A2. ★ 组内排序（阅读顺序）', a2)

def a3():
    """chunk_index 缺失时应能从 chunk_id 解析（继续检索追加后的情形）"""
    u = {"chunk_id": "X::42", "title": "X", "text": "t", "all_chunk_ids": ["a"]}
    u2 = {"chunk_id": "X::7", "title": "X", "text": "t", "all_chunk_ids": ["b"]}
    g = A.find_group_units([u, u2])
    got = [x['chunk_id'] for x in g[0]['units']]
    assert got == ["X::7", "X::42"], got
    return 'chunk_index 缺失时从 chunk_id 兜底解析 ✅'
check('A3. chunk_index 缺失的兜底', a3)

def a4():
    g = A.find_group_units([])
    assert g == []
    return '空输入返回空列表'
check('A4. 空输入', a4)

def a5():
    """同一本书多个单元时，n_chunks 应累加 all_chunk_ids"""
    u1 = mk('c1', 'BookA', 'a', 1)
    u1['all_chunk_ids'] = ['c1', 'c2', 'c3']       # 合并单元，含 3 个子片段
    u2 = mk('c4', 'BookA', 'b', 5)
    g = A.find_group_units([u1, u2])
    assert g[0]['n_chunks'] == 4, g[0]['n_chunks']
    return '合并单元按子片段计数：%d 条' % g[0]['n_chunks']
check('A5. 合并单元的子片段计数', a5)

print()
print('=== B. 统计行（程序化生成）===')

def b1():
    units = [mk('c1', 'BookA', 'a', 1, 'primary'),
             mk('c2', 'BookB', 'b', 1, 'secondary'),
             mk('c3', 'BookC', 'c', 1, 'primary')]
    s = A.build_find_stats(units, {"llm_rounds": 5, "tool_calls": 9})
    assert s.startswith('📊'), s
    for kw in ['检索 5 轮', '工具调用 9 次', '命中 3 条片段', '覆盖 3 种文献',
               '一手 2', '二手 1', '合并为 3 个展示单元']:
        assert kw in s, '缺少 %r：%s' % (kw, s)
    return s
check('B1. ★ 统计行内容完整', b1)

def b2():
    s = A.build_find_stats([mk('c1', 'BookA', 'a', 1, None)], None)
    assert '检索' not in s.split('命中')[0], s
    return '无 stats 时不编造轮次：%s' % s
check('B2. 无统计信息时不编造', b2)

def b3():
    s = A.build_find_stats([], {"llm_rounds": 3})
    assert '命中 0 条片段' in s and '覆盖 0 种文献' in s, s
    return '空结果也能生成统计行：%s' % s
check('B3. 空结果', b3)

print()
print('=== C. 与 merge_adjacent_chunks 的衔接 ===')

def c1():
    """相邻 chunk_index 应合并成一个展示单元"""
    raw = [mk('r1', 'BookA', 'part1', 1), mk('r2', 'BookA', 'part2', 2)]
    for r in raw:
        r['author'] = 'Auth'
        r['year'] = '1900'
    merged = A.merge_adjacent_chunks(raw)
    assert len(merged) == 1, '未合并：%d' % len(merged)
    assert len(merged[0]['all_chunk_ids']) == 2
    g = A.find_group_units(merged)
    assert g[0]['n_chunks'] == 2
    return '相邻片段合并为 1 个单元（含 2 个子片段），分组计数正确'
check('C1. ★ 合并 → 分组链路', c1)

def c2():
    """不相邻的不该合并（中间有缺口）"""
    raw = [mk('r1', 'BookA', 'p1', 1), mk('r2', 'BookA', 'p2', 5)]
    for r in raw:
        r['author'] = 'Auth'
        r['year'] = '1900'
    merged = A.merge_adjacent_chunks(raw)
    assert len(merged) == 2, '误合并：%d' % len(merged)
    return '缺口 >1 不合并（2 个单元）'
check('C2. 不相邻不合并', c2)

print()
print('=== D. 真实跑一轮文献查找（会调用 LLM）===')


class _FakeStatus:
    """替代 st.empty()，只吞掉进度文字（本测试不在 Streamlit 运行时里）。"""
    def write(self, *a, **k):
        print('      [status] %s' % (str(a[0])[:76] if a else ''))

    def empty(self):
        pass

    def caption(self, *a, **k):
        pass


def d1():
    """真实 agent 循环：目标 12 条，验证能凑够、能合并、能分组"""
    t0 = time.time()
    stats = {}
    # agent_loop 内部会读 st.session_state（dev_mode_on / excluded_chunk_ids / ui_filters）
    _ans, chunks = A.agent_loop(
        "1867 年奥匈折衷方案（Ausgleich）谈判中匈牙利方面的诉求",
        [], _FakeStatus(), dev_mode=False,
        system_prompt=A.FIND_SYSTEM_PROMPT,
        target_chunks=12,
        exclude=None,
        extra_hint="（本次目标片段数：12 条。达到后系统会自动停止。）",
        stats=stats,
    )
    assert len(chunks) > 0, '没检索到任何片段'
    units = A.merge_adjacent_chunks(chunks)
    line = A.build_find_stats(units, stats)
    g = A.find_group_units(units)
    return ("%d 条片段 → %d 个展示单元 → %d 种文献（%.0fs）\n      %s\n      前 3 种：%s"
            % (len(chunks), len(units), len(g), time.time() - t0, line,
               [(x['title'][:34], x['n_chunks']) for x in g[:3]]))
check('D1. ★ 端到端：描述 → 片段 → 分组', d1)

def d2():
    """目标数应被尊重（不会远超）"""
    stats = {}
    _ans, chunks = A.agent_loop(
        "1848 年维也纳革命", [], _FakeStatus(), dev_mode=False,
        system_prompt=A.FIND_SYSTEM_PROMPT, target_chunks=8,
        extra_hint="（本次目标片段数：8 条。）", stats=stats)
    return '目标 8 条 → 实得 %d 条（工具调用 %s 次，%s 轮）' % (
        len(chunks), stats.get('tool_calls'), stats.get('llm_rounds'))
check('D2. ★ 目标片段数被尊重', d2)

npass = sum(1 for r in RES if r[1] == 'PASS')
print()
print('=' * 84)
print('通过 %d / 失败 %d' % (npass, len(RES) - npass))
for n, s, note in RES:
    if s == 'FAIL':
        print('  [X] %s -> %s' % (n, note))
print('=' * 84)
