"""
用户档案管理器 - Facade
"""
from typing import Optional, Dict, List
from .profile_model import UserProfile, UserLevel, Preference
from .storage import ProfileStorage


class ProfileManager:
    """用户档案统一管理器"""
    
    def __init__(self, storage_dir: str = None):
        self.storage = ProfileStorage(storage_dir)
        self._cache: Dict[str, UserProfile] = {}
    
    def create_profile(self, user_id: str, username: str) -> UserProfile:
        """创建新用户档案"""
        profile = UserProfile(user_id=user_id, username=username)
        self.storage.save(profile)
        self._cache[user_id] = profile
        return profile
    
    def get_profile(self, user_id: str) -> Optional[UserProfile]:
        """获取用户档案"""
        if user_id in self._cache:
            return self._cache[user_id]
        profile = self.storage.load(user_id)
        if profile:
            self._cache[user_id] = profile
        return profile
    
    def update_profile(self, profile: UserProfile) -> bool:
        """更新用户档案"""
        self.storage.save(profile)
        self._cache[profile.user_id] = profile
        return True
    
    def add_preference(self, user_id: str, category: str, value, confidence: float = 0.5) -> bool:
        """添加用户偏好"""
        profile = self.get_profile(user_id)
        if not profile:
            return False
        profile.add_preference(category, value, confidence)
        return self.update_profile(profile)
    
    def get_preference(self, user_id: str, category: str) -> Optional[Preference]:
        """获取用户偏好"""
        profile = self.get_profile(user_id)
        if not profile:
            return None
        return profile.get_preference(category)
    
    def record_activity(self, user_id: str) -> bool:
        """记录用户活动"""
        profile = self.get_profile(user_id)
        if not profile:
            return False
        profile.update_activity()
        return self.update_profile(profile)
