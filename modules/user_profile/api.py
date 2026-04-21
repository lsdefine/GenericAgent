"""
用户档案API接口层
提供与外部系统交互的接口
"""
from typing import Optional, Dict, List, Any
from .profile_manager import ProfileManager
from .profile_model import UserLevel


class ProfileAPI:
    """用户档案外部API接口"""
    
    def __init__(self, storage_dir: str = None):
        self.manager = ProfileManager(storage_dir)
    
    # === 基本档案操作 ===
    
    def create_user(self, user_id: str, username: str, level: str = "newbie") -> Dict[str, Any]:
        """创建用户档案
        
        Args:
            user_id: 用户ID
            username: 用户名
            level: 用户等级 (newbie/active/expert/admin)
        
        Returns:
            成功: {"success": true, "user_id": xxx}
            失败: {"success": false, "error": xxx}
        """
        try:
            existing = self.manager.get_profile(user_id)
            if existing:
                return {"success": False, "error": "User already exists"}
            
            profile = self.manager.create_profile(user_id, username)
            profile.level = UserLevel(level)
            self.manager.update_profile(profile)
            
            return {"success": True, "user_id": user_id}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户档案"""
        profile = self.manager.get_profile(user_id)
        if not profile:
            return None
        return self._profile_to_dict(profile)
    
    def update_user(self, user_id: str, **kwargs) -> bool:
        """更新用户信息"""
        profile = self.manager.get_profile(user_id)
        if not profile:
            return False
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        return self.manager.update_profile(profile)
    
    # === 偏好操作 ===
    
    def set_preference(self, user_id: str, category: str, value: Any, confidence: float = 0.5) -> bool:
        """设置用户偏好"""
        return self.manager.add_preference(user_id, category, value, confidence)
    
    def get_preference(self, user_id: str, category: str) -> Optional[Dict[str, Any]]:
        """获取用户偏好"""
        pref = self.manager.get_preference(user_id, category)
        if not pref:
            return None
        return {
            "category": pref.category,
            "value": pref.value,
            "confidence": pref.confidence,
            "updated_at": pref.updated_at.isoformat()
        }
    
    def get_all_preferences(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户所有偏好"""
        profile = self.manager.get_profile(user_id)
        if not profile:
            return []
        return [
            {
                "category": p.category,
                "value": p.value,
                "confidence": p.confidence
            }
            for p in profile.preferences.values()
        ]
    
    # === 活动记录 ===
    
    def record_activity(self, user_id: str) -> bool:
        """记录用户活动"""
        return self.manager.record_activity(user_id)
    
    def get_statistics(self, user_id: str) -> Optional[Dict[str, int]]:
        """获取用户统计"""
        profile = self.manager.get_profile(user_id)
        if not profile:
            return None
        return profile.statistics
    
    # === 内部方法 ===
    
    def _profile_to_dict(self, profile) -> Dict[str, Any]:
        """将档案转换为字典"""
        return {
            "user_id": profile.user_id,
            "username": profile.username,
            "level": profile.level.value,
            "created_at": profile.created_at.isoformat(),
            "last_active": profile.last_active.isoformat(),
            "total_sessions": profile.total_sessions,
            "preferences": [
                {
                    "category": p.category,
                    "value": p.value,
                    "confidence": p.confidence
                }
                for p in profile.preferences.values()
            ],
            "statistics": profile.statistics,
            "skills": profile.skills,
            "knowledge_domains": profile.knowledge_domains,
            "metadata": profile.metadata
        }
