use crate::monitor::adapter::{ActivityAdapter, ActivityLevel, ProbeResult};
use crate::monitor::config::ProviderConfig;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use sysinfo::System;

const MIN_REFRESH_INTERVAL: Duration = Duration::from_secs(5);

pub struct SharedProcessScanner {
    system: System,
    last_refresh: Option<Instant>,
}

impl SharedProcessScanner {
    pub fn new() -> Self {
        Self {
            system: System::new(),
            last_refresh: None,
        }
    }

    pub fn refresh(&mut self) {
        let should_refresh = self
            .last_refresh
            .map(|t| t.elapsed() >= MIN_REFRESH_INTERVAL)
            .unwrap_or(true);
        if !should_refresh {
            return;
        }
        self.system
            .refresh_processes(sysinfo::ProcessesToUpdate::All, true);
        self.last_refresh = Some(Instant::now());
    }

    pub fn find_matching_cpu(&self, names: &[String], parent_exclude: &[String]) -> Option<f32> {
        let mut total_cpu: f32 = 0.0;
        let mut found = false;

        for process in self.system.processes().values() {
            let proc_name = process.name().to_string_lossy().to_lowercase();

            let matches = names
                .iter()
                .any(|n| proc_name == n.as_str() || proc_name.contains(n.as_str()));

            if !matches {
                continue;
            }

            if !parent_exclude.is_empty() {
                if let Some(parent_pid) = process.parent() {
                    if let Some(parent) = self.system.process(parent_pid) {
                        let parent_name = parent.name().to_string_lossy().to_lowercase();
                        if parent_exclude
                            .iter()
                            .any(|ex| parent_name.contains(ex.as_str()))
                        {
                            continue;
                        }
                    }
                }
            }

            found = true;
            total_cpu += process.cpu_usage();
        }

        if found {
            Some(total_cpu)
        } else {
            None
        }
    }
}

pub struct ProcessAdapter {
    provider_id: String,
    provider_name: String,
    process_names: Vec<String>,
    parent_exclude: Vec<String>,
    cpu_active_threshold: f32,
    scanner: Arc<Mutex<SharedProcessScanner>>,
    is_fallback: bool,
}

impl ProcessAdapter {
    pub fn from_config(
        config: &ProviderConfig,
        scanner: Arc<Mutex<SharedProcessScanner>>,
    ) -> Option<Self> {
        let names = if let Some(ref proc_cfg) = config.activity.process {
            proc_cfg.names.clone()
        } else if let Some(ref fb) = config.process_fallback {
            fb.names.clone()
        } else {
            return None;
        };

        let parent_exclude = config
            .process_fallback
            .as_ref()
            .and_then(|fb| fb.parent_exclude.clone())
            .unwrap_or_default();

        let cpu_threshold = config
            .activity
            .process
            .as_ref()
            .and_then(|p| p.cpu_active_threshold)
            .unwrap_or(5.0);

        Some(Self {
            provider_id: config.meta.id.clone(),
            provider_name: config.meta.name.clone(),
            process_names: names,
            parent_exclude,
            cpu_active_threshold: cpu_threshold,
            scanner,
            is_fallback: false,
        })
    }

    pub fn from_fallback(
        config: &ProviderConfig,
        scanner: Arc<Mutex<SharedProcessScanner>>,
    ) -> Option<Self> {
        let fb = config.process_fallback.as_ref()?;
        if !fb.enabled {
            return None;
        }

        Some(Self {
            provider_id: format!("{}-process", config.meta.id),
            provider_name: format!("{} (process)", config.meta.name),
            process_names: fb.names.clone(),
            parent_exclude: fb.parent_exclude.clone().unwrap_or_default(),
            cpu_active_threshold: fb.cpu_active_threshold.unwrap_or(20.0),
            scanner,
            is_fallback: true,
        })
    }
}

impl ActivityAdapter for ProcessAdapter {
    fn probe(&mut self) -> Option<ProbeResult> {
        let guard = self.scanner.lock().ok()?;
        let total_cpu = guard.find_matching_cpu(&self.process_names, &self.parent_exclude)?;
        drop(guard);

        let activity = if total_cpu > self.cpu_active_threshold * 2.0 {
            ActivityLevel::ActiveMedium
        } else if total_cpu > self.cpu_active_threshold {
            ActivityLevel::ActiveLow
        } else {
            ActivityLevel::Inactive
        };

        let last_active_ts = if activity >= ActivityLevel::ActiveLow {
            let now_ms = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64;
            Some(now_ms)
        } else {
            None
        };

        Some(ProbeResult {
            provider_id: self.provider_id.clone(),
            provider_name: self.provider_name.clone(),
            activity,
            last_active_ts,
            lines_added: None,
            files_changed: None,
            model_name: None,
            is_fallback: self.is_fallback,
        })
    }
}
