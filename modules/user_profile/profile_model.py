"""
用户档案数据模型
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum


class UserLevel(Enum):
    """用户等级"""
    NEWBIE = "newbie"           # 新用户
    ACTIVE = "active"           # 活跃用户
    EXPERT = "expert"           # 专家用户
    ADMIN = "admin"             # 管理员


@dataclass
class Preference:
    """用户偏好"""
    category: str               # 偏好类别
    value: Any                  # 偏好值
    confidence: float = 0.5     # 置信度 0-1
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class UserProfile:
    """用户档案核心数据结构"""
    user_id: str
    username: str
    level: UserLevel = UserLevel.NEWBIE
    
    # 基本信息
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    total_sessions: int = 0
    
    # 偏好设置
    preferences: Dict[str, Preference] = field(default_factory=dict)
    
    # 行为统计
    statistics: Dict[str, int] = field(default_factory=dict)
    
    # 技能和知识
    skills: List[str] = field(default_factory=list)
    knowledge_domains: List[str] = field(default_factory=list)
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_preference(self, category: str, value: Any, confidence: float = 0.5):
        """添加用户偏好"""
        self.preferences[category] = Preference(
            category=category,
            value=value,
            confidence=confidence
        )
    
    def get_preference(self, category: str) -> Optional[Preference]:
        """获取用户偏好"""
        return self.preferences.get(category)
    
    def update_activity(self):
        """更新活动记录"""
        self.last_active = datetime.now()
        self.total_sessions += 1
