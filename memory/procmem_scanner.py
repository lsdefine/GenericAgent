import ctypes
import ctypes.wintypes
import argparse
import yara
import sys
import os
import json

# Define WinAPI Types for 64-bit compatibility
PHANDLE = ctypes.wintypes.HANDLE
LPCVOID = ctypes.c_void_p
LPVOID = ctypes.c_void_p
SIZE_T = ctypes.c_size_t

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", LPVOID),
        ("AllocationBase", LPVOID),
        ("AllocationProtect", ctypes.wintypes.DWORD),
        ("RegionSize", SIZE_T),
        ("State", ctypes.wintypes.DWORD),
        ("Protect", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
    ]

# Explicitly setup kernel32 functions with precise types
k32 = ctypes.windll.kernel32
k32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
k32.OpenProcess.restype = PHANDLE

k32.VirtualQueryEx.argtypes = [PHANDLE, LPCVOID, ctypes.POINTER(MEMORY_BASIC_INFORMATION), SIZE_T]
k32.VirtualQueryEx.restype = SIZE_T

k32.ReadProcessMemory.argtypes = [PHANDLE, LPCVOID, LPVOID, SIZE_T, ctypes.POINTER(SIZE_T)]
k32.ReadProcessMemory.restype = ctypes.wintypes.BOOL

def is_hex_pattern(pattern):
    clean = pattern.replace(" ", "").replace("??", "")
    return all(c in "0123456789abcdefABCDEF" for c in clean) and (len(clean) % 2 == 0 or "??" in pattern)

def build_rules(pattern, mode='auto'):
    use_hex = (mode == 'hex') or (mode == 'auto' and is_hex_pattern(pattern))
    if use_hex:
        rule_text = f'rule CustomSearch {{ strings: $h = {{ {pattern.strip()} }} condition: $h }}'
    else:
        escaped = pattern.replace('\\', '\\\\').replace('"', '\\"')
        rule_text = f'rule CustomSearch {{ strings: $s = "{escaped}" ascii wide condition: $s }}'
    return yara.compile(source=rule_text)

def format_llm_context(data, offset, base_addr, length=64):
    start = max(0, offset - length)
    end = min(len(data), offset + length + 16)
    chunk = data[start:end]
    abs_addr = (base_addr if base_addr else 0) + offset
    return {
        "address": hex(abs_addr),
        "offset": hex(offset),
        "hex": chunk.hex(),
        "ascii": "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk),
        "hit_pos": offset - start
    }

def scan_memory(pid, pattern, context_size=256, mode='auto', llm_mode=False):
    rules = build_rules(pattern, mode)
    h_proc = k32.OpenProcess(0x0400 | 0x0010, False, pid)
    if not h_proc:
        # OpenProcess failed: might be system process or higher integrity level
        return [f"Error: Cannot open process {pid}. (ErrorCode: {k32.GetLastError()})"]

    results = []
    curr_addr = 0
    mbi = MEMORY_BASIC_INFORMATION()
    
    # Range for 64-bit user space
    max_addr = 0x7FFFFFFFFFFF

    while curr_addr < max_addr:
        # Use cast to ensure pointer type is correct for 64-bit
        res = k32.VirtualQueryEx(h_proc, ctypes.cast(curr_addr, LPCVOID), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if res == 0: break
        
        # MEM_COMMIT = 0x1000, PAGE_READABLE bitmask
        if mbi.State == 0x1000 and (mbi.Protect & 0xEE): # 0xEE covers common readable flags
            buf = ctypes.create_string_buffer(mbi.RegionSize)
            read = SIZE_T(0)
            if k32.ReadProcessMemory(h_proc, ctypes.cast(mbi.BaseAddress, LPCVOID), buf, mbi.RegionSize, ctypes.byref(read)):
                data = buf.raw[:read.value]
                for match in rules.match(data=data):
                    for inst in match.strings:
                        offset = inst.instances[0].offset
                        matched_data = inst.instances[0].matched_data
                        base = mbi.BaseAddress if mbi.BaseAddress else 0
                        if llm_mode:
                            results.append(format_llm_context(data, offset, base, length=context_size))
                        else:
                            # Expand context based on context_size to capture full KEY+SALT
                            start = max(0, offset - context_size)
                            end = min(len(data), offset + len(matched_data) + context_size)
                            results.append(f"Addr: {hex(base+offset)}\nHex: {data[start:end].hex()}")

        # Update address using the region size
        next_addr = (mbi.BaseAddress if mbi.BaseAddress else 0) + mbi.RegionSize
        if next_addr <= curr_addr: break
        curr_addr = next_addr

    k32.CloseHandle(h_proc)
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("pattern", type=str)
    parser.add_argument("--mode", default='auto')
    parser.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    try:
        res = scan_memory(args.pid, args.pattern, mode=args.mode, llm_mode=args.llm)
        print(json.dumps(res, indent=2) if args.llm else f"Matches: {len(res)}")
    except Exception as e:
        print(f"Error: {e}")