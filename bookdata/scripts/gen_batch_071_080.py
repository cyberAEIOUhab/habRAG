"""Generate and write entries for books 71-80."""
import json, os
from datetime import datetime

entries = [
    {
        "filename": "Reconstructing a National Identity The Jews of Habsburg Austria during World War I (Studies in Jewish History) (Marsha L. Rozenblit) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Reconstructing a National Identity: The Jews of Habsburg Austria during World War I",
        "author": "Marsha L. Rozenblit",
        "year": 2001,
        "language": "英文", "publisher": "Oxford University Press",
        "description": "Marsha L. Rozenblit的《重构民族认同：一战期间哈布斯堡奥地利的犹太人》是哈布斯堡犹太史领域的重要专著，2001年由牛津大学出版社出版（xiv+252页，属「犹太史研究」丛书）。Rozenblit（马里兰大学历史系教授）提出了一个核心分析概念——「三重认同」（tripartite identity）：哈布斯堡帝国内莱塔尼亚的犹太人在战前发展出一种独特的、多层叠合的认同结构——对奥地利国家的政治效忠、对（主要是德意志但也包括捷克或波兰）文化的归属、以及独特的犹太民族/族群意识。这种多层认同之所以可能，恰恰是因为哈布斯堡多民族国家是一个政治建构而非族群民族国家——它允许犹太人同时成为爱国的奥地利人与民族的犹太人。全书依次分析：一战前夕奥匈200余万犹太人的内部多样性；「1914年精神」中犹太人对战争的热情拥护（将反俄战争视为解放俄国犹太人的「圣战」）；后方约15.7-38.5万来自加利西亚与布科维纳的犹太难民的救助工作；超过30万犹太士兵（含约2.5万预备役军官）的服役经验；以及1918年帝国崩溃后「三重认同」在继任国中面临的深刻危机——波-乌战争（1918-1919）中约10万犹太人死于波兰境内的集体迫害（pogrom）。基于对维也纳、布拉格与耶路撒冷档案以及回忆录、报纸与布道词的广泛研究，本书被誉为哈布斯堡犹太人史、一战难民研究与民族主义/少数族群认同研究领域的杰出贡献。",
        "description_source": "web_search", "extraction_confidence": "high", "needs_review": False, "extraction_notes": "", "priority_tier": "standard"
    },
    {
        "filename": "Religion and Nationality in Western Ukraine The Greek Catholic Church and the Ruthenian National Movement in Galicia,… (John-Paul Himka) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Religion and Nationality in Western Ukraine: The Greek Catholic Church and the Ruthenian National Movement in Galicia, 1867-1900",
        "author": "John-Paul Himka",
        "year": 1999,
        "language": "英文", "publisher": "McGill-Queen's University Press",
        "description": "John-Paul Himka的《西乌克兰的宗教与民族性：希腊天主教会与加利西亚鲁塞尼亚民族运动，1867-1900》是其加利西亚乌克兰民族运动三部曲的收官之作，1999年由McGill-Queen's大学出版社出版于「宗教史研究」丛书（xvii+236页）。Himka（阿尔伯塔大学历史与古典学系教授）以1867年奥匈妥协至1900年间的加利西亚希腊天主教会为叙事轴心，考察宗教与民族性在这一最关键的民族建构阶段如何复杂交织。全书的核心分析框架聚焦于希腊天主教神职人员与政治圈子中「亲俄派」（Russophiles）与「民族民粹派」（National Populists，即乌克兰认同派）之间的斗争，以及四位关键外部行动者——哈布斯堡政府、梵蒂冈、沙皇俄国、波兰省级官员与耶稣会——各自的角色与利益。Himka在方法论上自觉运用Ernest Gellner、Eric Hobsbawm与Miroslav Hroch的民族主义理论，并有意识地使用「鲁塞尼亚人」与「希腊天主教徒」而非「乌克兰人」与「乌克兰天主教徒」作为中性术语——以忠实反映当时两种相互竞争的民族认同范式。本书以对乌克兰、波兰、奥地利与意大利（梵蒂冈）多国档案的广泛研究为基础，被Habsburg（H-Net）与Slavic Review评论者赞誉为其三部曲中『最精细、最具可读性』的一部，论证了加利西亚希腊天主教案例是「民族性建构中能动性与选择力量的一个惊人透明的实例」。",
        "description_source": "web_search", "extraction_confidence": "high", "needs_review": False, "extraction_notes": "", "priority_tier": "high"
    },
    {
        "filename": "Ring of Steel Germany and Austria-Hungary in World War I (Alexander Watson) (z-library.sk, 1lib.sk, z-lib.sk).epub",
        "title": "Ring of Steel: Germany and Austria-Hungary in World War I",
        "author": "Alexander Watson",
        "year": 2014,
        "language": "英文", "publisher": "Basic Books / Allen Lane",
        "description": "Alexander Watson的《钢铁之环：德国与奥匈帝国在第一次世界大战中》是近年来最受赞誉的一战史著作之一，2014年由Allen Lane（英国）与Basic Books（美国）出版（约608-832页，视版本而定），荣获沃尔夫森历史奖（Wolfson History Prize）与古根海姆-莱尔曼军事史奖。该书填补了一战英文学术的重要空白——这是首部从战败的中欧同盟国（德国与奥匈帝国）视角系统地叙述整个一战历程的综合性通史。Watson的核心论点是：『是恐惧而非侵略性或不受约束的军国主义』驱使德奥两国在1914年走向战争——奥匈帝国在萨拉热窝刺杀后恐惧民族主义分裂，德国恐惧被法俄英包围；这种恐惧催生了一场「幻觉之战」，随后蜕变为防御战、进而升级为生存之战，英国的海上封锁构成了书名中的「钢铁之环」。在战争责任问题上，Watson将首要责任归咎于奥匈帝国（拒绝接受对塞尔维亚的惩罚性战争可能扩大化），其次为德国（给予奥匈帝国1914年七月的空白支票），同时也严厉批评俄国将局部巴尔干冲突升级为世界性战火。该书对德奥两国战时公众动员、对平民暴行（比利时与塞尔维亚）、以及大战「有毒的遗产」——民族仇恨、反犹主义与暴力——为二战奠定基础远超凡尔赛条约安排的论证，均被广泛赞誉。H-Net评论者称其为『一本权威性资源……在平衡军事战役、外交、民众动员与全面战争的平民体验方面脱颖而出』。",
        "description_source": "web_search", "extraction_confidence": "medium", "needs_review": True, "extraction_notes": "EPUB文件，ebooklib提取失败，无法验证文本。书名、作者、年份依赖文件名解析与网页搜索。Basic Books美国版与Allen Lane英国版出版年份均为2014年。EPUB元数据需人工核对。",
        "priority_tier": "standard"
    },
    {
        "filename": "Robin-Okey-Taming-Balkan-Nationalism-The-Habsburg-Civilizing-Mission-in-Bosnia-1878-1914-2007.pdf",
        "title": "Taming Balkan Nationalism: The Habsburg 'Civilizing Mission' in Bosnia, 1878-1914",
        "author": "Robin Okey",
        "year": 2007,
        "language": "英文", "publisher": "Oxford University Press",
        "description": "Robin Okey（华威大学历史学教授，哈布斯堡与巴尔干史专家）的《驯化巴尔干民族主义：哈布斯堡在波斯尼亚的「文明使命」，1878-1914》是第一部全面评估奥匈帝国对波斯尼亚-黑塞哥维那占领治理的英文综合研究，2007年由牛津大学出版社出版（xvi+346页）。Okey基于在奥地利、匈牙利与南斯拉夫文献的广泛研究——特别是两位关键行政长官Benjámin Kállay与István Burián的匈牙利语文件——系统考察了哈布斯堡「文化使命」的两大核心主题：在一个「落后」社会推行「欧洲化」的影响，以及塞族、克族与波斯尼亚穆斯林这三种此后主导波斯尼亚生活的民族认同的结晶化过程。全书对Kállay备受争议的「波斯尼亚民族」（Bošnjaštvo）政策——一种试图培育超越族群-宗教分野的统一波斯尼亚认同的实用主义策略——进行了最为详尽的实证评估。Okey不偏不倚地评价了帝国治理的成就（基础设施建设、法律现代化、教育体系创建）与失败（未能争取民众的广泛支持、未能遏制民族分离主义的组织化）。特别值得注意的是，该书对「1914年前波斯尼亚中学生恐怖主义的前所未知的背景」——即加夫里洛·普林西普（Gavrilo Princip）从中涌现的社会与教育环境——进行了开创性分析，论证像民族主义但具有都市文化素养的塞族历史学家Vladimir Ćorović更典型地代表了该政权下受教育的一代，而非激进恐怖分子。Marko Attila Hoare在《英国历史评论》中誉之为「一部视野开阔、细节丰富的优秀而均衡的概述」。",
        "description_source": "web_search", "extraction_confidence": "high", "needs_review": False, "extraction_notes": "", "priority_tier": "high"
    },
    {
        "filename": "Rumania 1866-1947 (Oxford History of Modern Europe) (Keith Hitchins) (z-library.sk, 1lib.sk, z-lib.sk).epub",
        "title": "Rumania, 1866-1947",
        "author": "Keith Hitchins",
        "year": 1994,
        "language": "英文", "publisher": "Clarendon Press / Oxford University Press",
        "description": "Keith Hitchins的《罗马尼亚，1866-1947》是牛津现代欧洲史（Oxford History of Modern Europe）系列中的权威卷册，1994年由牛津Clarendon出版社出版（viii+579页）。Hitchins（伊利诺伊大学厄巴纳-香槟分校历史学教授，美国最杰出的罗马尼亚史专家）以12章的宏大结构，追踪了罗马尼亚从1866年独立建国至1947年共产党接管政权之间的政治、社会与经济演变。全书依时序分三大部分：1866-1914年卡罗尔一世治下的独立与制度建构（包括特兰西瓦尼亚的罗马尼亚人在二元君主国内的地位）；1914-1944年间的「大辩论」——围绕国家发展路径的政治与思想争论、两次大战间的议会政治与大罗马尼亚的民族整合难题；以及1944-1947年向苏联模式过渡与历史连续性的断裂。Hitchins的核心分析框架围绕精英们在现代化与民族认同之间的张力展开：如何在借鉴西欧模式「欧洲化」的同时不牺牲民族独特性？如何在列强主导的国际秩序中维系独立？一个尽管工业有所成长却仍以农业为主的经济如何应对现代性的挑战？附录中的详尽书目论文（pp. 548-569）是该领域不可多得的文献指南。本文件为EPUB格式。",
        "description_source": "web_search", "extraction_confidence": "medium", "needs_review": True, "extraction_notes": "EPUB文件，ebooklib提取失败，无法通过首页文本验证。书名与作者依赖文件名解析与网页搜索。Oxford University Press精装本1994年出版。EPUB元数据需人工核对。",
        "priority_tier": "standard"
    },
    {
        "filename": "Socialism in Galicia The Emergence of Polish Social Democracy and Ukrainian Radicalism (1860–1890) (John-Paul Himka) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Socialism in Galicia: The Emergence of Polish Social Democracy and Ukrainian Radicalism (1860-1890)",
        "author": "John-Paul Himka",
        "year": 1983,
        "language": "英文", "publisher": "Harvard Ukrainian Research Institute (distributed by Harvard University Press)",
        "description": "John-Paul Himka的《加利西亚的社会主义：波兰社会民主与乌克兰激进主义的兴起，1860-1890》是其加利西亚民族运动三部曲的开篇之作，1983年由哈佛大学乌克兰研究所出版（哈佛乌克兰研究丛书，xi+244页）。全书考察奥地利帝国最大、最东端的王室领地——加利西亚（今分属波兰与乌克兰）——在1860至1890年间社会主义运动的诞生与分化。Himka围绕两个核心问题展开分析：民族主义与社会主义之间的结构性关联（而非对立），以及东欧农民与手工业者的政治动员逻辑——这些群体在此前的社会主义史中往往被工业无产阶级的叙事所遮蔽。全书追溯了波兰与乌克兰社会主义者如何将工匠学徒与新近解放的农民组织为政治力量的过程：社会主义运动起源于对奥地利宪政改革（1861年二月特许状与1867年十二月宪法）回应的民主民族运动，随后在各民族关系日益紧张的语境与加利西亚向西欧工业经济开放的结构性变革中，逐渐结晶为社会主义政党。该书融入了Himka后来在其三部曲中持续深化的核心方法论关切——将民族认同视为一种建构性而非本质性的历史现象，以底层社会史的微观视角取代精英政治史的宏大叙事。美国历史评论（AHR, 1984年）发表书评。",
        "description_source": "web_search", "extraction_confidence": "high", "needs_review": False, "extraction_notes": "", "priority_tier": "standard"
    },
    {
        "filename": "Stjepan Radić, the Croat Peasant Party, and the Politics of Mass Mobilization,1904-1928 (Mark Biondich) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "Stjepan Radić, the Croat Peasant Party, and the Politics of Mass Mobilization, 1904-1928",
        "author": "Mark Biondich",
        "year": 2000,
        "language": "英文", "publisher": "University of Toronto Press",
        "description": "Mark Biondich的《斯捷潘·拉迪奇、克罗地亚农民党与群众动员政治，1904-1928》是英语学界关于20世纪克罗地亚政治史上最具魅力与影响力的人物——斯捷潘·拉迪奇（Stjepan Radić, 1871-1928）——的最权威研究，2000年由多伦多大学出版社出版（xi+344页）。全书以拉迪奇的政治生涯为叙事主线，考察这位魅力型领袖如何将克罗地亚农民——此前在地方社会中被排斥于正式政治参与之外的沉默多数——动员为现代群众政治的决定性力量。各章依次覆盖：拉迪奇的形成时期（1871-1904）、克罗地亚农业主义（agrarianism）的意识形态体系与组织建构、拉迪奇在克罗地亚主义、南斯拉夫主义与哈布斯堡君主国三重政治框架间的复杂立场、克罗地亚农民党在第一次世界大战期间的态度、1918-1925年间「中立克罗地亚农民共和国」的激进宪政实验与民族动员、1925-1928年「克罗地亚问题」在塞尔维亚人-克罗地亚人-斯洛文尼亚人王国议会政治中的激化。拉迪奇1928年在议会大厅被黑山塞族议员枪击身亡是全书叙事的历史终点——这一事件不仅终结了南斯拉夫短暂的民主实验，催生了亚历山大国王的皇家独裁（1929年），也深刻塑造了此后塞尔维亚-克罗地亚关系的集体记忆与政治神话。该书是前南斯拉夫政治史领域不可或缺的英文学术参考文献。",
        "description_source": "web_search", "extraction_confidence": "high", "needs_review": False, "extraction_notes": "", "priority_tier": "standard"
    },
    {
        "filename": "The Annexation of Bosnia 1908-1909 (Bernadotte E. Schmitt) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "The Annexation of Bosnia, 1908-1909",
        "author": "Bernadotte E. Schmitt",
        "year": 1937,
        "language": "英文", "publisher": "Cambridge University Press",
        "description": "Bernadotte E. Schmitt（1886-1969）的《波斯尼亚的兼并，1908-1909》是关于1908-1909年波斯尼亚兼并危机——第一次世界大战前欧洲最危险的大国对抗事件之一——的经典外交史研究，1937年由剑桥大学出版社出版（viii+264页）。Schmitt是美国第一代专业的欧洲外交史家，曾任美国历史学会主席（1960年），1930年因《三同盟的来临》（The Coming of the War, 1914）获普利策历史奖。全书以15章的紧密外交史结构，逐次分析了兼并危机的外交前奏（布赫劳会谈中俄奥两国外长的秘密交易）、保加利亚宣布独立与奥斯曼帝国的反应、兼并宣布后的欧洲会议提案之争、奥-塞紧张关系与俄国在德国最后通牒面前的退缩、对土耳其的补偿安排、以及「塞尔维亚1919年3月31日照会」——塞尔维亚被迫承认兼并并承诺与奥匈保持善邻关系——的屈辱性结局。Schmitt的叙事基于对各大国外交档案的广泛研究，在1930年代的外交史传统中代表了最优秀的学术水平。该书至今仍是研究1908-1909年波斯尼亚危机的最详尽的单卷本英文参考文献——这场危机虽以奥匈帝国的外交胜利告终，却也不可逆转地毒化了奥俄关系与奥塞关系，为1914年萨拉热窝事件的爆发奠定了关键的政治前提。",
        "description_source": "web_search", "extraction_confidence": "high", "needs_review": False, "extraction_notes": "", "priority_tier": "standard"
    },
    {
        "filename": "The Army of Francis Joseph (Gunther Rothenberg) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "The Army of Francis Joseph",
        "author": "Gunther E. Rothenberg",
        "year": 1976,
        "language": "英文", "publisher": "Purdue University Press",
        "description": "Gunther E. Rothenberg（1923-2004）的《弗朗茨·约瑟夫的军队》是英语学界关于哈布斯堡军队从拿破仑时代到一战解体之间最权威的单卷本军事制度史，1976年由普渡大学出版社出版（xiii+298页，后多次重印平装本）。Rothenberg系普渡大学军事史教授，以对拿破仑战争与哈布斯堡军事史的双重研究著称。全书以14章的结构追踪了哈布斯堡军队从起源至1918年解体的完整演变：从查理大公时代的军事改革、梅特涅时代的军队、1848-1849年革命与反革命的武装角色、皇帝亲掌军权时期（1849-1859）、1860-1866年间的衰败与克尼格雷茨战役的灾难、1867年奥匈妥协后的二元制军事架构与重组、1874-1881年巴尔干占领与军事边疆的废除、1881-1905年贝克（Beck）与阿尔布雷希特（Albrecht）时代的军事现代化、1906-1909年康拉德（Conrad）任总参谋长与兼并危机、1909-1914年康拉德-毛奇-埃伦塔尔之间的巴尔干危机三角关系、到1914-1916年大战中的表现与弗朗茨·约瑟夫去世，最后以卡尔皇帝治下军队的解体收尾。Rothenberg将军事制度史与政治社会史有机结合——论证哈布斯堡军队不仅仅是一支作战力量，更是多民族帝国最核心的统一制度支柱：其军官团、共同语言（德语指挥用语）、超民族的忠诚文化与独特的军事司法体系共同构成了一种替代性帝国公民身份。本书与其续篇《克罗地亚的军事边疆》（The Military Border in Croatia, 1740-1881，亦收入本馆藏）构成Rothenberg关于哈布斯堡军事制度的双卷本经典。",
        "description_source": "web_search", "extraction_confidence": "high", "needs_review": False, "extraction_notes": "", "priority_tier": "high"
    },
    {
        "filename": "The Austrian Electoral Reform of 1907 (William Alexander Jenks) (z-library.sk, 1lib.sk, z-lib.sk).pdf",
        "title": "The Austrian Electoral Reform of 1907",
        "author": "William Alexander Jenks",
        "year": 1950,
        "language": "英文", "publisher": "Columbia University Press",
        "description": "William Alexander Jenks的《1907年奥地利选举改革》是研究哈布斯堡帝国晚期政治体制转型的最重要的制度史著作之一，1950年由哥伦比亚大学出版社出版于「历史、经济与公法研究」丛书（No. 559，227页），原为作者在哥伦比亚大学的博士论文（1974年由Octagon Books重印）。全书聚焦于1907年奥地利（内莱塔尼亚）历史性的选举制度改革——帝国议会（Reichsrat）下院废除此前以社会阶层与纳税额为基础的等级选举制（curia system），首次实行（男性）普遍平等直接选举——系统分析了这一改革从1890年代政治动员到1907年首次普选实施的全过程。Jenks逐一检视了选举改革面临的六大核心问题：选民资格与普选权、选区划分与城乡代表失衡、语言与民族边界与选区划界的政治博弈、选举地理学对各民族政党席位分配的影响、1907年首次普选的实际选举结果对各民族政党的冲击、以及改革在1907-1914年间未能实现其倡导者所期望的政治理性化反而激化了民族冲突的「改革的失败」。该书对理解晚期哈布斯堡奥地利从显贵政治（Notabelnpolitik）向大众民主转型的制度机制、以及民主化本身如何意外地加剧而非缓解了帝国的民族政治离心力——这一对当代多民族民主国家具有持久警醒意义的「民主化悖论」——提供了不可替代的制度史分析。Jenks另著有《铁环下的奥地利，1879-1893》（亦收入本馆藏）。",
        "description_source": "web_search", "extraction_confidence": "high", "needs_review": False, "extraction_notes": "", "priority_tier": "standard"
    }
]

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

print(f'Added {added}, total: {len(existing)}/142')
for e in entries:
    print(f"  [{e['extraction_confidence']}] {e['title'][:70]} | {e['author'][:50]} | {e['year']}")
