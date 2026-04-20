"""
GA vs Openclaw comparison data
BrowseComp-ZH: 10 matching tasks (browsecomp_023 ~ browsecomp_039)
WebCanvas: 12 matching tasks
"""

# ===== BrowseComp-ZH =====
# GA data (from browsecomp/ folder)
ga_browsecomp = {
    "browsecomp_023": {"score": 1.0, "turns": 7,  "time": 130.4, "tokens": 124430},
    "browsecomp_024": {"score": 0.0, "turns": 22, "time": 219.0, "tokens": 479575},
    "browsecomp_026": {"score": 1.0, "turns": 6,  "time": 110.1, "tokens": 46860},
    "browsecomp_027": {"score": 1.0, "turns": 23, "time": 406.1, "tokens": 380227},
    "browsecomp_031": {"score": 1.0, "turns": 13, "time": 270.8, "tokens": 264714},
    "browsecomp_032": {"score": 1.0, "turns": 29, "time": 257.9, "tokens": 656485},
    "browsecomp_035": {"score": 0.0, "turns": 40, "time": 358.6, "tokens": 975406},
    "browsecomp_036": {"score": 1.0, "turns": 7,  "time": 65.6,  "tokens": 117027},
    "browsecomp_038": {"score": 0.0, "turns": 40, "time": 431.2, "tokens": 1012941},
    "browsecomp_039": {"score": 0.0, "turns": 30, "time": 267.2, "tokens": 656021},
}

# Openclaw data (best score across all runs)
openclaw_browsecomp = {
    "browsecomp_023": {"score": 1.0, "turns": 17, "time": 172.5, "tokens": 508837},
    "browsecomp_024": {"score": 0.0, "turns": 38, "time": 357.3, "tokens": 2041823},  # best from run 003938
    "browsecomp_026": {"score": 0.0, "turns": 17, "time": 191.3, "tokens": 842206},
    "browsecomp_027": {"score": 0.0, "turns": 55, "time": 347.8, "tokens": 2470125},  # best from run 003938
    "browsecomp_031": {"score": 0.0, "turns": 19, "time": 265.3, "tokens": 893822},
    "browsecomp_032": {"score": 0.0, "turns": 17, "time": 146.8, "tokens": 648316},
    "browsecomp_035": {"score": 1.0, "turns": 56, "time": 310.1, "tokens": 3624829},
    "browsecomp_036": {"score": 0.0, "turns": 14, "time": 107.8, "tokens": 568746},  # best from run 010247
    "browsecomp_038": {"score": 0.0, "turns": 11, "time": 112.3, "tokens": 468366},
    "browsecomp_039": {"score": 0.0, "turns": 17, "time": 160.6, "tokens": 1066935},
}

# ===== WebCanvas =====
# GA data (from webcanvas/ folder)
ga_webcanvas = {
    "webcanvas_5":   {"score": 1.0,    "turns": 8,  "time": 60.5,  "tokens": 104950},
    "webcanvas_26":  {"score": 0.6667, "turns": 7,  "time": 70.0,  "tokens": 23008},
    "webcanvas_35":  {"score": 1.0,    "turns": 25, "time": 245.5, "tokens": 127827},
    "webcanvas_48":  {"score": 0.6667, "turns": 31, "time": 300.0, "tokens": 573031},
    "webcanvas_58":  {"score": 1.0,    "turns": 17, "time": 170.4, "tokens": 330326},
    "webcanvas_80":  {"score": 0.6667, "turns": 30, "time": 300.0, "tokens": 549254},
    "webcanvas_84":  {"score": 0.6667, "turns": 28, "time": 300.0, "tokens": 100705},
    "webcanvas_85":  {"score": 1.0,    "turns": 15, "time": 162.5, "tokens": 26685},
    "webcanvas_91":  {"score": 0.6667, "turns": 14, "time": 123.0, "tokens": 61670},
    "webcanvas_101": {"score": 0.6667, "turns": 26, "time": 235.6, "tokens": 104467},
    "webcanvas_102": {"score": 1.0,    "turns": 4,  "time": 42.4,  "tokens": 16206},
    "webcanvas_103": {"score": 1.0,    "turns": 11, "time": 128.2, "tokens": 196025},
}

# Openclaw data (from openclaw_webcanvas/ folder)
openclaw_webcanvas = {
    "webcanvas_5":   {"score": 1.0,    "turns": 5,  "time": 42.3,  "tokens": 90017},
    "webcanvas_26":  {"score": 0.6667, "turns": 20, "time": 158.7, "tokens": 767679},
    "webcanvas_35":  {"score": 1.0,    "turns": 21, "time": 195.3, "tokens": 401739},
    "webcanvas_48":  {"score": 0.6667, "turns": 14, "time": 147.7, "tokens": 761695},
    "webcanvas_58":  {"score": 1.0,    "turns": 12, "time": 110.2, "tokens": 431698},
    "webcanvas_80":  {"score": 0.0,    "turns": 24, "time": 170.8, "tokens": 515775},
    "webcanvas_84":  {"score": 0.6667, "turns": 16, "time": 121.4, "tokens": 262124},
    "webcanvas_85":  {"score": 0.75,   "turns": 21, "time": 187.9, "tokens": 493914},
    "webcanvas_91":  {"score": 1.0,    "turns": 29, "time": 178.7, "tokens": 1082896},
    "webcanvas_101": {"score": 0.6667, "turns": 53, "time": 456.4, "tokens": 2946267},
    "webcanvas_102": {"score": 1.0,    "turns": 11, "time": 96.5,  "tokens": 377221},
    "webcanvas_103": {"score": 0.25,   "turns": 10, "time": 89.6,  "tokens": 348109},
}

# Task descriptions
task_descriptions = {
    "browsecomp_023": "文学家首创诗话/器质深厚",
    "browsecomp_024": "散文集/景区纪念碑立碑人",
    "browsecomp_026": "医药公司合并/药物名称",
    "browsecomp_027": "2D恶魔城音乐/美国小说",
    "browsecomp_031": "电影名=地名/导演非电影专业",
    "browsecomp_032": "1993创办/民企500强",
    "browsecomp_035": "当代作家成名作/反派调酒师",
    "browsecomp_036": "球类教练/6连冠/退役年份",
    "browsecomp_038": "歌手28岁第3张专辑/婚礼日期",
    "browsecomp_039": "医学家1900留学/创办杂志",
    "webcanvas_5":   "Discogs release submission overview",
    "webcanvas_26":  "Marriott Bonvoy credit cards",
    "webcanvas_35":  "Donnie Darko cast on IMDb",
    "webcanvas_48":  "5-star coffee makers on Kohls",
    "webcanvas_58":  "MacBook Air tech specs",
    "webcanvas_80":  "5-star saltwater rods on Cabelas",
    "webcanvas_84":  "Thrill rides Six Flags Great America",
    "webcanvas_85":  "Electronic music DVDs on Discogs",
    "webcanvas_91":  "Brooklyn Nets schedule on ESPN",
    "webcanvas_101": "Clearance women's dresses on Kohls",
    "webcanvas_102": "NY Yankees MLB schedule on FoxSports",
    "webcanvas_103": "Upcoming soccer events on ESPN2",
}
