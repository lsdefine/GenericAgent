import os
from functools import lru_cache


def get_default_db_path():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root_dir, ".ga-switch", "ga-switch.db")


@lru_cache(maxsize=8)
def get_service(db_path=None):
    from .service import GASwitchService

    return GASwitchService(db_path=db_path or get_default_db_path())
