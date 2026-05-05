import py_compile, traceback
try:
    py_compile.compile('frontends/stapp.py', doraise=True)
    print('COMPILE_OK')
except Exception:
    traceback.print_exc()
    raise
