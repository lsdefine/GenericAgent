import os
import sys
import subprocess
import tempfile

# 模拟AI执行代码的过程
def simulate_ai_execution():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Handler的工作目录
    handler_cwd = os.path.join(script_dir, 'temp')
    os.makedirs(handler_cwd, exist_ok=True)
    
    # AI要执行的代码
    code_to_run = """
import os
print("=== AI代码执行环境 ===")
print(f"当前工作目录: {os.getcwd()}")
print()
print("尝试访问上级目录:")
try:
    parent_contents = os.listdir('..')
    print(f"✅ 成功: {len(parent_contents)} 个项目")
except PermissionError as e:
    print(f"❌ 权限错误: {e}")
except Exception as e:
    print(f"⚠️  其他错误: {e}")

print()
print("尝试访问 memory 目录:")
try:
    memory_contents = os.listdir('../memory')
    print(f"✅ 成功: {len(memory_contents)} 个文件")
except PermissionError as e:
    print(f"❌ 权限错误: {e}")
except Exception as e:
    print(f"⚠️  其他错误: {e}")

print()
print("尝试读取文件:")
try:
    with open('../memory/memory_management_sop.md', 'r', encoding='utf-8') as f:
        content = f.read(200)
    print(f"✅ 成功读取文件")
except PermissionError as e:
    print(f"❌ 权限错误: {e}")
except Exception as e:
    print(f"⚠️  其他错误: {e}")
"""
    
    # 创建临时文件
    tmp_file = tempfile.NamedTemporaryFile(suffix=".ai.py", delete=False, mode='w', encoding='utf-8', dir=handler_cwd)
    tmp_file.write(code_to_run)
    tmp_path = tmp_file.name
    tmp_file.close()
    
    print(f"=== 模拟AI执行 ===")
    print(f"工作目录: {handler_cwd}")
    print(f"临时文件: {tmp_path}")
    print()
    
    # 执行代码（模拟AI的code_run）
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
    
    # 读取输出
    output = []
    for line_bytes in iter(process.stdout.readline, b''):
        try: 
            line = line_bytes.decode('utf-8')
        except UnicodeDecodeError: 
            line = line_bytes.decode('gbk', errors='ignore')
        output.append(line)
        print(line, end="")
    
    process.wait()
    
    # 清理临时文件
    os.unlink(tmp_path)
    
    return ''.join(output)

if __name__ == '__main__':
    simulate_ai_execution()