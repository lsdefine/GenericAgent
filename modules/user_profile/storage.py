"""
用户档案存储管理器
集成_shared配置和存储资源
"""
import json
import os
from pathlib import Path
from typing import Optional, Dict
from .profile_model import UserProfile

# 集成_shared资源
import sys
shared_path = str(Path(__file__).parent.parent.parent / '_shared')
if shared_path not in sys.path:
    sys.path.insert(0, shared_path)

from config import config


class ProfileStorage:
    """用户档案持久化存储"""
    
    def __init__(self, storage_dir: str = None):
        # 使用_shared配置获取存储目录
        if storage_dir is None:
            project_root = config.get('project.root', 
                str(Path(__file__).parent.parent.parent))
            storage_dir = Path(project_root) / "01_user_profile" / "data" / "profiles"
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_profile_path(self, user_id: str) -> Path:
        """获取用户档案文件路径"""
        return self.storage_dir / f"{user_id}.json"
    
    def save(self, profile: UserProfile) -> bool:
        """保存用户档案"""
        try:
            path = self._get_profile_path(profile.user_id)
            data = {
                'user_id': profile.user_id,
                'username': profile.username,
                'level': profile.level.value,
                'created_at': profile.created_at.isoformat(),
                'last_active': profile.last_active.isoformat(),
                'total_sessions': profile.total_sessions,
                'preferences': {
                    k: {
                        'category': v.category,
                        'value': v.value,
                        'confidence': v.confidence,
                        'updated_at': v.updated_at.isoformat()
                    }
                    for k, v in profile.preferences.items()
                },
                'statistics': profile.statistics,
                'skills': profile.skills,
                'knowledge_domains': profile.knowledge_domains,
                'metadata': profile.metadata
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Save error: {e}")
            return False
    
    def load(self, user_id: str) -> Optional[UserProfile]:
        """加载用户档案"""
        try:
            path = self._get_profile_path(user_id)
            if not path.exists():
                return None
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            from datetime import datetime
            from .profile_model import UserLevel, Preference
            
            profile = UserProfile(
                user_id=data['user_id'],
                username=data['username'],
                level=UserLevel(data['level']),
                created_at=datetime.fromisoformat(data['created_at']),
                last_active=datetime.fromisoformat(data['last_active']),
                total_sessions=data['total_sessions'],
                statistics=data['statistics'],
                skills=data['skills'],
                knowledge_domains=data['knowledge_domains'],
                metadata=data['metadata']
            )
            profile.preferences = {
                k: Preference(
                    category=v['category'],
                    value=v['value'],
                    confidence=v['confidence'],
                    updated_at=datetime.fromisoformat(v['updated_at'])
                )
                for k, v in data['preferences'].items()
            }
            return profile
        except Exception as e:
            print(f"Load error: {e}")
            return None
    
    def delete(self, user_id: str) -> bool:
        """删除用户档案"""
        try:
            path = self._get_profile_path(user_id)
            if path.exists():
                path.unlink()
            return True
        except:
            return False
