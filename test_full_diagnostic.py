import os
import sys
import subprocess
import tempfile

def run_diagnostic():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    handler_cwd = os.path.join(script_dir, 'temp')
    
    # 模拟AI执行的完整代码
    code_to_run = """
import os
import sys

print("="*60)
print("AI执行环境诊断")
print("="*60)

# 1. 基本信息
print("\\n[1] 基本信息:")
print(f"Python版本: {sys.version}")
print(f"当前工作目录: {os.getcwd()}")
print(f"脚本路径: {os.path.abspath(__file__)}")

# 2. 环境变量
print("\\n[2] 环境变量:")
print(f"HOME: {os.environ.get('HOME', '未设置')}")
print(f"USERPROFILE: {os.environ.get('USERPROFILE', '未设置')}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH', '未设置')}")

# 3. 测试上级目录访问
print("\\n[3] 上级目录访问测试:")
test_paths = ['..', '../memory', '../..']
for p in test_paths:
    try:
        abs_path = os.path.abspath(p)
        contents = os.listdir(p)
        print(f"✅ {p} -> {abs_path} (包含 {len(contents)} 个项目)")
    except PermissionError as e:
        print(f"❌ {p} -> 权限错误: {e}")
    except FileNotFoundError:
        print(f"⚠️  {p} -> 路径不存在")
    except Exception as e:
        print(f"❓ {p} -> 未知错误: {e}")

# 4. 测试文件读取
print("\\n[4] 文件读取测试:")
test_files = [
    '../memory/memory_management_sop.md',
    '../agentmain.py',
    '../mykey.py'
]
for f in test_files:
    try:
        abs_path = os.path.abspath(f)
        if os.path.exists(f):
            with open(f, 'r', encoding='utf-8') as file:
                content = file.read(100)
            print(f"✅ {f} -> 读取成功")
        else:
            print(f"⚠️  {f} -> 文件不存在")
    except PermissionError as e:
        print(f"❌ {f} -> 权限错误: {e}")
    except Exception as e:
        print(f"❓ {f} -> 未知错误: {e}")

# 5. 测试文件写入
print("\\n[5] 文件写入测试:")
test_write_path = './test_write.txt'
try:
    with open(test_write_path, 'w', encoding='utf-8') as f:
        f.write('test')
    print(f"✅ 写入 {test_write_path} 成功")
    os.remove(test_write_path)
except PermissionError as e:
    print(f"❌ 写入失败: {e}")
except Exception as e:
    print(f"❓ 写入未知错误: {e}")

# 6. 检查 os 模块权限
print("\\n[6] OS模块权限检查:")
try:
    stat_info = os.stat('.')
    print(f"当前目录权限: {oct(stat_info.st_mode)[-4:]}")
except Exception as e:
    print(f"获取权限失败: {e}")

print("\\n" + "="*60)
print("诊断完成")
print("="*60)
"""
    
    # 创建临时文件（模拟AI的code_run）
    tmp_file = tempfile.NamedTemporaryFile(suffix=".ai.py", delete=False, mode='w', encoding='utf-8', dir=handler_cwd)
    
    # 添加 code_run_header.py 的内容
    cr_header = os.path.join(script_dir, 'assets', 'code_run_header.py')
    if os.path.exists(cr_header):
        tmp_file.write(open(cr_header, encoding='utf-8').read())
    
    tmp_file.write(code_to_run)
    tmp_path = tmp_file.name
    tmp_file.close()
    
    print(f"=== 运行诊断脚本 ===")
    print(f"工作目录: {handler_cwd}")
    print(f"临时文件: {tmp_path}")
    print()
    
    # 执行
    cmd = [sys.executable, "-X", "utf8", "-u", tmp_path]
    
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT,
        bufsize=0, 
        cwd=handler_cwd, 
        startupinfo=startupinfo
    )
    
    for line_bytes in iter(process.stdout.readline, b''):
        try: 
            line = line_bytes.decode('utf-8')
        except UnicodeDecodeError: 
            line = line_bytes.decode('gbk', errors='ignore')
        print(line, end="")
    
    process.wait()
    os.unlink(tmp_path)

if __name__ == '__main__':
    run_diagnostic()