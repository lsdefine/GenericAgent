#!/usr/bin/env python3
"""完整测试：模拟从 launch.pyw 启动 GA 并使用桌宠功能"""
import subprocess
import sys
import os
import time
from urllib.request import urlopen
from urllib.parse import quote

def test_desktop_pet():
    print("=" * 60)
    print("桌面宠物完整测试")
    print("=" * 60)

    # 1. 检查文件
    print("\n1. 检查文件...")
    pet_script = 'frontends/desktop_pet_v2.pyw'
    skins_dir = 'frontends/skins'

    if not os.path.exists(pet_script):
        print(f"✗ 找不到: {pet_script}")
        return False
    print(f"✓ 桌宠脚本: {pet_script}")

    if not os.path.exists(skins_dir):
        print(f"✗ 找不到: {skins_dir}")
        return False

    skin_count = len([d for d in os.listdir(skins_dir)
                     if os.path.isdir(os.path.join(skins_dir, d))
                     and os.path.exists(os.path.join(skins_dir, d, 'skin.json'))])
    print(f"✓ 皮肤目录: {skins_dir} ({skin_count} 个皮肤)")

    # 2. 启动桌宠
    print("\n2. 启动桌宠...")
    kwargs = {'creationflags': 0x08} if sys.platform == 'win32' else {}
    proc = subprocess.Popen([sys.executable, pet_script], **kwargs)
    print(f"✓ 进程 PID: {proc.pid}")

    time.sleep(3)

    if proc.poll() is not None:
        print("✗ 桌宠启动失败")
        return False
    print("✓ 桌宠正在运行")

    # 3. 测试 HTTP 接口
    print("\n3. 测试 HTTP 接口...")
    try:
        # 测试消息
        msg = "🔄 Turn 1\n正在执行任务..."
        response = urlopen(f'http://127.0.0.1:51983/?msg={quote(msg)}', timeout=2)
        print(f"✓ 发送消息: {response.status}")
        time.sleep(2)

        # 测试动画状态切换
        states = ['walk', 'run', 'sprint', 'idle']
        for state in states:
            response = urlopen(f'http://127.0.0.1:51983/?state={state}', timeout=2)
            print(f"✓ 切换状态 {state}: {response.status}")
            time.sleep(1.5)

        # 发送完成消息
        msg = "✅ 任务已完成！"
        response = urlopen(f'http://127.0.0.1:51983/?msg={quote(msg)}', timeout=2)
        print(f"✓ 完成消息: {response.status}")

    except Exception as e:
        print(f"✗ HTTP 测试失败: {e}")
        proc.terminate()
        return False

    # 4. 总结
    print("\n" + "=" * 60)
    print("✓ 所有测试通过！")
    print("=" * 60)
    print("\n桌宠功能说明：")
    print("  • 单击拖动 - 移动桌宠位置")
    print("  • 双击 - 关闭桌宠")
    print("  • 右键 - 打开菜单（切换皮肤/动画）")
    print("\n从 GA 使用：")
    print("  1. 运行: python3 launch.pyw")
    print("  2. 点击侧边栏的 '🐱 桌面宠物' 按钮")
    print("  3. 每个 turn 结束时会自动显示通知")
    print("\n请手动关闭桌宠窗口（双击）来结束测试")

    return True

if __name__ == '__main__':
    os.chdir('/Users/lwj/Documents/projects/a3lab/ga_zhuochong')
    test_desktop_pet()
