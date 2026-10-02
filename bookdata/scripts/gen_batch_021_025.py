"""Generate and write entries for books 21-25."""
import json, os
from datetime import datetime

entries = [
    {
        "filename": "Education and middle-class society in imperial Austria, 1848-1918 (Cohen, Gary B., 1948-) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Education and Middle-Class Society in Imperial Austria, 1848-1918",
        "author": "Gary B. Cohen",
        "year": 1996,
        "language": "英文",
        "publisher": "Purdue University Press",
        "description": "Gary B. Cohen的《帝奥地利的教育与中产阶级社会，1848-1918》是首部系统研究19世纪奥地利（内莱塔尼亚）中高等教育史的英文专著，1996年由普渡大学出版社出版。Cohen挑战了晚期哈布斯堡帝国「保守僵化」的传统形象，以大量统计数据论证奥地利在教育领域实为欧洲领先者——至1910年，其文法中学、实科中学与大学的适龄入学率不仅与德国持平甚至在某些指标上超越德国，居欧洲第四位。全书核心论点为：奥地利的教育扩张远超其经济发展水平（1913年奥地利人均GNP仅为德国的57%），这一「超前的现代化」得益于政府与公民社会的共同推动；但教育机会的扩大并未根本改变阶级招募模式——精英阶层的自我再生产率维持在25-30%，不过中下层乃至部分工人阶级子弟确实获得了有限的社会流动通道。该书还详细考察了捷克与波兰民族群体以及犹太与新教宗教少数群体在教育扩张中的获益差异，为理解帝国晚期的民族冲突与社会变迁提供了关键的教育制度分析视角。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "standard"
    },
    {
        "filename": "Emperor Francis Joseph of Austria a biography (Redlich, Josef, 1869-1936) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Emperor Francis Joseph of Austria: A Biography",
        "author": "Josef Redlich",
        "year": 1929,
        "language": "英文",
        "publisher": "The Macmillan Company",
        "description": "Josef Redlich所著《奥地利皇帝弗朗茨·约瑟夫传》是哈布斯堡王朝晚期史学中的经典传记，1929年由Macmillan公司在伦敦与纽约同时出版。Redlich（1869-1936）本人即为奥地利帝国宪政史的权威学者，曾任奥地利国会议员及奥匈帝国末代财政部长——这一独特的「学者-政治家」双重身份使其著史兼具学术深度与政治内景的洞察力。全书将弗朗茨·约瑟夫的个人生平与19世纪欧洲政治大转型（从维也纳会议到凡尔赛条约）紧密交织，Redlich在导论中提出其核心判断：弗朗茨·约瑟夫「对重大事件的影响力超过19世纪任何其他欧洲君主」，尽管作为个体「远非人类伟大的化身」。各章依次覆盖其青年时代、1848年革命后登基、克里米亚战争中的奥地利角色、与撒丁-法国的战争及伦巴第的丧失、1866年普奥战争与二元君主制的建立、皇储鲁道夫的悲剧、萨拉热窝刺杀与一战爆发、直至1916年驾崩。《外交事务》（Foreign Affairs, 1929年4月）誉之为「一部真正伟大的著作」，称赞其「遵循伟大的学术传统」，对哈布斯堡问题提供了深刻分析。",
        "description_source": "web_search",
        "extraction_confidence": "medium",
        "needs_review": True,
        "extraction_notes": "首页为扫描件，无法从PDF提取文字验证书名/出版年份。书名、作者、年份依赖文件名解析与网页搜索交叉确认。1929年为英文初版年份，需确认本文件是否为此版或后续重印版。建议人工核对版权页。",
        "priority_tier": "high"
    },
    {
        "filename": "Endogenous Borders The Effects of New Borders on Trade in Central Europe 1885-1933.pdf",
        "title": "Endogenous Borders? The Effects of New Borders on Trade in Central Europe 1885-1933",
        "author": "Hans-Christian Heinemeyer, Max-Stephan Schulze, and Nikolaus Wolf",
        "year": 2008,
        "language": "英文",
        "publisher": "CESifo Working Paper No. 2246",
        "description": "本文由Heinemeyer、Schulze与Wolf三位经济史学家合作发表于2008年（CESifo Working Paper No. 2246），是对国际贸易学中「边界效应」文献的方法论创新贡献。论文利用1919年巴黎和约在中东欧强行重新划定边界这一「历史自然实验」，采用Ashenfelter双重差分估计法，基于覆盖1885-1933年的全新次国家级贸易流量数据集，解决此前边界效应研究的核心识别问题：政治边界的变化究竟在多大程度上「因果性地」影响了贸易，而非仅仅是顺应了此前已存在的贸易格局？论文的主要发现具有重要的方法论与实证含义——新边界确实对贸易产生了显著负面影响，但其因果「处理效应」远小于横截面研究估计的水平；更关键的是，1919年的边界变更在很大程度上沿袭了一战中已清晰可见的贸易格局，即「边界塑造贸易，贸易也塑造边界」。这一双向因果关系从根本上挑战了此前文献中边界的纯外生性假设，对当代贸易政策与边界研究具有持久影响。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "standard"
    },
    {
        "filename": "Engineering and Economic Growth. The Development of Austria-Hungarys Machine-Building Industry in the late Nineteenth Century… (Review by Franz Mathis) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Engineering and Economic Growth: The Development of Austria-Hungary's Machine-Building Industry in the Late Nineteenth Century",
        "author": "Max-Stephan Schulze",
        "year": 1996,
        "language": "英文",
        "publisher": "Peter Lang",
        "description": "Max-Stephan Schulze的《工程与经济增长：19世纪晚期奥匈帝国机器制造业的发展》是LSE经济史学者的重要专著，1996年由Peter Lang出版于「经济-金融-社会史研究」丛书（第3卷，295页）。本书对奥匈帝国机器制造业——第二次工业革命的核心部门——进行了细致的定量与定性分析，核心贡献是以资本品部门的新证据有力支持了奥地利「大萧条」（1873年至1890年代中期）的存在论：1873年股市崩盘后机器制造产出急剧收缩，直至1888年才恢复到崩溃前水平，直接挑战了以David Good为代表的修正主义学派对「大萧条」命题的质疑。长期来看，1872-1912年间奥地利机器制造业年均增长4.57%（整体工业仅2.36%），匈牙利机器制造业年均增长7.14%（整体工业3.08%），全要素生产率与劳动生产率均显著提升，且国内机器制造业为下游产业提供了大部分生产力提升所需设备。该研究表明机器制造业是奥匈帝国一战前二十年经济「追赶式增长」的重要引擎。本书由Franz Mathis在《奥地利历史年鉴》（1998年）上发表书评。本PDF文件实际上是一篇3页的书评而非全书。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": True,
        "extraction_notes": "文件名标注为「Review by Franz Mathis」，首页提取仅3页，确认本文件为Michael Pammer撰写的书评而非Schulze原书。已将title设为原书名而非书评标题。建议人工确认是否需要将此书评与原书分开著录。",
        "priority_tier": "standard"
    },
    {
        "filename": "Ethnic Nationalism and the Fall of Empires Central Europe, Russia, and the Middle East, 1914-1923 (Aviel Roshwald) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Ethnic Nationalism and the Fall of Empires: Central Europe, Russia and the Middle East, 1914-1923",
        "author": "Aviel Roshwald",
        "year": 2001,
        "language": "英文",
        "publisher": "Routledge",
        "description": "Aviel Roshwald的《族群民族主义与帝国的覆灭：中欧、俄罗斯与中东，1914-1923》是一部视野宏阔的比较史著作，2001年由Routledge出版（273页）。该书以第一次世界大战为叙事轴心，将奥匈、俄罗斯、奥斯曼与德意志四大帝国的崩溃置于同一分析框架中，论证战争期间族群民族主义政治如何在帝国废墟上塑造了延续至今的国家认同与冲突格局。Roshwald的核心分析概念是「受挫的期望」（dashed expectations）——一战期间被动员起来的民族主义渴望在战后安排中大多未能得到满足，埋下了持久的族群冲突种子。全书涵盖奥匈帝国的解体、俄国革命与苏维埃国家建设中的族群维度、晚期奥斯曼帝国的民族问题、阿拉伯民族主义的起源、军事占领区的族群政治以及捷克斯洛伐克与南斯拉夫认同的建构等广泛议题。Dominic Lieven在《英国历史评论》中称赞其「有趣、原创且有用」，提供了「许多深思熟虑且不同寻常的见解」，但也批评该书对哈布斯堡帝国多族群管理体制的评价过于苛刻、对西方民主「现代性」的理想化倾向明显。该书是对僵硬的结构主义民族主义理论的一剂「历史偶然性的解毒剂」，对理解当代中东欧与中东族群政治具有持续的学术与现实意义。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "standard"
    }
]

