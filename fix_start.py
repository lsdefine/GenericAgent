import os, sys, subprocess, ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def fix_permissions():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    
    os.environ['GA_LANG'] = 'zh'
    
    temp_dir = os.path.join(script_dir, 'temp')
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        os.listdir(temp_dir)
        print('✅ temp 目录访问正常')
    except Exception as e:
        print(f'❌ temp 目录访问失败: {e}')
        return False
    
    try:
        os.listdir('..')
        print('✅ 上级目录访问正常')
    except Exception as e:
        print(f'❌ 上级目录访问失败: {e}')
        return False
    
    return True

def main():
    if not is_admin():
        print('⚠️ 建议以管理员身份运行')
    
    print('🔧 正在检查和修复权限...')
    if not fix_permissions():
        print('❌ 权限修复失败')
        sys.exit(1)
    
    print('🚀 启动 GenericAgent...')
    subprocess.run([sys.executable, 'agentmain.py'])

if __name__ == '__main__':
    main()
