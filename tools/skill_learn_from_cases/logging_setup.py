"""
logging_setup.py — 结构化日志配置

依据 structured_logging 技能模式:
  - 日志同时输出到文件和控制台
  - 日志级别: DEBUG/INFO/WARNING/ERROR
  - 使用结构化格式便于排查

用法:
  from tools.skill_learn_from_cases.logging_setup import logger
  logger.info("Phase 1 completed")
  logger.debug("Search query: %s", query)
  logger.error("LLM call failed: %s", e)
"""
import logging, sys, os

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "temp")

def setup_logger(name: str = "skill_learn", level: int = logging.WARNING) -> logging.Logger:
    """配置日志器"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 控制台 handler (WARNING 及以上)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console)
    
    # 文件 handler (所有级别)
    os.makedirs(_LOG_DIR, exist_ok=True)
    fh = logging.FileHandler(os.path.join(_LOG_DIR, "skill_learn.log"), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(fh)
    
    return logger

logger = setup_logger()
