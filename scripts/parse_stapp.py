import ast, traceback
p='frontends/stapp.py'
try:
    s=open(p,'r',encoding='utf-8').read()
    ast.parse(s)
    print('PARSE_OK')
except Exception:
    traceback.print_exc()
    raise
