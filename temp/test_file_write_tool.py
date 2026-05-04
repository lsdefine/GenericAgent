import os, sys
# ensure repo root is on sys.path so tests can import scripts.* when running the test file directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import os
from scripts.file_write_helper import write_direct, build_file_content_block, verify_file

def test_direct_write():
    p = 'temp/test_fw_output.txt'
    content = 'hello test direct'
    write_direct(p, content)
    assert verify_file(p, content)

if __name__ == '__main__':
    test_direct_write()
    print('test_direct_write passed')
