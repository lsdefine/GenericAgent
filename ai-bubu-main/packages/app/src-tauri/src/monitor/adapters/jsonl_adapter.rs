use crate::monitor::adapter::{activity_from_elapsed, ActivityAdapter, ProbeResult};
use crate::monitor::config::ProviderConfig;
use std::fs;
use std::io::{Read as _, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub struct JsonlAdapter {
    provider_id: String,
    provider_name: String,
    base_dir: PathBuf,
    file_pattern: String,
    timestamp_field: String,
}

impl JsonlAdapter {
    pub fn from_config(config: &ProviderConfig, base_path: String) -> Option<Self> {
        let jsonl_cfg = config.activity.jsonl.as_ref()?;

        Some(Self {
            provider_id: config.meta.id.clone(),
            provider_name: config.meta.name.clone(),
            base_dir: PathBuf::from(base_path),
            file_pattern: jsonl_cfg.file_pattern.clone(),
            timestamp_field: jsonl_cfg.timestamp_field.clone(),
        })
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

impl ActivityAdapter for JsonlAdapter {
    fn probe(&mut self) -> Option<ProbeResult> {
        if !self.base_dir.exists() {
            return None;
        }

        let (path, mtime) = find_latest_jsonl(&self.base_dir, &self.file_pattern)?;

        let content_ts = read_last_line_timestamp(&path, &self.timestamp_field);

        let (elapsed_s, last_active_ts) = if let Some(ts_ms) = content_ts {
            let now = now_ms();
            let elapsed = now.saturating_sub(ts_ms) / 1000;
            (elapsed, ts_ms)
        } else {
            let now = SystemTime::now();
            let elapsed = now.duration_since(mtime).ok()?.as_secs();
            let now_ms_val = now
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis() as u64;
            (elapsed, now_ms_val - elapsed * 1000)
        };

        let activity = activity_from_elapsed(elapsed_s);

        Some(ProbeResult {
            provider_id: self.provider_id.clone(),
            provider_name: self.provider_name.clone(),
            activity,
            last_active_ts: Some(last_active_ts),
            lines_added: None,
            files_changed: None,
            model_name: None,
            is_fallback: false,
        })
    }
}

/// Read the tail of a JSONL file and extract the timestamp from the last
/// entry that contains the field. Scans backwards through lines because
/// some tools (e.g. Claude Code) append metadata entries without timestamps.
fn read_last_line_timestamp(path: &Path, ts_field: &str) -> Option<u64> {
    let mut file = fs::File::open(path).ok()?;
    let file_len = file.metadata().ok()?.len();
    if file_len == 0 {
        return None;
    }

    let tail_size = 8192u64.min(file_len);
    file.seek(SeekFrom::End(-(tail_size as i64))).ok()?;

    let mut buf = String::new();
    file.read_to_string(&mut buf).ok()?;

    for line in buf.lines().rev() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let obj: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if let Some(ts) = obj.get(ts_field) {
            return parse_timestamp_value(ts);
        }
    }
    None
}

fn parse_timestamp_value(val: &serde_json::Value) -> Option<u64> {
    if let Some(n) = val.as_u64() {
        return Some(n);
    }
    if let Some(n) = val.as_f64() {
        return Some(n as u64);
    }
    if let Some(s) = val.as_str() {
        if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(s) {
            return Some(dt.timestamp_millis() as u64);
        }
        return s.parse::<u64>().ok();
    }
    None
}

/// Find the most recently modified JSONL file matching the pattern.
/// Returns (path, mtime). The mtime is the OS file modification time —
/// no content parsing needed, no timezone concerns, works with any line size.
fn find_latest_jsonl(base: &Path, pattern: &str) -> Option<(PathBuf, SystemTime)> {
    let glob_pattern = format!("{}/**/{}", base.display(), pattern);

    glob::glob(&glob_pattern)
        .ok()?
        .flatten()
        .filter_map(|path| {
            let mtime = fs::metadata(&path).ok()?.modified().ok()?;
            Some((path, mtime))
        })
        .max_by_key(|(_, mtime)| *mtime)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::monitor::adapter::ActivityLevel;
    use std::time::Duration;
    use tempfile::TempDir;

    #[test]
    fn activity_from_elapsed_zones() {
        assert_eq!(activity_from_elapsed(0), ActivityLevel::ActiveHigh);
        assert_eq!(activity_from_elapsed(5), ActivityLevel::ActiveHigh);
        assert_eq!(activity_from_elapsed(10), ActivityLevel::ActiveHigh);
        assert_eq!(activity_from_elapsed(11), ActivityLevel::ActiveMedium);
        assert_eq!(activity_from_elapsed(30), ActivityLevel::ActiveMedium);
        assert_eq!(activity_from_elapsed(31), ActivityLevel::ActiveLow);
        assert_eq!(activity_from_elapsed(60), ActivityLevel::ActiveLow);
        assert_eq!(activity_from_elapsed(61), ActivityLevel::Inactive);
    }

    #[test]
    fn find_latest_jsonl_picks_newest_by_mtime() {
        let tmp = TempDir::new().unwrap();
        let f1 = tmp.path().join("old.jsonl");
        let f2 = tmp.path().join("new.jsonl");

        fs::write(&f1, r#"{"x":1}"#).unwrap();
        std::thread::sleep(Duration::from_millis(50));
        fs::write(&f2, r#"{"x":2}"#).unwrap();

        let (path, _) = find_latest_jsonl(&tmp.path().to_path_buf(), "*.jsonl").unwrap();
        assert_eq!(path, f2);
    }

    #[test]
    fn find_latest_jsonl_mtime_is_recent() {
        let tmp = TempDir::new().unwrap();
        let f = tmp.path().join("session.jsonl");
        fs::write(&f, "data").unwrap();

        let (_, mtime) = find_latest_jsonl(&tmp.path().to_path_buf(), "*.jsonl").unwrap();
        let elapsed = SystemTime::now().duration_since(mtime).unwrap();
        assert!(elapsed.as_secs() < 5, "mtime should be very recent");
    }

    #[test]
    fn find_latest_jsonl_none_for_empty_dir() {
        let tmp = TempDir::new().unwrap();
        let result = find_latest_jsonl(&tmp.path().to_path_buf(), "*.jsonl");
        assert!(result.is_none());
    }

    #[test]
    fn find_latest_jsonl_recursive() {
        let tmp = TempDir::new().unwrap();
        let sub = tmp.path().join("sub").join("agent");
        fs::create_dir_all(&sub).unwrap();

        let f_root = tmp.path().join("root.jsonl");
        fs::write(&f_root, "old").unwrap();
        std::thread::sleep(Duration::from_millis(50));

        let f_deep = sub.join("deep.jsonl");
        fs::write(&f_deep, "new").unwrap();

        let (path, _) = find_latest_jsonl(&tmp.path().to_path_buf(), "*.jsonl").unwrap();
        assert_eq!(path, f_deep);
    }

    #[test]
    fn find_latest_ignores_non_matching_files() {
        let tmp = TempDir::new().unwrap();
        fs::write(tmp.path().join("data.txt"), "not jsonl").unwrap();
        fs::write(tmp.path().join("session.jsonl"), "jsonl").unwrap();

        let (path, _) = find_latest_jsonl(&tmp.path().to_path_buf(), "*.jsonl").unwrap();
        assert!(path.extension().unwrap() == "jsonl");
    }

    #[test]
    fn mtime_works_with_large_files() {
        let tmp = TempDir::new().unwrap();
        let f = tmp.path().join("big.jsonl");
        let padding = "x".repeat(100_000);
        fs::write(&f, &padding).unwrap();

        let (path, mtime) = find_latest_jsonl(&tmp.path().to_path_buf(), "*.jsonl").unwrap();
        assert_eq!(path, f);
        let elapsed = SystemTime::now().duration_since(mtime).unwrap();
        assert!(elapsed.as_secs() < 5);
    }
}
