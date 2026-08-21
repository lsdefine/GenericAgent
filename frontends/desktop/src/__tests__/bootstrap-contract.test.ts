import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { initialState, reducer } from '../loading/store';
import { subscribe, unsubscribe } from '../loading/events';
import type { BootstrapFailureCode, BootstrapPhase, BootstrapSnapshot } from '../loading/types';

const desktopRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

function snapshot(
  seq: number,
  phase: BootstrapPhase,
  failure: BootstrapSnapshot['failure'] = null,
): BootstrapSnapshot {
  return {
    seq,
    mode: 'cold_start',
    phase,
    stage: phase === 'preparing' ? 'dependencies' : null,
    progress: phase === 'preparing' ? 45 : 0,
    failure,
    diagnostics: {
      buildId: 'abc-123',
      platform: 'windows',
      projectDir: 'C:\\GenericAgent',
      pythonPath: 'C:\\GenericAgent\\runtime\\python\\python.exe',
      portState: 'free',
      bridgeIdentity: null,
      recentLogs: [],
    },
  };
}

describe('bootstrap snapshot contract', () => {
  afterEach(() => {
    unsubscribe();
    delete (window as any).__TAURI__;
  });

  it('applies a newer snapshot as the complete loading state', () => {
    const next = reducer(initialState, { type: 'snapshot', snapshot: snapshot(2, 'preparing') } as any);

    expect((next as any).seq).toBe(2);
    expect((next as any).phase).toBe('preparing');
    expect((next as any).route).toBe('progress');
    expect((next as any).overallPct).toBe(45);
  });

  it('ignores a stale snapshot that arrives after a newer event', () => {
    const current = reducer(initialState, { type: 'snapshot', snapshot: snapshot(5, 'ready') } as any);
    const stale = reducer(current, {
      type: 'snapshot',
      snapshot: snapshot(4, 'failed', { code: 'service_timeout', detail: 'late' }),
    } as any);

    expect(stale).toBe(current);
    expect((stale as any).phase).toBe('ready');
  });

  it.each<[BootstrapPhase, string]>([
    ['idle', 'loading'],
    ['resolving', 'loading'],
    ['preparing', 'progress'],
    ['starting_service', 'loading'],
    ['opening_ui', 'loading'],
    ['ready', 'ready'],
    ['failed', 'loading'],
  ])('derives the loading route for the %s phase', (phase, route) => {
    const modeSnapshot = snapshot(1, phase);
    if (phase === 'preparing') modeSnapshot.mode = 'prepare';
    expect(reducer(initialState, { type: 'snapshot', snapshot: modeSnapshot }).route).toBe(route);
  });

  it.each<BootstrapFailureCode>([
    'config_unresolved',
    'prepare_failed',
    'spawn_failed',
    'port_conflict',
    'service_timeout',
    'service_exited',
    'ui_navigation_failed',
    'unknown',
  ])('preserves the %s failure code from Rust', (code) => {
    const failed = snapshot(1, 'failed', { code, detail: 'diagnostic detail' });
    expect(reducer(initialState, { type: 'snapshot', snapshot: failed }).failure).toEqual({
      code,
      detail: 'diagnostic detail',
    });
  });

  it('subscribes before requesting the current snapshot', async () => {
    const calls: string[] = [];
    const current = snapshot(3, 'starting_service');
    const dispatch = vi.fn();
    (window as any).__TAURI__ = {
      event: {
        listen: vi.fn(async () => {
          calls.push('listen');
          return () => {};
        }),
      },
      core: {
        invoke: vi.fn(async (command: string) => {
          calls.push(command);
          return current;
        }),
      },
    };

    await subscribe(dispatch);

    expect(calls).toEqual(['listen', 'get_bootstrap_snapshot']);
    expect(dispatch).toHaveBeenCalledWith({ type: 'snapshot', snapshot: current });
  });

  it('cancels an in-flight subscription during StrictMode effect cleanup', async () => {
    const stop = vi.fn();
    let resolveListen: ((stop: () => void) => void) | undefined;
    const invoke = vi.fn(async () => snapshot(1, 'idle'));
    (window as any).__TAURI__ = {
      event: {
        listen: vi.fn(() => new Promise<() => void>((resolve) => {
          resolveListen = resolve;
        })),
      },
      core: { invoke },
    };

    const pending = subscribe(vi.fn());
    unsubscribe();
    resolveListen?.(stop);
    await pending;

    expect(stop).toHaveBeenCalledOnce();
    expect(invoke).not.toHaveBeenCalled();
  });

  it('keeps the React v2 recovery page aligned with the bootstrap command contract', () => {
    const publicFallback = fs.readFileSync(path.join(desktopRoot, 'public/fallback.html'), 'utf8');

    expect(publicFallback).toContain("invoke('get_bootstrap_snapshot')");
    expect(publicFallback).toContain("invoke('retry_bootstrap'");
    expect(publicFallback).toContain('修复启动问题');
    expect(publicFallback).toContain('诊断信息');
    expect(publicFallback).toContain('复制诊断信息');
    expect(publicFallback).not.toContain("invoke('get_prepare_error')");
  });

  it('treats upstream static v1 as an independent non-empty source boundary', () => {
    const staticFallback = fs.readFileSync(path.join(desktopRoot, 'static/fallback.html'), 'utf8');
    expect(staticFallback.trim().length).toBeGreaterThan(0);
  });
});
