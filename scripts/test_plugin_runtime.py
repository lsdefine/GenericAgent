import sys, os, time
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

def main():
    import agentmain
    AG = agentmain.GeneraticAgent
    print('[RUNTIME TEST] GeneraticAgent class patched flag:', getattr(AG, '_myauto_patched', False))
    a = agentmain.GeneraticAgent()
    print('[RUNTIME TEST] before put_task: _myauto_inited=', getattr(a, '_myauto_inited', False))
    dq = a.put_task('health-check: trigger plugin init', source='test')
    # allow any sync init to run
    time.sleep(0.2)
    print('[RUNTIME TEST] after put_task: _myauto_inited=', getattr(a, '_myauto_inited', False))
    print('[RUNTIME TEST] _myauto_patched on class:', getattr(AG, '_myauto_patched', False))
    print('[RUNTIME TEST] _myauto_last_route exists:', hasattr(a, '_myauto_last_route'))
    print('[RUNTIME TEST] _myauto_last_route:', getattr(a, '_myauto_last_route', None))

if __name__ == '__main__':
    main()