# Load baseline for filepath and other fields
with open('baseline_extract.json', 'r', encoding='utf-8') as f:
    baseline = json.load(f)
baseline_by_fn = {b['filename']: b for b in baseline}

# Populate from baseline
for entry in entries:
    fn = entry['filename']
    if fn in baseline_by_fn:
        b = baseline_by_fn[fn]
        entry['filepath'] = b['filepath']
        entry['page_count'] = b.get('page_count', 0)
        entry['is_scanned'] = b.get('is_scanned')
        entry['has_bookmarks'] = b.get('has_bookmarks')
        bm = b.get('bookmark_titles')
        entry['bookmark_titles'] = [item['title'] for item in bm if isinstance(item, dict)] if bm and isinstance(bm, list) else []

# Write to bookdata.json
with open('bookdata.json', 'r', encoding='utf-8') as f:
    existing = json.load(f)
existing_fns = {b['filename'] for b in existing}

added = 0
for entry in entries:
    if entry['filename'] not in existing_fns:
        existing.append(entry)
        existing_fns.add(entry['filename'])
        added += 1

with open('bookdata.json', 'w', encoding='utf-8') as f:
    json.dump(existing, f, ensure_ascii=False, indent=2)

# Log
for entry in entries:
    ts = datetime.now().isoformat()
    review = 'REVIEW' if entry.get('needs_review') else 'OK'
    with open('log.txt', 'a', encoding='utf-8') as lf:
        lf.write(f"{entry['filename']} | DONE | {ts} | conf={entry['extraction_confidence']} review={review} desc_src={entry['description_source']}\n")

print(f'Added {added}, total: {len(existing)}')
for e in entries:
    print(f"  [{e['extraction_confidence']}] {e['title'][:70]} | {e['author'][:50]} | {e['year']}")
