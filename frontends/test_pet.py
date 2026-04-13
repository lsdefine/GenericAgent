#!/usr/bin/env python3
"""Test script for desktop pet v2"""
import subprocess
import sys
import os

script_dir = os.path.dirname(os.path.abspath(__file__))
pet_script = os.path.join(script_dir, 'desktop_pet_v2.pyw')

print("Testing desktop pet v2...")
print(f"Script: {pet_script}")

# Test with default skin
print("\n1. Testing with default skin...")
subprocess.run([sys.executable, pet_script])
