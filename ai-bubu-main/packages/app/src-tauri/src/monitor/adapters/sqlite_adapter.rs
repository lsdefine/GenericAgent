use crate::monitor::adapter::{activity_from_elapsed, ActivityAdapter, ActivityLevel, ProbeResult};
use crate::monitor::config::ProviderConfig;
use rusqlite::{Connection, OpenFlags};
use std::path::PathBuf;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const CACHE_TTL: Duration = Duration::from_secs(5);

type QueryRow = (Option<u64>, Option<String>, Option<u32>, Option<u32>);

pub struct SqliteAdapter {
    provider_id: String,
    provider_name: String,
    db_path: PathBuf,
    query: String,
    timestamp_field: String,
    status_field: Option<String>,
    metrics_fields: Vec<String>,
    status_map: Vec<(String, ActivityLevel)>,
    cached_row: Option<QueryRow>,
    cache_time: Option<Instant>,
}

impl SqliteAdapter {
    pub fn from_config(config: &ProviderConfig, db_path: String) -> Option<Self> {
        let sqlite_cfg = config.activity.sqlite.as_ref()?;

        let status_map = parse_status_map(config.activity.status_map.as_ref());

        Some(Self {
            provider_id: config.meta.id.clone(),
            provider_name: config.meta.name.clone(),
            db_path: PathBuf::from(db_path),
            query: sqlite_cfg.latest_query.clone(),
            timestamp_field: sqlite_cfg.timestamp_field.clone(),
            status_field: sqlite_cfg.status_field.clone(),
            metrics_fields: sqlite_cfg.metrics_fields.clone().unwrap_or_default(),
            status_map,
            cached_row: None,
            cache_time: None,
        })
    }
}

impl ActivityAdapter for SqliteAdapter {
    fn probe(&mut self) -> Option<ProbeResult> {
        if !self.db_path.exists() {
            return None;
        }

        let cache_fresh = self
            .cache_time
            .map(|t| t.elapsed() < CACHE_TTL)
            .unwrap_or(false);

        if !cache_fresh {
            let query_result = try_sqlite_query(
                &self.db_path,
                &self.query,
                &self.timestamp_field,
                &self.status_field,
                &self.metrics_fields,
            );
            if let Some(row) = query_result {
                self.cached_row = Some(row);
                self.cache_time = Some(Instant::now());
            }
        }

        let (ts, ref status, lines_added, files_changed) =
            self.cached_row.clone().unwrap_or((None, None, None, None));

        let activity = determine_activity(ts, status.as_deref(), &self.status_map);

        Some(ProbeResult {
            provider_id: self.provider_id.clone(),
            provider_name: self.provider_name.clone(),
            activity,
            last_active_ts: ts,
            lines_added,
            files_changed,
            model_name: None,
            is_fallback: false,
        })
    }
}

