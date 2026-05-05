import sys, importlib.util, os, pkgutil
repo = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo not in sys.path: sys.path.insert(0, repo)
print('sys.path[0]=', sys.path[0])
spec = importlib.util.find_spec('plugins')
print('plugins spec=', spec)
try:
    import plugins
    print('plugins module imported, __file__=', getattr(plugins, '__file__', None))
    print('plugins __path__=', getattr(plugins, '__path__', None))
except Exception as e:
    print('import plugins failed:', e)
print('modules in plugins dir:', list(pkgutil.iter_modules([os.path.join(repo, "plugins") ])))
