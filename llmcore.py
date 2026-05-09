6468291e0cb02c75450648842b818ca439c121bc
class SmartRouter:
    """根据用户查询自动分类任务复杂度，推荐 simple(flash) 或 complex(pro) 模型组。"""
    
    COMPLEX_KEYWORDS = [
        '代码', '框架', '实现', '架构', '设计模式', '重构', '调试', '算法',
        '数据库', 'SQL', 'API', '接口', '部署', '性能', '优化', '爬虫',
        'web', 'flask', 'django', 'git', 'docker', 'k8s', 'kubernetes',
        '分析', '设计', '方案', '架构设计', '系统设计', '单元测试', 'CI/CD',
        'pytest', 'unittest', '异步', '多线程', '并发', '缓存', 'redis',
        'nginx', 'linux', 'bash', 'shell', '正则', 'ORM', 'REST', 'graphql',
    ]
    
    def __init__(self):
        self._enabled = False
        self._last_classification = None
    
    def enable(self):
        self._enabled = True
    
    def disable(self):
        self._enabled = False
    
    @property
    def enabled(self):
        return self._enabled
    
    def classify(self, query: str) -> str:
        """返回 'simple' 或 'complex'"""
        q = query.strip()
        if not q:
            return 'simple'
        # 短查询(<=8字符)且无关键词 → simple
        if len(q) <= 8:
            self._last_classification = 'simple'
            return 'simple'
        # 关键词命中 → complex
        q_lower = q.lower()
        for kw in self.COMPLEX_KEYWORDS:
            if kw.lower() in q_lower:
                self._last_classification = 'complex'
                return 'complex'
        # 含代码特征 → complex
        if any(c in q for c in ['{', '}', ';', '==', '!=', '=>', '->', 'def ', 'class ', 'import ']):
            self._last_classification = 'complex'
            return 'complex'
        self._last_classification = 'simple'
        return 'simple'
    
    def get_last(self):
        return self._last_classification
    
    def get_route(self, query: str) -> str:
        """返回 'simple' 或 'complex' based on query and enabled state"""
        if not self._enabled:
            return None  # 未启用，由外部决定
        return self.classify(query)

