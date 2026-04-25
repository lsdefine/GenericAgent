import os
import subprocess
import sys

def check_permissions():
    print("=" * 60)
    print("权限诊断脚本")
    print("=" * 60)
    
    # 1. 检查当前工作目录
    try:
        cwd = os.getcwd()
        print(f"\n[1] 当前工作目录: {cwd}")
    except Exception as e:
        print(f"\n[1] 获取当前目录失败: {e}")
    
    # 2. 检查上级目录访问
    print("\n[2] 尝试访问上级目录:")
    try:
        parent_contents = os.listdir('..')
        print(f"    ✅ 成功列出上级目录内容: {len(parent_contents)} 个项目")
        print(f"    内容: {parent_contents[:10]}..." if len(parent_contents) > 10 else f"    内容: {parent_contents}")
    except PermissionError as e:
        print(f"    ❌ 权限错误: {e}")
    except Exception as e:
        print(f"    ⚠️  其他错误: {e}")
    
    # 3. 检查 memory 目录
    print("\n[3] 尝试访问 memory 目录:")
    try:
        memory_path = '../memory'
        if os.path.exists(memory_path):
            memory_contents = os.listdir(memory_path)
            print(f"    ✅ 成功列出 memory 目录: {len(memory_contents)} 个项目")
        else:
            print(f"    ⚠️  memory 目录不存在: {memory_path}")
    except PermissionError as e:
        print(f"    ❌ 权限错误: {e}")
    except Exception as e:
        print(f"    ⚠️  其他错误: {e}")
    
    # 4. 检查 E:\AI 目录
    print("\n[4] 尝试访问 E:\\AI 目录:")
    try:
        ai_path = 'E:\\AI'
        if os.path.exists(ai_path):
            ai_contents = os.listdir(ai_path)
            print(f"    ✅ 成功列出 E:\\AI 目录: {len(ai_contents)} 个项目")
        else:
            print(f"    ⚠️  E:\\AI 目录不存在")
    except PermissionError as e:
        print(f"    ❌ 权限错误: {e}")
    except Exception as e:
        print(f"    ⚠️  其他错误: {e}")
    
    # 5. 检查用户信息
    print("\n[5] 用户信息:")
    try:
        if sys.platform == 'win32':
            result = subprocess.run(['whoami'], capture_output=True, text=True)
            print(f"    当前用户: {result.stdout.strip()}")
            
            # 检查是否管理员
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
            print(f"    是否管理员: {'是' if is_admin else '否'}")
    except Exception as e:
        print(f"    获取用户信息失败: {e}")
    
    # 6. 检查 NTFS 权限 (通过 icacls)
    print("\n[6] NTFS 权限检查:")
    try:
        result = subprocess.run(
            ['icacls', os.getcwd()],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        print(f"    当前目录权限:\n{result.stdout[:1000]}")
    except Exception as e:
        print(f"    检查权限失败: {e}")
    
    # 7. 检查环境变量
    print("\n[7] 环境变量检查:")
    print(f"    PYTHONPATH: {os.environ.get('PYTHONPATH', '未设置')}")
    print(f"    PATH: {os.environ.get('PATH', '未设置')[:100]}...")
    
    # 8. 检查目录属性
    print("\n[8] 目录属性检查:")
    try:
        cwd_stat = os.stat('.')
        print(f"    当前目录 stat: {cwd_stat}")
        print(f"    权限位: {oct(cwd_stat.st_mode)[-4:]}")
    except Exception as e:
        print(f"    获取目录属性失败: {e}")
    
    print("\n" + "=" * 60)
    print("诊断完成!")
    print("=" * 60)

if __name__ == "__main__":
    check_permissions()