#!/usr/bin/env python3
"""Configuration Manager - Unified config loading with env/var/dotenv support"""
import os
import json
from typing import Any, Optional, Dict

class ConfigManager:
    """Unified configuration management"""
    
    def __init__(self, config_path: str = "config.json", env_prefix: str = "GA_"):
        self.config_path = config_path
        self.env_prefix = env_prefix
        self._config: Dict[str, Any] = {}
        self.load()
        
    def load(self):
        """Load configuration from file, then override with env vars"""
        # Load from file
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                try:
                    self._config = json.load(f)
                except json.JSONDecodeError:
                    self._config = {}
        
        # Override with environment variables
        for key, value in os.environ.items():
            if key.startswith(self.env_prefix):
                config_key = key[len(self.env_prefix):].lower()
                self._config[config_key] = self._parse_value(value)
                
    def _parse_value(self, value: str) -> Any:
        """Parse string value to appropriate type"""
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value
        
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self._config.get(key, default)
        
    def set(self, key: str, value: Any):
        """Set configuration value"""
        self._config[key] = value
        
    def save(self):
        """Save configuration to file"""
        with open(self.config_path, 'w') as f:
            json.dump(self._config, f, indent=2)
            
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration"""
        return dict(self._config)
        
    def validate(self, schema: Dict[str, type]) -> bool:
        """Validate configuration against schema"""
        for key, expected_type in schema.items():
            value = self.get(key)
            if value is None:
                print(f"Missing required config: {key}")
                return False
            if not isinstance(value, expected_type):
                print(f"Invalid type for {key}: expected {expected_type.__name__}, got {type(value).__name__}")
                return False
        return True


if __name__ == "__main__":
    # Set some env vars for testing
    os.environ['GA_DEBUG'] = 'true'
    os.environ['GA_PORT'] = '8080'
    os.environ['GA_API_KEY'] = 'test-key-123'
    
    config = ConfigManager()
    
    # Test basic config
    config.set('app_name', 'GenericAgent')
    config.set('version', '1.0.0')
    config.set('max_retries', 3)
    
    print(f"App Name: {config.get('app_name')}")
    print(f"Debug: {config.get('debug')}")
    print(f"Port: {config.get('port')}")
    print(f"API Key: {config.get('api_key')}")
    print(f"Max Retries: {config.get('max_retries')}")
    
    # Test validation
    schema = {'app_name': str, 'max_retries': int}
    valid = config.validate(schema)
    print(f"\nConfig valid: {valid}")
    
    # Test save/load
    config.save()
    print("\nConfig saved to config.json")
    
    # Reload
    config2 = ConfigManager()
    print(f"Reloaded app_name: {config2.get('app_name')}")
    
    # Cleanup
    os.remove('config.json')
    print("Config cleaned up.")
