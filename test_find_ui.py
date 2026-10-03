#!/usr/bin/env python3
"""
用 Streamlit AppTest 真实跑一遍 app.py，验证 UI 无异常。

注意两点：
  1. 不改动 sessions/ 里的真实会话文件 —— 只把 session_state["messages"] 置空，
     并同步 loaded_session，让 app 跳过从磁盘加载那一步。
  2. AppTest 自身处理不了 st.feedback（ButtonGroupProto 的 value 为 None 时
     element_tree.py:730 会崩），所以必须先清空历史消息再切模式。
"""
import os
import sys
import warnings

warnings.filterwarnings('ignore')
ROOT = r'C:/Users/notch/Desktop/habRAG'
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, '_libs'))
os.chdir(ROOT)
os.environ['HABRAG_BACKEND'] = 'zilliz'

from streamlit.testing.v1 import AppTest

import streamlit as _st

# ★ AppTest 自身处理不了 st.feedback：它的 ButtonGroupProto 在未交互时 value 为 None，
#   element_tree.py 的 indices 属性会 TypeError。而 get_widget_states() 在每次 .run()
#   之前都会遍历上一轮的整棵树，所以只要历史里有 feedback 就寸步难行。
#   这里在**测试进程内**把它换成空操作（app.py 里 `import streamlit as st` 拿到的是
#   同一个模块对象，因此同样被替换）；不影响真实运行时。
_st.feedback = lambda *a, **k: None

RES = []
_AT = {}


def check(name, fn):
    try:
        note = fn()
        RES.append((name, 'PASS', str(note or '')))
        print('  %-50s PASS  %s' % (name, note or ''))
    except Exception as e:
        RES.append((name, 'FAIL', '%s: %s' % (type(e).__name__, str(e)[:170])))
        print('  %-50s FAIL  %s: %s' % (name, type(e).__name__, str(e)[:170]))


def fresh():
    """新开一个 AppTest，并清空历史消息（不动磁盘上的会话文件）。"""
    at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=300)
    at.run()
    at.session_state['messages'] = []
    # AppTest 的 session_state 代理没有 .get()，只能先 in 判断
    if 'current_session' in at.session_state:
        at.session_state['loaded_session'] = at.session_state['current_session']
    at.run()
    return at


def switch(at, mode):
    r = next(x for x in at.radio if '模式' in str(x.label))
    r.set_value(mode)
    at.run()
    return at


print('=' * 86)
print('Streamlit AppTest —— 真实渲染验证')
print('=' * 86)
print()

print('=== A. 默认模式（应为文献查找）===')


def a1():
    at = fresh()
    _AT['v'] = at
    assert not at.exception, '渲染抛异常：%s' % [str(e.value)[:200] for e in at.exception]
    return 'app.py 无异常渲染（%d 个 widget）' % (
        len(at.radio) + len(at.multiselect) + len(at.selectbox) + len(at.button))
check('A1. 应用渲染无异常', a1)


def a2():
    r = next(x for x in _AT['v'].radio if '模式' in str(x.label))
    assert r.options == ['文献查找', '深度分析', '长文本分析'], r.options
    assert r.value == '文献查找', '默认不是文献查找：%s' % r.value
    return '模式 radio = %s，默认 %s' % (r.options, r.value)
check('A2. ★ 三选一 + 默认文献查找', a2)


def a3():
    labels = [str(m.label) for m in _AT['v'].multiselect]
    for kw in ['排除史料类型', '排除语言', '排除学科视角', '排除地区', '排除史学立场', '排除具体书目']:
        assert kw in labels, '缺少 %r；现有 %s' % (kw, labels)
    return '负过滤面板 6 项齐全'
check('A3. ★ 负过滤面板渲染', a3)


def a4():
    n = _AT['v'].multiselect[0].options
    assert n, '排除史料类型的候选为空'
    return '「排除史料类型」候选 %d 个：%s' % (len(n), n)
check('A4. 候选值非空', a4)


def a5():
    caps = ' '.join(str(c.value) for c in _AT['v'].caption)
    assert '默认收录全部来源' in caps, caps[:200]
    return '排除条件说明已显示'
check('A5. 说明文案', a5)


def a6():
    labels = [str(s.label) for s in _AT['v'].selectbox]
    assert '史料类型' not in labels, '文献查找模式下不该出现正过滤面板：%s' % labels
    assert any('描述你要找的内容' in str(t.label) for t in _AT['v'].text_input), \
        '缺少查找输入框'
    return '正过滤面板已隐藏，查找输入框存在 ✅'
check('A6. ★ 两套过滤不混淆', a6)


def a7():
    labels = [str(s.label) for s in _AT['v'].text_input]
    return '输入框：%s' % labels
check('A7. 文献查找的输入框', a7)


print()
print('=== B. 切到深度分析 ===')


def b1():
    at = switch(_AT['v'], '深度分析')
    _AT['v'] = at
    assert not at.exception, '切换抛异常：%s' % [str(e.value)[:200] for e in at.exception]
    return '切换无异常'
check('B1. 切换模式', b1)


def b2():
    labels = [str(s.label) for s in _AT['v'].selectbox]
    assert '史料类型' in labels, '深度模式应显示正过滤面板；现有：%s' % labels
    return '正过滤面板恢复：%s' % labels[:4]
check('B2. ★ 深度模式仍是正过滤', b2)


def b3():
    labels = [str(b.label) for b in _AT['v'].button]
    hit = [x for x in labels if '继续对话' in x]
    assert hit, '深度模式应有「继续对话」按钮；现有：%s' % labels[:12]
    return '「继续对话」已在深度模式：%s' % hit
check('B3. ★ 继续对话已移植到深度模式', b3)


def b4():
    labels = [str(m.label) for m in _AT['v'].multiselect]
    assert '排除史料类型' not in labels, '深度模式不该出现负过滤面板：%s' % labels
    return '负过滤面板已隐藏 ✅'
check('B4. 负过滤面板正确隐藏', b4)


print()
print('=== C. 切到长文本分析 ===')


def c1():
    at = switch(_AT['v'], '长文本分析')
    _AT['v'] = at
    assert not at.exception, '切换抛异常：%s' % [str(e.value)[:200] for e in at.exception]
    return '切换无异常'
check('C1. 切换模式', c1)


def c2():
    areas = [str(a.label) for a in _AT['v'].text_area]
    assert any('长文本' in x for x in areas), '应有长文本输入框；现有：%s' % areas
    return '长文本输入框：%s' % areas
check('C2. 长文本输入框', c2)


print()
print('=== D. 切回文献查找 ===')


def d1():
    at = switch(_AT['v'], '文献查找')
    _AT['v'] = at
    assert not at.exception
    labels = [str(m.label) for m in at.multiselect]
    assert '排除史料类型' in labels, labels
    return '切回后负过滤面板恢复 ✅'
check('D1. 模式可来回切换', d1)


def d2():
    """确认测试没有往 sessions/ 写入新文件"""
    d = os.path.join(ROOT, 'sessions')
    n = len([f for f in os.listdir(d) if f.endswith('.jsonl')])
    assert n <= 4, 'sessions 目录多出了文件（测试污染）：%d 个' % n
    return 'sessions/ 未新增文件（%d 个会话）' % n
check('D2. ★ 未污染真实会话', d2)


npass = sum(1 for r in RES if r[1] == 'PASS')
print()
print('=' * 86)
print('通过 %d / 失败 %d' % (npass, len(RES) - npass))
for n, s, note in RES:
    if s == 'FAIL':
        print('  [X] %s -> %s' % (n, note))
print('=' * 86)
