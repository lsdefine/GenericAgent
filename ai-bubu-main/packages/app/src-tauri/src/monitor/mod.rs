pub mod adapter;
pub mod adapters;
pub mod config;
pub mod scoring;

use adapter::{ActivityAdapter, ActivityLevel, ProbeResult};
use adapters::build_adapters;
use adapters::process_adapter::SharedProcessScanner;
use config::load_providers;
use scoring::MovementStateMachine;
use std::collections::HashSet;

use serde::Serialize;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};

const PROBE_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MonitorUpdate {
    pub providers: Vec<ProbeResult>,
    pub score: f32,
    pub movement: String,
    pub active_provider_count: usize,
    pub timestamp: u64,
}

pub struct MonitorEngine {
    adapters: Vec<Arc<Mutex<Box<dyn ActivityAdapter>>>>,
    cached_results: Mutex<Vec<Option<ProbeResult>>>,
    process_scanner: Arc<Mutex<SharedProcessScanner>>,
    state_machine: Mutex<MovementStateMachine>,
}

impl MonitorEngine {
    pub fn new(providers_dir: PathBuf) -> Self {
        let configs = load_providers(&providers_dir);
        let process_scanner = Arc::new(Mutex::new(SharedProcessScanner::new()));

        let mut adapters: Vec<Arc<Mutex<Box<dyn ActivityAdapter>>>> = Vec::new();

        for config in &configs {
            let built = build_adapters(config, &process_scanner);
            if built.is_empty() {
                eprintln!(
                    "monitor: skipped provider '{}' (not found on this system)",
                    config.meta.name
                );
            } else {
                eprintln!(
                    "monitor: loaded provider '{}' ({} adapter(s))",
                    config.meta.name,
                    built.len()
                );
                for adapter in built {
                    adapters.push(Arc::new(Mutex::new(adapter)));
                }
            }
        }

        eprintln!("monitor: {} adapters active", adapters.len());

        let cached_results = Mutex::new(vec![None; adapters.len()]);

        Self {
            adapters,
            cached_results,
            process_scanner,
            state_machine: Mutex::new(MovementStateMachine::new()),
        }
    }

    pub fn scan(&self) -> MonitorUpdate {
        if let Ok(mut scanner) = self.process_scanner.lock() {
            scanner.refresh();
        }

        let adapter_count = self.adapters.len();

        thread::scope(|s| {
            let (tx, rx) = mpsc::channel();

            for (i, adapter) in self.adapters.iter().enumerate() {
                let tx = tx.clone();
                s.spawn(move || {
                    let result = match adapter.try_lock() {
                        Ok(mut a) => a.probe(),
                        Err(_) => None,
                    };
                    let _ = tx.send((i, result));
                });
            }
            drop(tx);

            let deadline = Instant::now() + PROBE_TIMEOUT;
            let mut received = 0usize;
            {
                let mut cache = match self.cached_results.lock() {
                    Ok(c) => c,
                    Err(e) => e.into_inner(),
                };

                loop {
                    let remaining = deadline.saturating_duration_since(Instant::now());
                    if remaining.is_zero() || received == adapter_count {
                        break;
                    }
                    match rx.recv_timeout(remaining) {
                        Ok((i, result)) => {
                            if result.is_some() {
                                cache[i] = result;
                            }
                            received += 1;
                        }
                        Err(RecvTimeoutError::Timeout) => {
                            eprintln!(
                                "monitor: scan timeout — {}/{} adapters responded",
                                received, adapter_count
                            );
                            break;
                        }
                        Err(RecvTimeoutError::Disconnected) => break,
                    }
                }
            }
        });

        let results: Vec<ProbeResult> = {
            let cache = match self.cached_results.lock() {
                Ok(c) => c,
                Err(e) => e.into_inner(),
            };
            let all: Vec<ProbeResult> = cache.iter().filter_map(|r| r.clone()).collect();

            let active_primary_ids: HashSet<String> = all
                .iter()
                .filter(|r| !r.is_fallback && r.activity >= ActivityLevel::ActiveMedium)
                .map(|r| r.provider_id.clone())
                .collect();

            all.into_iter()
                .filter(|r| {
                    if !r.is_fallback {
                        return true;
                    }
                    let base_id = r
                        .provider_id
                        .strip_suffix("-process")
                        .unwrap_or(&r.provider_id);
                    !active_primary_ids.contains(base_id)
                })
                .collect()
        };

        let scored = {
            let mut sm = match self.state_machine.lock() {
                Ok(s) => s,
                Err(e) => e.into_inner(),
            };
            sm.update(&results)
        };

        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64;

        // --- detailed scan log ---
        let active_names: Vec<String> = results
            .iter()
            .filter(|r| r.activity >= ActivityLevel::ActiveLow)
            .map(|r| {
                format!(
                    "{}({:?}{})",
                    r.provider_name,
                    r.activity,
                    if r.is_fallback { ",fb" } else { "" }
                )
            })
            .collect();

        let cooldown_tag = if scored.in_cooldown {
            " (cooldown)"
        } else {
            ""
        };
        if active_names.is_empty() {
            eprintln!(
                "monitor: scan — no active tools → {}  score={:.0}",
                scored.movement.as_str(),
                scored.score
            );
        } else {
            eprintln!(
                "monitor: scan — active=[{}] → {}{}  score={:.0}  tools={}",
                active_names.join(", "),
                scored.movement.as_str(),
                cooldown_tag,
                scored.score,
                scored.active_tool_count
            );
        }

        MonitorUpdate {
            providers: results,
            score: scored.score,
            movement: scored.movement.as_str().to_string(),
            active_provider_count: scored.active_tool_count,
            timestamp,
        }
    }
}

pub struct MonitorRunner {
    stop_flag: Arc<AtomicBool>,
    handle: Option<JoinHandle<()>>,
}

impl MonitorRunner {
    pub fn stop(&mut self) {
        self.stop_flag.store(true, Ordering::Relaxed);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

impl Drop for MonitorRunner {
    fn drop(&mut self) {
        self.stop();
    }
}

pub fn start_monitor(
    app_handle: AppHandle,
    engine: Arc<MonitorEngine>,
    interval_ms: u64,
) -> MonitorRunner {
    let stop_flag = Arc::new(AtomicBool::new(false));
    let flag_clone = stop_flag.clone();

    let handle = thread::spawn(move || {
        let interval = Duration::from_millis(interval_ms);
        while !flag_clone.load(Ordering::Relaxed) {
            let update = engine.scan();
            let _ = app_handle.emit("monitor-update", &update);
            thread::sleep(interval);
        }
    });

    MonitorRunner {
        stop_flag,
        handle: Some(handle),
    }
}
