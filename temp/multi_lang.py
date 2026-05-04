#!/usr/bin/env python3
"""
Multi-Language Support Engine for GenericAgent
多语言支持引擎: 翻译、语言检测、本地化资源管理、RTL支持
支持: 离线词典、API翻译回退、复数规则、日期/数字格式化
"""

import os
import json
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Built-in language metadata
LANG_META = {
    'en': {'name': 'English', 'rtl': False, 'plural_rules': 'default'},
    'zh': {'name': '中文', 'rtl': False, 'plural_rules': 'none'},
    'ja': {'name': '日本語', 'rtl': False, 'plural_rules': 'none'},
    'ko': {'name': '한국어', 'rtl': False, 'plural_rules': 'none'},
    'fr': {'name': 'Français', 'rtl': False, 'plural_rules': 'default'},
    'de': {'name': 'Deutsch', 'rtl': False, 'plural_rules': 'default'},
    'es': {'name': 'Español', 'rtl': False, 'plural_rules': 'default'},
    'ar': {'name': 'العربية', 'rtl': True, 'plural_rules': 'complex'},
    'he': {'name': 'עברית', 'rtl': True, 'plural_rules': 'default'},
    'ru': {'name': 'Русский', 'rtl': False, 'plural_rules': 'complex'},
}

class TranslationCache:
    def __init__(self, cache_file: str = ".i18n_cache.json"):
        self.cache_file = cache_file
        self._cache: Dict[str, Dict[str, str]] = {}
        self._load()
    
    def _load(self):
        if os.path.exists(self.cache_file):
            with open(self.cache_file) as f:
                self._cache = json.load(f)
    
    def _save(self):
        with open(self.cache_file, 'w') as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)
    
    def get(self, key: str, lang: str) -> Optional[str]:
        return self._cache.get(key, {}).get(lang)
    
    def set(self, key: str, lang: str, value: str):
        if key not in self._cache:
            self._cache[key] = {}
        self._cache[key][lang] = value
        self._save()


