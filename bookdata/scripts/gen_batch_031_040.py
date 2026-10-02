"""Generate and write entries for books 31-40."""
import json, os
from datetime import datetime

entries = [
    {
        "filename": "Franz Conrad von Hötzendorf  architect of the apocalypse (Sondhaus, Lawrence, 1958- author) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Franz Conrad von Hötzendorf: Architect of the Apocalypse",
        "author": "Lawrence Sondhaus",
        "year": 2000,
        "language": "英文",
        "publisher": "Humanities Press / Brill",
        "description": "Lawrence Sondhaus的《弗朗茨·康拉德·冯·赫岑多夫：末日建筑师》是首部关于奥匈帝国最具争议性军事人物的现代传记，2000年由Humanities Press出版（Brill「中欧史研究」丛书第18卷，viii+271页）。康拉德于1906-1917年间担任奥匈帝国总参谋长，其军事生涯呈现一个深刻的历史悖论：他在战前享有军事天才的盛誉，却在第一次世界大战中遭遇惨重失败。Sondhaus的独特贡献在于将康拉德置于比较军事史的视野中——作者论证，在欧洲各大国中，没有任何其他将领像康拉德那样同时兼任一国首要的战前战术理论家、战前与战时战略制定者以及战时野战军指挥官。全书依次检视其1906年前的军事写作与战术教学生涯、总参谋长任内的丑闻与政治危机、大战中的灾难性表现（特别是1914年加利西亚战役的惨败），以及晚年的衰落。Sondhaus在弗吉尼亚大学获博士学位，任教于印第安纳波利斯大学，另著有《海战史1815-1914》等作品。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "standard"
    },
    {
        "filename": "From Prejudice to Persecution A History of Austrian Anti-Semitism (Bruce F. Pauley) (z-library.sk, 1lib.sk, z-lib.sk).epub",
        "title": "From Prejudice to Persecution: A History of Austrian Anti-Semitism",
        "author": "Bruce F. Pauley",
        "year": 1992,
        "language": "英文",
        "publisher": "University of North Carolina Press",
        "description": "Bruce F. Pauley的《从偏见到迫害：奥地利反犹主义史》是英语学界关于奥地利反犹主义最全面、最系统的通史性著作，1992年由北卡罗来纳大学出版社出版。Pauley（中佛罗里达大学历史学教授）追溯了奥地利反犹主义从19世纪中后期的宗教与经济偏见到20世纪纳粹时期的系统性种族迫害的完整演变轨迹，将分析嵌入奥地利政治文化从自由主义崩溃经基督教社会党的群众动员到纳粹吞并的宏大叙事之中。全书的核心分析框架强调奥地利反犹主义的独特性——它既不同于德国的种族生物学路径，也不同于法国的政治-司法反犹传统，而是一种根植于哈布斯堡多民族帝国特有的民族竞争、经济焦虑与政治机会主义交织而成的复合现象。该书覆盖了从1848年革命到1938年德奥合并近一个世纪的时间跨度，对舍内雷尔（Schönerer）的泛日耳曼主义、卢埃格尔（Lueger）的基督教社会反犹动员、一战期间加利西亚犹太难民危机、以及两次大战之间各政党对「犹太问题」的政治利用均有专章论述，是哈布斯堡史学与犹太史交叉领域的标准参考书。",
        "description_source": "web_search",
        "extraction_confidence": "medium",
        "needs_review": True,
        "extraction_notes": "EPUB文件，ebooklib提取失败，无法通过首页文本验证书名/出版年份。书名、作者、年份依赖文件名解析与网页搜索交叉确认。UNC Press精装版出版于1992年，平装本1998年。本EPUB版本年份未能确定。",
        "priority_tier": "high"
    },
    {
        "filename": "From Sadowa to Sarajevo  the foreign policy of Austria-Hungary, 1866-1914 (F R Bridge) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "From Sadowa to Sarajevo: The Foreign Policy of Austria-Hungary, 1866-1914",
        "author": "F. R. Bridge",
        "year": 1972,
        "language": "英文",
        "publisher": "Routledge & Kegan Paul",
        "description": "F.R. Bridge的《从萨多瓦到萨拉热窝：奥匈帝国外交政策，1866-1914》是英语学界关于奥匈帝国外交史最权威的标准著作之一，1972年由Routledge & Kegan Paul出版于「大国外交政策」丛书中（xvi+480页，附地图与详尽参考书目）。全书以1866年普奥战争（以萨多瓦/克尼格雷茨战役为转折点，奥地利被逐出德意志事务）为叙事起点，以1914年萨拉热窝刺杀事件引发的一战为终点，系统分析了哈布斯堡帝国外交决策的制度结构、战略困境与政策演变。Bridge的核心论点是：奥匈帝国的外交政策从根本上受到其作为多民族大国的内在脆弱性的制约——相对于其他欧洲列强，哈布斯堡的外交决策更少由经济利益或帝国扩张驱动，而更多由国内民族政治的离心压力与王朝威望的维护需求所塑造。该书特别关注了巴尔干问题在奥匈外交中的核心地位、1879年德奥同盟的形成逻辑、1878-1908年波斯尼亚占领时期的治理困境、以及1908-1909年兼并危机后与俄国的逐步对抗升级，对于理解一战起源于维也纳视角具有不可替代的学术价值。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "high"
    },
    {
        "filename": "Frontiers, Islands, Forests, Stones Mapping the Geography of a German Identity in the Habsburg Monarchy, 1848-1900.pdf",
        "title": "Frontiers, Islands, Forests, Stones: Mapping the Geography of a German Identity in the Habsburg Monarchy, 1848-1900",
        "author": "Pieter M. Judson",
        "year": 1996,
        "language": "英文",
        "publisher": "University of Michigan Press (chapter in 'The Geography of Identity', ed. Patricia Yaeger)",
        "description": "Pieter M. Judson的《边疆、孤岛、森林、石头》是1996年收入Patricia Yaeger主编《认同的地理学》（The Geography of Identity, University of Michigan Press）论文集中的一篇重要章节（第13章，pp. 382-407）。本文是Judson关于哈布斯堡帝国内莱塔尼亚地区德意志民族主义文化建构研究的早期代表作之一，与其同年出版的专著《排他性革命者》形成互补关系。Judson以四种空间隐喻为分析框架考察1848-1900年间德意志民族主义活动家如何将民族认同锚定于物理景观之中：摩拉维亚等边境地区被重塑为德意志-斯拉夫文明交锋的「边疆」；伊格劳/伊赫拉瓦等族群混居城镇被描绘为德意志人孤悬于捷克「海洋」中的「孤岛」；波希米亚森林被宣称为古日耳曼部落的祖居地（「森林」）；建筑风格与城市规划则被用作论证景观之德意志特性的「石头」证据。文章论证民族认同从精英文化消费品向大众化的、植根于地方空间的日常身份认同的转型，深刻影响了此后关于哈布斯堡「民族无差异」（national indifference）问题的学术讨论。本文件应为该论文集的PDF扫描版节选（26页）。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "standard"
    },
    {
        "filename": "Galician Haskalah and the Austrian Enlightenment.pdf",
        "title": "Galician Haskalah and the Austrian Enlightenment",
        "author": "Dirk Sadowski (presumed)",
        "year": 2012,
        "language": "英文",
        "publisher": None,
        "description": "本文探讨加利西亚哈斯卡拉（犹太启蒙运动）与奥地利启蒙专制主义之间的复杂互动关系，聚焦约瑟夫二世宽容法令（1782年）之后哈布斯堡国家在加利西亚建立的德語犹太学校网络。该论文的核心主题可能围绕Herz Homberg（1749-1841）——摩西·门德尔松的学生、受国家委派在加利西亚监督超过100所犹太小学的maskil——在将哈斯卡拉教育理念付诸实践过程中与拉比权威、传统犹太社群和帝国官僚体制之间的多重张力展开。相关学术研究（参见Dirk Sadowski, 'Haskala und Lebenswelt', Vandenhoeck & Ruprecht, 2010）强调这些学校不仅是识字教育的工具，更是国家「社会规训」（Sozialdisziplinierung）的载体——通过教科书将开明专制主义的道德价值植入犹太社群的日常生活世界（Lebenswelt）。本文应为Sadowski在2012年Jewish Culture and History期刊发表的论文'The Jewish German schools in Galicia (1782-1806) – school reality and corporate resistance'或相关学术论文的PDF版本。",
        "description_source": "web_search",
        "extraction_confidence": "low",
        "needs_review": True,
        "extraction_notes": "搜索未找到与该标题完全匹配的论文。推测为Dirk Sadowski关于加利西亚哈斯卡拉与奥地利启蒙运动关系的英文论文。作者、确切年份、期刊来源均存在不确定性，需人工确认。11页、非扫描版PDF。",
        "priority_tier": "standard"
    },
    {
        "filename": "Guardians of the Nation Activists on the Language Frontiers of Imperial Austria (Pieter M. Judson) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Guardians of the Nation: Activists on the Language Frontiers of Imperial Austria",
        "author": "Pieter M. Judson",
        "year": 2006,
        "language": "英文",
        "publisher": "Harvard University Press",
        "description": "Pieter M. Judson的《国家的守护者：帝奥地利语言边疆上的活动家》是其哈布斯堡民族主义三部曲中的第二部核心著作，2006年由哈佛大学出版社出版（313页），荣获多项学术图书奖。本书提出了对现代欧洲民族主义史学的根本性挑战：Judson论证晚期哈布斯堡奥地利乡村的「语言边疆」并非自然或永恒的现实，而是民族主义活动家自1880年代起有意识地「发明」出来的建构——他们利用1880-1910年间「日常使用语言」的普查数据，在地图上绘制出想象中相互碰撞的民族边界。全书分别以南波希米亚（德-捷）、南施蒂利亚（德-斯洛文尼亚）和南蒂罗尔（德-意）三地为个案，追踪城市民族主义活动家如何进入乡村地区试图将双语、文化混杂的农村居民「民族化」——却基本宣告失败。Judson提出了影响深远的「民族无差异」（national indifference）概念：农村人口的身份认同是多元的、情境性的，在日常生活语境中可在不同民族标签间灵活切换，他们并不将语言使用等同于对某一民族的效忠。该书标志着哈布斯堡民族主义史学从精英思想史向底层实践史的「实践转向」，对理解多民族帝国的民族冲突动态具有持久的方法论影响。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "high"
    },
    {
        "filename": "History in Exile Memory and Identity at the Borders of the Balkans (Pamela Ballinger) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "History in Exile: Memory and Identity at the Borders of the Balkans",
        "author": "Pamela Ballinger",
        "year": 2003,
        "language": "英文",
        "publisher": "Princeton University Press",
        "description": "Pamela Ballinger的《流放中的历史：巴尔干边界上的记忆与认同》是一部关于被迫迁徙、历史记忆与族群认同的人类学著作，2003年由普林斯顿大学出版社出版（xiv+328页）。Ballinger（时任鲍登学院人类学助理教授）以二战后从朱利安边疆区（Julian March，原属奥匈帝国，一战后归属意大利，二战后被意大利与南斯拉夫分割）被迫迁徙的多达35万意大利族裔为研究对象，基于1995-1996年在的里雅斯特与伊斯特拉半岛的多点田野调查（档案、民族志与口述史），比较了「流亡者」（esuli，逃亡到的里雅斯特及意大利其他地区的意大利人）与「留守者」（rimasti，留在现克罗地亚与斯洛文尼亚境内作为意大利少数民族的群体）两种截然不同的集体记忆模式。Ballinger揭示了双方如何建构相互竞争的受害者叙事——意大利一方聚焦于1943和1945年南斯拉夫游击队在foibe（喀斯特溶洞）中处决意大利人的记忆，而斯拉夫一方则强调法西斯政权的暴力压迫——以及意识形态对立（法西斯vs.共产主义）如何随时间转化为族群/文明对立（意大利/欧洲vs.斯拉夫/巴尔干）。该书被广泛认为是对欧洲人类学、被迫迁徙研究（displacement studies）与记忆研究领域的重要贡献，以微观史学的深度阐明了「历史」、「记忆」与「认同」三者均为建构性而非本质性的核心人类学命题。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "standard"
    },
    {
        "filename": "History of Slovakia The Struggle for Survival (2005) (Stanislav J. Kirschbaum) (z-library.sk, 1lib.sk, z-lib.sk).epub",
        "title": "A History of Slovakia: The Struggle for Survival",
        "author": "Stanislav J. Kirschbaum",
        "year": 2005,
        "language": "英文",
        "publisher": "St. Martin's Griffin / Palgrave Macmillan",
        "description": "Stanislav J. Kirschbaum的《斯洛伐克史：求存之斗争》是英语学界最权威的斯洛伐克通史著作之一，2005年出第二版（St. Martin's Griffin/Palgrave Macmillan，约397-416页）。Kirschbaum系约克大学格伦登学院国际研究教授、加拿大皇家学会院士，另著有《斯洛伐克历史辞典》。全书从斯洛伐克在多瑙河平原的早期定居一直写到后共产主义时代加入北约与欧盟的历程，时间跨度逾千年。核心叙事线索是「求存」——斯洛伐克民族在匈牙利化（Magyarization）压力下如何发展民族意识、在捷克斯洛伐克框架内如何争取自治地位、第一个斯洛伐克共和国（1939-1945）面对纳粹欧洲的抵抗与妥协、共产主义时期的现代化与压制，以及天鹅绒分离（1993）后第二共和国的建立。维也纳大学Emilia Hrabovec赞誉该书为「历史叙事的杰作……不受意识形态或政治偏见的影响」。皮茨堡大学Martin Votruba称之为「关于斯洛伐克过去的最易获取的英文综合性信息来源」。该书在哈布斯堡帝国民族冲突与东中欧民族国家建构的历史语境中提供了不可或缺的「斯洛伐克视角」。",
        "description_source": "web_search",
        "extraction_confidence": "medium",
        "needs_review": True,
        "extraction_notes": "EPUB文件，ebooklib提取失败，无法通过首页文本验证书名/出版年份。第一版出版于1995年，本文件标注为2005年（第二版）。作者、书名依赖文件名解析与网页搜索。建议人工确认EPUB元数据中的具体版本信息。",
        "priority_tier": "standard"
    },
    {
        "filename": "Hoyos Alexander — Der deutsch-englische Gegensatz.pdf",
        "title": "Der deutsch-englische Gegensatz und sein Einfluss auf die Balkanpolitik Österreich-Ungarns",
        "author": "Alexander von Hoyos",
        "year": 1922,
        "language": "德文",
        "publisher": "Berlin (publisher uncertain)",
        "description": "亚历山大·冯·霍约斯伯爵（Alexander Graf von Hoyos）所著《德英对立及其对奥匈帝国巴尔干政策的影响》是关于一战前大国关系与奥匈外交决策的关键一手史料，1922年出版于柏林（约105-108页，德文）。霍约斯在1914年七月危机期间担任奥匈帝国外交大臣贝希托尔德（Leopold Berchtold）的侍从室主任（chef-de-cabinet），因1914年7月5日奉命秘密出使柏林——即历史上著名的「霍约斯使命」（Hoyos Mission）——而载入史册：他成功从德国获得了对奥匈对塞尔维亚采取军事行动的无条件支持（所谓「空白支票」），成为七月危机升级为一战的关键环节。霍约斯在贝希托尔德外交团队中属鹰派，积极主张使用武力解决塞尔维亚问题。然而学者Solomon Wank指出，该书「对于他自己在1914年7月政策决策中的角色和影响力揭示甚少」，这本身就是研究七月危机决策者心态与自我辩护策略的重要文献特征。该书对于理解奥匈帝国在1908-1914年间巴尔干政策与英德对抗之间互动关系的内部视角具有独特史料价值。",
        "description_source": "web_search",
        "extraction_confidence": "medium",
        "needs_review": True,
        "extraction_notes": "首页文本提取显示为扫描件（quality=likely scanned），从PDF无法提取完整文字进行验证。出版年份有分歧：文件名未标注年份，网页搜索显示为1922年（而非1914年）。作者全名与出版社信息需人工核对版权页确认。",
        "priority_tier": "high"
    },
    {
        "filename": "Hungary and Her Successors (C.A. Macartney) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Hungary and Her Successors: The Treaty of Trianon and Its Consequences, 1919-1937",
        "author": "C. A. Macartney",
        "year": 1937,
        "language": "英文",
        "publisher": "Oxford University Press (for the Royal Institute of International Affairs)",
        "description": "C.A. Macartney（1895-1978）的《匈牙利及其继承国：特里亚农条约及其后果，1919-1937》是关于20世纪中东欧民族问题与领土变更的里程碑式学术著作，1937年由牛津大学出版社为皇家国际事务研究所（Chatham House）出版（xxi+504页，附折叠地图）。Macartney是英国学术院院士、牛津大学万灵学院研究员，专攻东中欧特别是奥匈帝国的历史与政治，以同情匈牙利立场著称。本书基于广泛的档案研究与田野调查，系统考察了特里亚农条约（1920年）之后匈牙利少数民族在四个继承国——奥地利、捷克斯洛伐克、罗马尼亚和南斯拉夫——中的处境，是英语学界最早对战后匈牙利边界问题进行深入实证研究的学术著作。全书结合了制度分析（继承国少数族群保护条约的法律框架）、统计评估（人口普查与土地改革数据）与田野调查中的第一手观察，对继承国的民族政策提供了细致的批判性比较。《外交事务》（1938年4月）誉之为「基于研究与实地调查的彻底学术工作」。尽管Macartney的亲匈牙利立场受到部分批评者注意，该书至今仍是研究特里亚农条约与两次大战之间中东欧民族政治不可绕过的经典参考文献，后于1965与1968年多次重印。",
        "description_source": "web_search",
        "extraction_confidence": "high",
        "needs_review": False,
        "extraction_notes": "",
        "priority_tier": "high"
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
