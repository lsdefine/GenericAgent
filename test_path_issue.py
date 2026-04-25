import os
import sys

# 获取脚本目录
script_dir = os.path.dirname(os.path.abspath(__file__))
print(f"脚本目录: {script_dir}")

# 模拟 Handler 的工作目录设置
cwd = os.path.join(script_dir, 'temp')
print(f"Handler工作目录: {cwd}")

# 模拟 _get_abs_path 方法
def _get_abs_path(path):
    if not path: return ""
    return os.path.abspath(os.path.join(cwd, path))

# 测试各种路径
test_paths = [
    '../',
    '../memory',
    '../memory/test.txt',
    './test.txt',
    'test.txt',
    '/test.txt',
    '../..'
]

print("\n=== 路径解析测试 ===")
for path in test_paths:
    try:
        abs_path = _get_abs_path(path)
        exists = os.path.exists(abs_path)
        is_dir = os.path.isdir(abs_path) if exists else False
        can_access = True
        if exists:
            try:
                if is_dir:
                    files = os.listdir(abs_path)
                    print(f"✅ {path} -> {abs_path} (目录，包含 {len(files)} 个文件)")
                else:
                    with open(abs_path, 'r') as f:
                        content = f.read(100)
                    print(f"✅ {path} -> {abs_path} (文件)")
            except PermissionError as e:
                can_access = False
                print(f"❌ {path} -> {abs_path} (权限错误: {e})")
            except Exception as e:
                print(f"⚠️  {path} -> {abs_path} (其他错误: {e})")
        else:
            print(f"ℹ️  {path} -> {abs_path} (不存在)")
    except Exception as e:
        print(f"❌ {path} -> 解析失败: {e}")

print("\n=== 当前进程信息 ===")
print(f"当前工作目录: {os.getcwd()}")
print(f"Python可执行文件: {sys.executable}")
print(f"是否管理员: {os.name == 'nt' and __import__('ctypes').windll.shell32.IsUserAnAdmin()}")

# 测试 subprocess 执行环境
print("\n=== subprocess 环境测试 ===")
import subprocess
result = subprocess.run(
    ['python', '-c', 'import os; print(os.getcwd()); print(os.listdir(".."))'],
    capture_output=True,
    text=True,
    cwd=cwd
)
print(f"stdout: {result.stdout}")
if result.stderr:
    print(f"stderr: {result.stderr}")
if result.returncode != 0:
    print(f"返回码: {result.returncode}")