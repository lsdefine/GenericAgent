use crate::monitor::adapter::{activity_from_elapsed, ActivityAdapter, ProbeResult};
use crate::monitor::config::ProviderConfig;
use std::fs;
use std::path::PathBuf;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

const GLOB_TIMEOUT_SECS: u64 = 3;

pub struct FileMtimeAdapter {
    provider_id: String,
    provider_name: String,
    base_dir: PathBuf,
    watch_pattern: String,
}

impl FileMtimeAdapter {
    pub fn from_config(config: &ProviderConfig, base_path: String) -> Option<Self> {
        let mtime_cfg = config.activity.file_mtime.as_ref()?;

        Some(Self {
            provider_id: config.meta.id.clone(),
            provider_name: config.meta.name.clone(),
            base_dir: PathBuf::from(base_path),
            watch_pattern: mtime_cfg.watch_pattern.clone(),
        })
    }
}

impl ActivityAdapter for FileMtimeAdapter {
    fn probe(&mut self) -> Option<ProbeResult> {
        if !self.base_dir.exists() {
            return None;
        }

        let glob_pattern = format!("{}/{}", self.base_dir.display(), self.watch_pattern);

        let start = Instant::now();
        let mut latest_mtime: Option<SystemTime> = None;

        if let Ok(paths) = glob::glob(&glob_pattern) {
            for entry in paths.flatten() {
                if let Ok(meta) = fs::metadata(&entry) {
                    if let Ok(mtime) = meta.modified() {
                        if latest_mtime.is_none_or(|prev| mtime > prev) {
                            latest_mtime = Some(mtime);
                        }
                    }
                }
                if start.elapsed().as_secs() > GLOB_TIMEOUT_SECS {
                    eprintln!(
                        "monitor: file_mtime adapter '{}' glob timed out after {}s",
                        self.provider_id, GLOB_TIMEOUT_SECS
                    );
                    break;
                }
            }
        }

        let latest_mtime = latest_mtime?;

        let now = SystemTime::now();
        let elapsed_s = now.duration_since(latest_mtime).ok()?.as_secs();

        let now_ms = now
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64;
        let last_ts = now_ms - elapsed_s * 1000;

        let activity = activity_from_elapsed(elapsed_s);

        Some(ProbeResult {
            provider_id: self.provider_id.clone(),
            provider_name: self.provider_name.clone(),
            activity,
            last_active_ts: Some(last_ts),
            lines_added: None,
            files_changed: None,
            model_name: None,
            is_fallback: false,
        })
    }
}
