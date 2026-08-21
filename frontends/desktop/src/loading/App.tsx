import { useReducer, useEffect } from 'react';
import { reducer, initialState } from './store';
import { subscribe, unsubscribe } from './events';
import { LoadingScreen } from './Loading';
import { ProgressScreen } from './Progress';
import { ReadyScreen } from './Ready';
import { WindowsTitlebar } from '../components/layout/WindowsTitlebar';
import { isWindows } from '../platform';

export function LoadingApp() {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    void subscribe(dispatch).catch((error) => {
      console.error('[bootstrap] failed to subscribe to startup state', error);
    });
    return () => unsubscribe();
  }, []);

  let content: React.ReactNode;
  switch (state.route) {
    case 'loading':
      content = <LoadingScreen mode={state.mode} />;
      break;
    case 'progress':
      content = <ProgressScreen stages={state.stages} overallPct={state.overallPct} logs={state.logs} />;
      break;
    case 'ready':
      content = <ReadyScreen />;
      break;
  }

  return (
    <div className="bootstrap-shell">
      {isWindows && <WindowsTitlebar />}
      <div className="bootstrap-app" data-route={state.route}>
        {content}
      </div>
    </div>
  );
}
