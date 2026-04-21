"""
用户画像与个性化档案系统
"""
__version__ = '1.0.0'

from .profile_model import UserProfile, UserLevel, Preference
from .storage import ProfileStorage
from .profile_manager import ProfileManager
from .api import ProfileAPI

__all__ = [
    'UserProfile', 'UserLevel', 'Preference',
    'ProfileStorage', 'ProfileManager', 'ProfileAPI'
]
