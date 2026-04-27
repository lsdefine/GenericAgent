
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock


class ChatLogger:
    def __init__(self):
        self.log_dir = Path(__file__).parent.parent / "logs" / "chat_logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.logger_file_map = {}

    def get_logger(self, platform_name):
        if platform_name not in self.logger_file_map:
            logger = logging.getLogger(f"platform.{platform_name}")
            logger.setLevel(logging.INFO)
            
            # 文本日志 (.log)
            txt_path = self.log_dir / f"{platform_name}.log"
            fh_txt = logging.FileHandler(txt_path, encoding="utf-8")
            fmt_txt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
            fh_txt.setFormatter(fmt_txt)
            
            # JSONL 结构化日志 (.jsonl)
            json_path = self.log_dir / f"{platform_name}_entries.jsonl"
            
            logger.addHandler(fh_txt)
            self.logger_file_map[platform_name] = {
                "logger": logger,
                "txt_handler": fh_txt,
                "json_path": json_path
            }
        return self.logger_file_map[platform_name]

    def save_message(self, platform, user_id, user_msg, ai_response=None, extra_info=None):
        plat_key = platform.lower().replace("app", "").replace("web", "")
        
        entry_type = "ai_response" if ai_response else "user_input"
        content = ai_response if ai_response else user_msg
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "user_id": str(user_id),
            "msg_type": entry_type,
            "content": str(content),
            "extra": extra_info or {}
        }
        
        try:
            entry_map = self.get_logger(plat_key)
            text_entry = f"[{datetime.now().strftime('%H:%M:%S')}] [{platform}:{user_id}] "
            if ai_response:
                text_entry += f"AI: {str(ai_response)[:200]}"
            else:
                text_entry += f"User Input: {str(user_msg)[:200]}"
            
            with self.lock:
                entry_map["logger"].info(text_entry)
                with open(entry_map["json_path"], "a", encoding="utf-8") as f:
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[ChatLogger Error] Failed to log on {plat_key}: {e}")


# 全局单例
_chat_logger_instance = None

def get_chat_logger():
    global _chat_logger_instance
    if _chat_logger_instance is None:
        _chat_logger_instance = ChatLogger()
    return _chat_logger_instance