class MultiLangEngine:
    def __init__(self, locale_dir: str = ".locales", default_lang: str = "en"):
        self.locale_dir = locale_dir
        self.default_lang = default_lang
        self.current_lang = default_lang
        self.translations: Dict[str, Dict[str, str]] = defaultdict(dict)
        self.cache = TranslationCache()
        os.makedirs(locale_dir, exist_ok=True)
        self._load_locales()
    
    def _load_locales(self):
        for fname in os.listdir(self.locale_dir):
            if fname.endswith('.json'):
                lang = fname[:-5]
                fpath = os.path.join(self.locale_dir, fname)
                with open(fpath, encoding='utf-8') as f:
                    data = json.load(f)
                for key, val in data.items():
                    self.translations[key][lang] = val
    
    def add_translation(self, key: str, lang: str, text: str):
        self.translations[key][lang] = text
        self.cache.set(key, lang, text)
        # Save to locale file
        fpath = os.path.join(self.locale_dir, f"{lang}.json")
        if os.path.exists(fpath):
            with open(fpath, encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}
        data[key] = text
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def translate(self, key: str, lang: str = None) -> str:
        lang = lang or self.current_lang
        # Check loaded translations
        if key in self.translations and lang in self.translations[key]:
            return self.translations[key][lang]
        # Check cache
        cached = self.cache.get(key, lang)
        if cached:
            return cached
        # Fallback to default
        if key in self.translations and self.default_lang in self.translations[key]:
            return self.translations[key][self.default_lang]
        # Fallback to key itself
        return key
    
    def detect_language(self, text: str) -> str:
        """Simple language detection based on character ranges"""
        has_cjk = any('\u4e00' <= c <= '\u9fff' for c in text)
        has_hiragana = any('\u3040' <= c <= '\u309f' for c in text)
        has_katakana = any('\u30a0' <= '\u30ff' for c in text)
        has_cyrillic = any('\u0400' <= c <= '\u04ff' for c in text)
        has_arabic = any('\u0600' <= c <= '\u06ff' for c in text)
        has_hebrew = any('\u0590' <= c <= '\u05ff' for c in text)
        
        if has_hiragana or has_katakana:
            return 'ja'
        if has_cjk:
            return 'zh'
        if has_katakana:
            return 'ko'
        if has_cyrillic:
            return 'ru'
        if has_arabic:
            return 'ar'
        if has_hebrew:
            return 'he'
        return 'en'
    
    def format_number(self, number: float, lang: str = None, decimals: int = 2) -> str:
        lang = lang or self.current_lang
        if lang in ['de', 'ru']:
            return f"{number:,.{decimals}f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        if lang == 'fr':
            return f"{number:,.{decimals}f}".replace(',', 'X').replace('.', ',').replace('X', ' ')
        if lang in ['zh', 'ja', 'ko']:
            return f"{number:.{decimals}f}"
        return f"{number:,.{decimals}f}"
    
    def format_date(self, dt: datetime, lang: str = None) -> str:
        lang = lang or self.current_lang
        if lang == 'zh':
            return dt.strftime('%Y年%m月%d日')
        if lang == 'ja':
            return dt.strftime('%Y年%m月%d日')
        if lang == 'fr':
            return dt.strftime('%d/%m/%Y')
        if lang == 'de':
            return dt.strftime('%d.%m.%Y')
        return dt.strftime('%Y-%m-%d')
    
    def pluralize(self, key: str, count: int, lang: str = None) -> str:
        lang = lang or self.current_lang
        meta = LANG_META.get(lang, LANG_META['en'])
        
        if meta['plural_rules'] == 'none':
            return self.translate(key, lang)
        
        if lang == 'ru':
            abs_count = abs(count) % 100
            last_digit = abs_count % 10
            if 11 <= abs_count <= 14:
                return self.translate(f"{key}_many", lang)
            if last_digit == 1:
                return self.translate(f"{key}_one", lang)
            if 2 <= last_digit <= 4:
                return self.translate(f"{key}_few", lang)
            return self.translate(f"{key}_many", lang)
        
        # Default English-style
        if count == 1:
            return self.translate(f"{key}_one", lang)
        return self.translate(f"{key}_many", lang)
    
    def get_rtl_css(self) -> str:
        meta = LANG_META.get(self.current_lang, {})
        if meta.get('rtl'):
            return "direction: rtl; text-align: right;"
        return "direction: ltr; text-align: left;"
    
    def get_supported_languages(self) -> List[Dict]:
        return [{'code': k, **v} for k, v in LANG_META.items()]


if __name__ == '__main__':
    engine = MultiLangEngine()
    
    engine.add_translation("greeting", "en", "Hello!")
    engine.add_translation("greeting", "zh", "你好！")
    engine.add_translation("greeting", "ja", "こんにちは！")
    engine.add_translation("greeting", "fr", "Bonjour !")
    
    engine.add_translation("items_one", "en", "1 item")
    engine.add_translation("items_many", "en", "{count} items")
    engine.add_translation("items_one", "ru", "1 элемент")
    engine.add_translation("items_few", "ru", "{count} элемента")
    engine.add_translation("items_many", "ru", "{count} элементов")
    
    print("=== Translation ===")
    print(f"EN: {engine.translate('greeting', 'en')}")
    print(f"ZH: {engine.translate('greeting', 'zh')}")
    print(f"JA: {engine.translate('greeting', 'ja')}")
    print(f"FR: {engine.translate('greeting', 'fr')}")
    
    print("\n=== Language Detection ===")
    tests = ["Hello world", "你好世界", "こんにちは", "Привет мир"]
    for t in tests:
        print(f"  '{t}' -> {engine.detect_language(t)}")
    
    print("\n=== Number Formatting ===")
    print(f"  EN: {engine.format_number(1234567.89, 'en')}")
    print(f"  DE: {engine.format_number(1234567.89, 'de')}")
    print(f"  FR: {engine.format_number(1234567.89, 'fr')}")
    
    print("\n=== Pluralization ===")
    print(f"  EN 1: {engine.pluralize('items', 1, 'en')}")
    print(f"  EN 5: {engine.pluralize('items', 5, 'en')}")
    print(f"  RU 1: {engine.pluralize('items', 1, 'ru')}")
    print(f"  RU 3: {engine.pluralize('items', 3, 'ru')}")
    print(f"  RU 5: {engine.pluralize('items', 5, 'ru')}")
    print(f"  RU 21: {engine.pluralize('items', 21, 'ru')}")
