"""Generate and write entries for books 26-30."""
import json, os
from datetime import datetime

entries = [
    {
        "filename": "European goods market integration in the very long run from the Black Death to the First World War.pdf",
        "title": "European Goods Market Integration in the Very Long Run: From the Black Death to the First World War",
        "author": "Giovanni Federico, Max-Stephan Schulze, and Oliver Volckart",
        "year": 2021,
        "language": "英文",
        "publisher": "Journal of Economic History, Vol. 81, No. 1 (Cambridge University Press)",
        "description": "本文由Federico、Schulze与Volckart三位经济史学家发表于2021年《经济史杂志》（Journal of Economic History, Vol. 81, No. 1, pp. 276-308），是对欧洲商品市场整合问题的一项雄心勃勃的超长时段（ultra-long-run）定量研究。基于全新构建的覆盖近600个欧洲市场的小麦价格数据集，论文追踪了从14世纪中叶黑死病到一战前夕近六个世纪的价格趋同与市场效率演变。主要发现颠覆了既有研究的若干基本假设：价格趋同主要是一种前现代现象——早在15世纪末即已开始，17世纪初曾短暂停滞，三十年战争后恢复，拿破仑战争后因贸易自由化加速推进，但从19世纪40年代末趋同放缓，1875年后在保护主义贸易政策主导下反转为分化。论文还确认了约1600年开始出现的西北欧与欧洲大陆其他地区之间的「小分流」（Little Divergence），并将制度变迁与信息传播技术的非同步扩散——而非仅仅是交通成本或技术变革——确定为驱动市场整合时空格局的关键因素，对理解欧洲经济史与全球化起源具有重要方法论与实证贡献。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "standard"
    },
    {
        "filename": "Exclusive revolutionaries  liberal politics, social experience, and national identity in the Austrian Empire, 1848-1914 (Pieter M. Judson) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Exclusive Revolutionaries: Liberal Politics, Social Experience, and National Identity in the Austrian Empire, 1848-1914",
        "author": "Pieter M. Judson",
        "year": 1996,
        "language": "英文",
        "publisher": "University of Michigan Press",
        "description": "Pieter M. Judson的《排他性革命者：奥地利帝国的自由主义政治、社会经验与民族认同，1848-1914》是一部重塑哈布斯堡帝国晚期政治文化史理解的重要著作，1996年由密歇根大学出版社出版，1998年荣获美国历史学会赫伯特·巴克斯特·亚当斯奖（Herbert Baxter Adams Prize，欧洲史最佳首部著作奖）。Judson利用来自多个前哈布斯堡省份的丰富档案材料，追踪德语自由主义活动家如何从1848年革命的普世主义理想出发，通过志愿社团网络构建政治运动——他们倡导基于私有产权的市场经济、个人自我完善、体面伦理以及积极公民与消极公民的严格划分。1880年代后，面对群众性政治运动的挑战，这些自由派转向了以族群认同和语言来定义的德意志民族主义政治，将「德意志性」作为弥合社会阶级分歧的工具。Judson的核心论点强调连续性而非断裂：后期民族主义运动必须被理解为早期自由主义传统中已蕴含的冲动的延续，自由派「关于社会的论述持续设定了」王室、贵族与军方争夺19世纪奥地利社会主导权的斗争条件。本书有两个版本：本文件为17.8MB扫描版（300+页完整本），另有一份3.8MB非扫描版（仅11页，疑为导论或摘要）。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "high"
    },
    {
        "filename": "Exclusive revolutionaries liberal politics, social experience, and national identity in the Austrian Empire, 1848-1914.pdf",
        "title": "Exclusive Revolutionaries: Liberal Politics, Social Experience, and National Identity in the Austrian Empire, 1848-1914 [excerpt/summary]",
        "author": "Pieter M. Judson",
        "year": 1996,
        "language": "英文",
        "publisher": "University of Michigan Press",
        "description": "本文件为Pieter M. Judson《排他性革命者：奥地利帝国的自由主义政治、社会经验与民族认同，1848-1914》（University of Michigan Press, 1996）的节选/摘要版（仅11页），应为全书导论或部分章节的摘录。全书的完整扫描版（300+页，约17.8MB）也收入本馆藏中。Judson的这部获奖著作（1998年AHA Herbert Baxter Adams Prize）论证了奥地利德语自由主义运动如何从1848年的普世理想演变为1880年代后的排他性德意志民族主义政治，其核心竞争力在于将「政治文化」概念引入哈布斯堡史学，以志愿社团的社会经验为透镜分析自由主义意识形态从普世主义向民族排他性转变的内在逻辑。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": True,
        "extraction_notes": "本文件仅11页（非扫描版，含3条书签），与同名17.8MB扫描版（300+页）为同一著作的不同版本。推测为导论/摘要/书评选录。建议人工确认本文件的具体内容性质（是否为出版社提供的试读章节或学术书评摘录），必要时合并为一个书目记录。",
        "priority_tier": "standard"
    },
    {
        "filename": "Fin-de-siecle Vienna politics and culture (Schorske, Carl E) (z-library.sk, 1lib.sk, z-lib.sk).epub",
        "title": "Fin-de-Siècle Vienna: Politics and Culture",
        "author": "Carl E. Schorske",
        "year": 1980,
        "language": "英文",
        "publisher": "Alfred A. Knopf / Vintage Books",
        "description": "Carl E. Schorske的《世纪末的维也纳：政治与文化》是20世纪文化史与思想史领域最具影响力的著作之一，1981年荣获普利策非虚构类作品奖。本书以七篇相互独立却又巧妙交织的论文结构，探索了19世纪末维也纳这座城市如何在政治与社会解体的危机中孕育了现代主义艺术与思想的诸多源头。Schorske的核心方法论是「以政治语境解读文化创造」——他将克里姆特的绘画、奥托·瓦格纳与阿道夫·洛斯的建筑、弗洛伊德的精神分析、施尼茨勒的文学以及勋伯格的音乐等个案一一置于哈布斯堡帝国晚期自由主义政治崩溃与反犹群众政治兴起的语境中进行解读，论证世纪之交的维也纳文化现代主义本质上是资产阶级在丧失政治权力后向内转的精神创造。该书被誉为「对历史研究自身的动人辩护」（David Hollinger语），Gordon Craig、H.R. Trevor-Roper等史学大家都给予了极高评价。Schorske（1915-2015）曾任普林斯顿大学教授，获麦克阿瑟天才奖，本书是其毕生学术声誉的奠基之作。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "EPUB文件，ebooklib提取失败，无法通过首页文本验证书名/出版年份。但Schorske此书为学界公认经典，标题/作者/年份完全无歧义。",
        "priority_tier": "high"
    },
    {
        "filename": "Francis Joseph (Beller, Steven, 1958-) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Francis Joseph",
        "author": "Steven Beller",
        "year": 1996,
        "language": "英文",
        "publisher": "Longman",
        "description": "Steven Beller的《弗朗茨·约瑟夫》是Longman出版社「权力人物传」（Profiles in Power）系列中的一卷，1996年出版（viii+272页）。此书并非传统帝王传记，而是一部以弗朗茨·约瑟夫皇帝为叙事轴心的晚期哈布斯堡政治史深度解读论文，主要面向大学教科书市场。Beller提出了一个尖锐的批判性论点：弗朗茨·约瑟夫的个人决策——尤其是对军队与外交政策的王朝控制权的执念——阻碍了功能性政治体制的发展，加剧了民族紧张关系，并为君主制解体后的威权政治乃至亲法西斯政治奠定了结构性基础。全书将1867年奥匈妥协视为皇帝最严重的政治错误之一。各章依次覆盖绝对主义时期（1830-1859）、自由主义实验期（1859-1879）、「糊弄过关」的铁环时代（1879-1897）、暮年专制回归（1897-1914）以及1914年的战争决策与死亡。Beller对哈布斯堡帝国的评价与当代怀旧式的帝国神话形成鲜明对照——在他笔下，这是一个其统治者选择直接促成了自身崩溃及其后悲剧的多民族国家。H-Net书评（Daniel Unowsky撰）称赞该书在有限篇幅内提供了对晚期哈布斯堡政治史的清晰而有力的综述，适合作为本科生课程的核心阅读材料。",
        "description_source": "web_search",
        "extraction_confidence": "medium",
        "needs_review": True,
        "extraction_notes": "首页为扫描件（is_scanned=True），无法从PDF提取文字验证书名/出版信息。书名、作者、年份依赖文件名解析与网页搜索。1996年Longman版有精装/平装两种（ISBN不同），本文件版本未能确定。建议人工核对版权页。",
        "priority_tier": "standard"
    }
]

# Load baseline
with open('baseline_extract.json', 'r', encoding='utf-8') as f:
    baseline = json.load(f)
baseline_by_fn = {b['filename']: b for b in baseline}

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

# Write
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

for entry in entries:
    ts = datetime.now().isoformat()
    review = 'REVIEW' if entry.get('needs_review') else 'OK'
    with open('log.txt', 'a', encoding='utf-8') as lf:
        lf.write(f"{entry['filename']} | DONE | {ts} | conf={entry['extraction_confidence']} review={review} desc_src={entry['description_source']}\n")

print(f'Added {added}, total: {len(existing)}')
for e in entries:
    print(f"  [{e['extraction_confidence']}] {e['title'][:70]} | {e['author'][:50]} | {e['year']}")