/// Run the SQLite query with a hard 2-second timeout via a worker thread.
/// The worker thread is always joined to prevent thread leaks.
fn try_sqlite_query(
    db_path: &PathBuf,
    query: &str,
    timestamp_field: &str,
    status_field: &Option<String>,
    metrics_fields: &[String],
) -> Option<QueryRow> {
    use std::sync::mpsc;
    use std::thread;

    let db = db_path.clone();
    let q = query.to_string();
    let ts_field = timestamp_field.to_string();
    let st_field = status_field.clone();
    let mf = metrics_fields.to_vec();

    let (tx, rx) = mpsc::channel();

    let handle = thread::spawn(move || {
        let flags = OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX;
        let result = (|| {
            let conn = Connection::open_with_flags(&db, flags).ok()?;
            conn.busy_timeout(Duration::from_millis(200)).ok();
            conn.pragma_update(None, "query_only", "ON").ok();

            let mut stmt = conn.prepare(&q).ok()?;
            let column_names: Vec<String> =
                stmt.column_names().iter().map(|s| s.to_string()).collect();

            stmt.query_row([], |row| {
                let mut ts: Option<u64> = None;
                let mut status: Option<String> = None;
                let mut lines_added: Option<u32> = None;
                let mut files_changed: Option<u32> = None;

                for (i, col) in column_names.iter().enumerate() {
                    if *col == ts_field {
                        ts = row.get::<_, i64>(i).ok().map(|v| v as u64);
                    }
                    if st_field.as_deref() == Some(col.as_str()) {
                        status = row.get::<_, String>(i).ok();
                    }
                    if mf.contains(col) {
                        if col == "lines_added" {
                            lines_added = row.get::<_, u32>(i).ok();
                        }
                        if col == "files_changed" {
                            files_changed = row.get::<_, u32>(i).ok();
                        }
                    }
                }
                Ok((ts, status, lines_added, files_changed))
            })
            .ok()
        })();
        let _ = tx.send(result);
    });

    let result = match rx.recv_timeout(Duration::from_secs(2)) {
        Ok(result) => result,
        Err(_) => {
            eprintln!("monitor: sqlite query timed out for {:?}", db_path);
            None
        }
    };

    // Always join the worker thread to prevent leaks.
    // Even after timeout, the worker finishes once busy_timeout expires.
    let _ = handle.join();
    result
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn elapsed_seconds(ts_ms: u64, current_ms: u64) -> u64 {
    current_ms.saturating_sub(ts_ms) / 1000
}

const STUCK_STATUS_TIMEOUT_S: u64 = 300;

/// Combines status and recency to determine activity level.
///
/// Only statuses mapped to `ActiveHigh` (e.g. "generating") override recency,
/// and only if the timestamp is within the staleness window. A "generating"
/// session that hasn't updated in 5 minutes is treated as stuck/abandoned.
pub fn determine_activity(
    ts: Option<u64>,
    status: Option<&str>,
    status_map: &[(String, ActivityLevel)],
) -> ActivityLevel {
    if let Some(status_str) = status {
        for (pattern, level) in status_map {
            if status_str == pattern && *level == ActivityLevel::ActiveHigh {
                let stale = ts
                    .map(|t| elapsed_seconds(t, now_ms()) > STUCK_STATUS_TIMEOUT_S)
                    .unwrap_or(true);
                if !stale {
                    return ActivityLevel::ActiveHigh;
                }
            }
        }
    }

    let Some(ts_ms) = ts else {
        return ActivityLevel::Inactive;
    };

    activity_from_elapsed(elapsed_seconds(ts_ms, now_ms()))
}

fn parse_status_map(
    map: Option<&std::collections::HashMap<String, String>>,
) -> Vec<(String, ActivityLevel)> {
    let Some(map) = map else {
        return Vec::new();
    };

    map.iter()
        .filter_map(|(k, v)| {
            let level = match v.as_str() {
                "active_high" => ActivityLevel::ActiveHigh,
                "active_medium" => ActivityLevel::ActiveMedium,
                "active_low" => ActivityLevel::ActiveLow,
                "inactive" => ActivityLevel::Inactive,
                _ => return None,
            };
            Some((k.clone(), level))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

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
        assert_eq!(activity_from_elapsed(9999), ActivityLevel::Inactive);
    }

    #[test]
    fn elapsed_seconds_basic() {
        assert_eq!(elapsed_seconds(1000, 6000), 5);
        assert_eq!(elapsed_seconds(5000, 5000), 0);
        assert_eq!(elapsed_seconds(10000, 5000), 0);
    }

    #[test]
    fn determine_activity_generating_with_fresh_ts() {
        let map = vec![("generating".to_string(), ActivityLevel::ActiveHigh)];
        let recent_ts = now_ms() - 5_000;
        let result = determine_activity(Some(recent_ts), Some("generating"), &map);
        assert_eq!(result, ActivityLevel::ActiveHigh);
    }

    #[test]
    fn determine_activity_generating_no_ts_treated_as_stale() {
        let map = vec![("generating".to_string(), ActivityLevel::ActiveHigh)];
        let result = determine_activity(None, Some("generating"), &map);
        assert_eq!(result, ActivityLevel::Inactive);
    }

    #[test]
    fn determine_activity_generating_stale_ts_treated_as_stuck() {
        let map = vec![("generating".to_string(), ActivityLevel::ActiveHigh)];
        let stale_ts = now_ms() - 600_000;
        let result = determine_activity(Some(stale_ts), Some("generating"), &map);
        assert_eq!(result, ActivityLevel::Inactive);
    }

    #[test]
    fn determine_activity_completed_uses_recency() {
        let map = vec![("generating".to_string(), ActivityLevel::ActiveHigh)];
        let recent_ts = now_ms() - 5000;
        let result = determine_activity(Some(recent_ts), Some("completed"), &map);
        assert!(result >= ActivityLevel::ActiveMedium);
    }

    #[test]
    fn determine_activity_aborted_uses_recency() {
        let map = vec![("generating".to_string(), ActivityLevel::ActiveHigh)];
        let recent_ts = now_ms() - 3000;
        let result = determine_activity(Some(recent_ts), Some("aborted"), &map);
        assert!(result >= ActivityLevel::ActiveMedium);
    }

    #[test]
    fn determine_activity_stale_aborted_is_inactive() {
        let map = vec![("generating".to_string(), ActivityLevel::ActiveHigh)];
        let stale_ts = now_ms() - 600_000;
        let result = determine_activity(Some(stale_ts), Some("aborted"), &map);
        assert_eq!(result, ActivityLevel::Inactive);
    }

    #[test]
    fn determine_activity_no_status_uses_timestamp() {
        let recent_ts = now_ms() - 2000;
        let result = determine_activity(Some(recent_ts), None, &[]);
        assert_eq!(result, ActivityLevel::ActiveHigh);
    }

    #[test]
    fn determine_activity_no_ts_no_status() {
        let result = determine_activity(None, None, &[]);
        assert_eq!(result, ActivityLevel::Inactive);
    }

    #[test]
    fn determine_activity_no_ts_non_high_status() {
        let map = vec![("completed".to_string(), ActivityLevel::ActiveLow)];
        let result = determine_activity(None, Some("completed"), &map);
        assert_eq!(result, ActivityLevel::Inactive);
    }

    #[test]
    fn parse_status_map_valid() {
        let mut m = HashMap::new();
        m.insert("generating".to_string(), "active_high".to_string());
        m.insert("streaming".to_string(), "active_high".to_string());
        m.insert("idle".to_string(), "inactive".to_string());

        let result = parse_status_map(Some(&m));
        assert_eq!(result.len(), 3);

        let gen = result.iter().find(|(k, _)| k == "generating").unwrap();
        assert_eq!(gen.1, ActivityLevel::ActiveHigh);

        let idle = result.iter().find(|(k, _)| k == "idle").unwrap();
        assert_eq!(idle.1, ActivityLevel::Inactive);
    }

    #[test]
    fn parse_status_map_none() {
        let result = parse_status_map(None);
        assert!(result.is_empty());
    }

    #[test]
    fn parse_status_map_ignores_unknown_values() {
        let mut m = HashMap::new();
        m.insert("foo".to_string(), "bogus_level".to_string());
        m.insert("bar".to_string(), "active_medium".to_string());
        let result = parse_status_map(Some(&m));
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].0, "bar");
    }

    #[test]
    fn stale_query_ts_is_inactive() {
        let map = vec![("generating".to_string(), ActivityLevel::ActiveHigh)];
        let stale_query_ts = now_ms() - 600_000;
        let result = determine_activity(Some(stale_query_ts), Some("aborted"), &map);
        assert_eq!(result, ActivityLevel::Inactive);
    }
}
