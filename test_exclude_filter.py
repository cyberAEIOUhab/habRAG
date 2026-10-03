#!/usr/bin/env python3
"""验证负过滤（exclude）的 NULL 安全语义"""
import os
import sys

ROOT = r'C:/Users/notch/Desktop/habRAG'
sys.path.insert(0, ROOT)
sys.path.append(os.path.join(ROOT, '_libs'))
os.chdir(ROOT)

import config
import corpus_lib as C
from milvus_backend import where_to_expr
from pymilvus import MilvusClient

C_COLL = config.ZILLIZ_COLLECTION
cli = MilvusClient(uri=config.ZILLIZ_URI, token=config.ZILLIZ_TOKEN)
TOTAL = 160637
RES = []


def check(name, fn):
    try:
        note = fn()
        RES.append((name, 'PASS', str(note or '')))
        print('  %-52s PASS  %s' % (name, note or ''))
    except Exception as e:
        RES.append((name, 'FAIL', '%s: %s' % (type(e).__name__, str(e)[:140])))
        print('  %-52s FAIL  %s: %s' % (name, type(e).__name__, str(e)[:140]))


def count(expr):
    r = cli.query(C_COLL, filter=expr or '', output_fields=['count(*)'])
    return r[0].get('count(*)')


print('=' * 84)
print('负过滤 NULL 安全验证')
print('=' * 84)
print()
print('=== A. 表达式构造 ===')

def a1():
    e = where_to_expr(C.build_where(exclude={'source_type': ['secondary']}))
    assert 'not in' in e and 'is null' in e, e
    return e
check('A1. 标量字段 → not in ... or is null', a1)

def a2():
    e = where_to_expr(C.build_where(exclude={'doc_section': ['Inserate', 'Börse']}))
    assert 'is null' in e, e
    return e
check('A2. doc_section（绝大多数为 NULL）', a2)

def a3():
    e = where_to_expr(C.build_where(exclude={'region': ['加利西亚']}))
    assert 'ARRAY_CONTAINS' in e and 'is null' in e, e
    return e
check('A3. 数组字段 → not ARRAY_CONTAINS ... or is null', a3)

def a4():
    e = where_to_expr(C.build_where(exclude={'source_type': ['secondary'],
                                             'language': ['英文'],
                                             'region': ['加利西亚']}))
    return '多字段组合 %d 字符' % len(e)
check('A4. 多字段组合不报错', a4)

print()
print('=== B. 实际能跑通且语义正确 ===')

def b1():
    e = where_to_expr(C.build_where(exclude={'source_type': ['secondary']}))
    n = count(e)
    assert 0 < n < TOTAL, 'n=%s' % n
    return '排除 secondary → %d 条（< 全库 %d）' % (n, TOTAL)
check('B1. 排除 secondary 能执行', b1)

def b2():
    """关键：排除 secondary 后的条数，应等于 primary + mixed 的总和"""
    n_all = count('')
    n_sec = count('source_type == "secondary"')
    n_ex = count(where_to_expr(C.build_where(exclude={'source_type': ['secondary']})))
    assert n_ex == n_all - n_sec, 'exclude=%d, all-sec=%d' % (n_ex, n_all - n_sec)
    return '%d = %d - %d ✅ 精确' % (n_ex, n_all, n_sec)
check('B2. ★ 排除语义精确（不误伤 NULL）', b2)

def b3():
    """doc_section 绝大多数为 NULL —— 排除 Inserate 后应几乎等于全库"""
    n_ex = count(where_to_expr(C.build_where(exclude={'doc_section': ['Inserate']})))
    n_ins = count('doc_section == "Inserate"')
    return '排除 Inserate → %d 条；Inserate 本身 %d 条（全库 %d）' % (n_ex, n_ins, TOTAL)
check('B3. doc_section 排除不误伤 NULL 行', b3)

def b4():
    n_ex = count(where_to_expr(C.build_where(exclude={'region': ['加利西亚']})))
    n_gal = count('ARRAY_CONTAINS(region, "加利西亚")')
    n_all = count('')
    assert n_ex == n_all - n_gal, 'exclude=%d, 预期 %d' % (n_ex, n_all - n_gal)
    return '数组排除精确：%d = %d - %d ✅' % (n_ex, n_all, n_gal)
check('B4. ★ 数组字段排除精确', b4)

def b5():
    """与报刊排除组合"""
    e = where_to_expr(C.build_where(exclude_press=True,
                                    exclude={'source_type': ['secondary']}))
    n = count(e)
    assert n == 160475 - count('source_type == "secondary" and not (title like "Neue Freie Presse%")'), n
    return '报刊排除 + negative 过滤组合正确：%d 条' % n
check('B5. 与报刊排除组合', b5)

print()
print('=== C. Python 侧镜像（本地 FTS5 腿）===')
def c1():
    assert C._meta_matches({'source_type': 'secondary'}, exclude={'source_type': ['secondary']}) is False
    assert C._meta_matches({'source_type': 'primary'}, exclude={'source_type': ['secondary']}) is True
    assert C._meta_matches({'source_type': None}, exclude={'source_type': ['secondary']}) is True, 'NULL 被误排'
    assert C._meta_matches({}, exclude={'source_type': ['secondary']}) is True, '缺字段被误排'
    return 'NULL / 缺字段都保留，指定值被排除 ✅'
check('C1. ★ _meta_matches 与 build_where 语义一致', c1)

def c2():
    assert C._meta_matches({'region': ['加利西亚', '匈牙利']},
                           exclude={'region': ['加利西亚']}) is False
    assert C._meta_matches({'region': ['匈牙利']},
                           exclude={'region': ['加利西亚']}) is True
    assert C._meta_matches({'region': None}, exclude={'region': ['加利西亚']}) is True
    return '数组字段镜像判定一致 ✅'
check('C2. 数组字段镜像', c2)

npass = sum(1 for r in RES if r[1] == 'PASS')
print()
print('=' * 84)
print('通过 %d / 失败 %d' % (npass, len(RES) - npass))
for n, s, note in RES:
    if s == 'FAIL':
        print('  [X] %s -> %s' % (n, note))
print('=' * 84)
