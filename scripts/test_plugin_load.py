import sys
import os
import traceback

# ensure repo root is on sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

def main():
    try:
        import llmcore
        mk, changed = llmcore.reload_mykeys()
        print(f"[TEST] reload_mykeys changed={changed}, my_plugins={mk.get('my_plugins')}")
    except Exception as e:
        print('[TEST] reload_mykeys failed:', e)
        traceback.print_exc()

    # Try importing plugin directly via importlib if llmcore didn't load it
    try:
        import importlib.util
        ppath = os.path.join(repo_root, 'plugins', 'my_auto_route_plugin.py')
        if os.path.exists(ppath):
            spec = importlib.util.spec_from_file_location('my_auto_route_plugin', ppath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            print('[TEST] Direct import of plugins/my_auto_route_plugin.py succeeded')
        else:
            print(f'[TEST] plugin file not found at {ppath}')
    except Exception as e:
        print('[TEST] direct import failed:', e)
        traceback.print_exc()

    try:
        import agentmain
        AG = getattr(agentmain, 'GeneraticAgent', None)
        print(f"[TEST] GeneraticAgent in agentmain: {AG is not None}")
        a = agentmain.GeneraticAgent()
        # Check plugin patch flag on class
        patched = getattr(AG, '_myauto_patched', False)
        print(f"[TEST] GeneraticAgent._myauto_patched = {patched}")
        # Check instance attrs
        print(f"[TEST] instance has _myauto_inited = {getattr(a, '_myauto_inited', False)}")
        print(f"[TEST] instance has _myauto_last_route = {hasattr(a, '_myauto_last_route')}")
    except Exception as e:
        print('[TEST] agentmain/GeneraticAgent test failed:', e)
        traceback.print_exc()

if __name__ == '__main__':
    main()
