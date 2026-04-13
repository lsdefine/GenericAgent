#!/usr/bin/env python3
"""Test GA integration with desktop pet"""
import sys
import os
import time
from urllib.request import urlopen
from urllib.parse import quote

# Simulate what stapp.py does
def test_ga_integration():
    print("Testing GA → Desktop Pet integration\n")

    # Test 1: Send turn notification (like GA does)
    print("1. Testing turn notification...")
    try:
        msg = "🔄 Turn 1\n正在执行任务\n✅ 任务已完成"
        # URL encode for Chinese characters
        encoded_msg = quote(msg)
        response = urlopen(f'http://127.0.0.1:51983/?msg={encoded_msg}', timeout=2)
        if response.status == 200:
            print("   ✓ Turn notification sent")
        time.sleep(2)
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False

    # Test 2: Change state based on activity
    print("\n2. Testing activity states...")
    states = ['idle', 'walk', 'run', 'sprint']
    for state in states:
        try:
            response = urlopen(f'http://127.0.0.1:51983/?state={state}', timeout=2)
            if response.status == 200:
                print(f"   ✓ State: {state}")
            time.sleep(1.5)
        except Exception as e:
            print(f"   ✗ State {state} failed: {e}")
            return False

    # Test 3: Send completion message
    print("\n3. Testing completion message...")
    try:
        msg = "✅ 所有任务已完成！"
        encoded_msg = quote(msg)
        response = urlopen(f'http://127.0.0.1:51983/?msg={encoded_msg}', timeout=2)
        if response.status == 200:
            print("   ✓ Completion message sent")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        return False

    print("\n✓ All integration tests passed!")
    print("\n提示：桌宠应该显示了消息气泡并切换了动画状态")
    return True

if __name__ == '__main__':
    print("请先手动启动桌宠：python3 desktop_pet_v2.pyw")
    print("然后按回车继续测试...")
    input()

    test_ga_integration()
