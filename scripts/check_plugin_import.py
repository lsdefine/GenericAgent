import importlib
try:
    m = importlib.import_module('plugins.my_auto_route_plugin')
    print('OK', getattr(m, 'plugin_status', None))
except Exception as e:
    print('IMPORT_ERROR', e)
