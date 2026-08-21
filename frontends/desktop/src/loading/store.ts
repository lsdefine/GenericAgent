import type {
  BootstrapDiagnostics,
  BootstrapFailure,
  BootstrapMode,
  BootstrapPhase,
  BootstrapSnapshot,
} from './types';

export type Route = 'loading' | 'progress' | 'ready';

export type StageState = 'pending' | 'running' | 'done' | 'skipped' | 'failed';

export interface Stage {
  key: string;
  state: StageState;
  pct: number;
}

export interface BootstrapState {
  seq: number;
  route: Route;
  mode: BootstrapMode;
  phase: BootstrapPhase;
  stage: string | null;
  stages: Stage[];
  logs: string[];
  failure: BootstrapFailure | null;
  diagnostics: BootstrapDiagnostics;
  overallPct: number;
}

export type BootstrapAction = { type: 'snapshot'; snapshot: BootstrapSnapshot };

const KNOWN_STAGES = ['validate', 'python', 'dependencies', 'service', 'ui'];

const EMPTY_DIAGNOSTICS: BootstrapDiagnostics = {
  buildId: '',
  platform: '',
  projectDir: '',
  pythonPath: '',
  portState: 'unknown',
  bridgeIdentity: null,
  recentLogs: [],
};

export const initialState: BootstrapState = {
  seq: -1,
  route: 'loading',
  mode: 'cold_start',
  phase: 'idle',
  stage: null,
  stages: [],
  logs: [],
  failure: null,
  diagnostics: EMPTY_DIAGNOSTICS,
  overallPct: 0,
};

function routeFor(snapshot: BootstrapSnapshot): Route {
  if (snapshot.phase === 'ready') return 'ready';
  if (snapshot.mode === 'prepare' || snapshot.phase === 'preparing') return 'progress';
  return 'loading';
}

function stagesFor(snapshot: BootstrapSnapshot): Stage[] {
  if (snapshot.mode !== 'prepare' && snapshot.phase !== 'preparing') return [];

  const currentIndex = snapshot.stage ? KNOWN_STAGES.indexOf(snapshot.stage) : -1;
  return KNOWN_STAGES.map((key, index) => {
    let stageState: StageState = 'pending';
    if (snapshot.phase === 'failed' && key === snapshot.stage) stageState = 'failed';
    else if (snapshot.phase === 'ready' || currentIndex > index) stageState = 'done';
    else if (currentIndex === index) stageState = 'running';
    return { key, state: stageState, pct: snapshot.progress };
  });
}

export function reducer(state: BootstrapState, action: BootstrapAction): BootstrapState {
  if (action.type !== 'snapshot' || action.snapshot.seq <= state.seq) {
    return state;
  }

  const snapshot = action.snapshot;
  return {
    seq: snapshot.seq,
    route: routeFor(snapshot),
    mode: snapshot.mode,
    phase: snapshot.phase,
    stage: snapshot.stage,
    stages: stagesFor(snapshot),
    logs: snapshot.diagnostics.recentLogs,
    failure: snapshot.failure,
    diagnostics: snapshot.diagnostics,
    overallPct: snapshot.progress,
  };
}
