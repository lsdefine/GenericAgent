export type BootstrapMode = 'hot_start' | 'cold_start' | 'prepare';

export type BootstrapPhase =
  | 'idle'
  | 'resolving'
  | 'preparing'
  | 'starting_service'
  | 'opening_ui'
  | 'ready'
  | 'failed';

export type BootstrapFailureCode =
  | 'config_unresolved'
  | 'prepare_failed'
  | 'spawn_failed'
  | 'port_conflict'
  | 'service_timeout'
  | 'service_exited'
  | 'ui_navigation_failed'
  | 'unknown';

export interface BootstrapFailure {
  code: BootstrapFailureCode;
  detail: string;
}

export interface BootstrapDiagnostics {
  buildId: string;
  platform: string;
  projectDir: string;
  pythonPath: string;
  portState: 'free' | 'owned' | 'foreign' | 'unknown';
  bridgeIdentity: string | null;
  recentLogs: string[];
}

export interface BootstrapSnapshot {
  seq: number;
  mode: BootstrapMode;
  phase: BootstrapPhase;
  stage: string | null;
  progress: number;
  failure: BootstrapFailure | null;
  diagnostics: BootstrapDiagnostics;
}
