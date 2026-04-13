use crate::monitor::adapter::{activity_from_elapsed, ActivityAdapter, ProbeResult};
use crate::monitor::config::ProviderConfig;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

struct VariantInfo {
    id: String,
    name: String,
    tasks_dir: PathBuf,
}

pub struct VscodeExtAdapter {
    #[allow(dead_code)]
    provider_id: String,
    variants: Vec<VariantInfo>,
}

impl VscodeExtAdapter {
    pub fn from_config(config: &ProviderConfig) -> Option<Self> {
        let variants_cfg = config.variants.as_ref()?;
        let paths = config.detect.paths.as_ref()?;

        #[cfg(target_os = "macos")]
        let path_template = paths.get("macos")?;
        #[cfg(target_os = "linux")]
        let path_template = paths.get("linux")?;
        #[cfg(target_os = "windows")]
        let path_template = paths.get("windows")?;

        let home = dirs::home_dir()?;
        let home_str = home.to_string_lossy();

        #[cfg(target_os = "macos")]
        let app_support = format!("{}/Library/Application Support", home_str);
        #[cfg(target_os = "linux")]
        let app_support = format!("{}/.config", home_str);
        #[cfg(target_os = "windows")]
        let app_support =
            std::env::var("APPDATA").unwrap_or_else(|_| format!("{}\\AppData\\Roaming", home_str));

        let ide_names = ["Code", "Cursor", "Trae"];

        let mut variants = Vec::new();

        for variant in variants_cfg {
            for ide in &ide_names {
                let path = path_template
                    .replace("${APP_SUPPORT}", &app_support)
                    .replace("${HOME}", &home_str)
                    .replace("${IDE}", ide)
                    .replace("${EXT_ID}", &variant.extension_id);

                let dir = PathBuf::from(&path);
                if dir.exists() {
                    variants.push(VariantInfo {
                        id: format!("{}-{}", variant.id, ide.to_lowercase()),
                        name: format!("{} ({})", variant.name, ide),
                        tasks_dir: dir,
                    });
                }
            }
        }

        if variants.is_empty() {
            return None;
        }

        Some(Self {
            provider_id: config.meta.id.clone(),
            variants,
        })
    }
}

impl ActivityAdapter for VscodeExtAdapter {
    fn probe(&mut self) -> Option<ProbeResult> {
        let mut best_result: Option<ProbeResult> = None;

        for variant in &self.variants {
            if let Some(result) = probe_variant(variant) {
                if best_result
                    .as_ref()
                    .is_none_or(|prev| result.activity > prev.activity)
                {
                    best_result = Some(result);
                }
            }
        }

        best_result
    }
}

fn probe_variant(variant: &VariantInfo) -> Option<ProbeResult> {
    let mut latest_mtime: Option<SystemTime> = None;

    let entries = fs::read_dir(&variant.tasks_dir).ok()?;

    for entry in entries.flatten() {
        let task_dir = entry.path();
        if !task_dir.is_dir() {
            continue;
        }

        let history_file = task_dir.join("api_conversation_history.json");
        if let Ok(meta) = fs::metadata(&history_file) {
            if let Ok(mtime) = meta.modified() {
                if latest_mtime.is_none_or(|prev| mtime > prev) {
                    latest_mtime = Some(mtime);
                }
            }
        }
    }

    let mtime = latest_mtime?;
    let now = SystemTime::now();
    let elapsed_s = now.duration_since(mtime).ok()?.as_secs();

    let now_ms = now
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64;
    let last_ts = now_ms - elapsed_s * 1000;

    let activity = activity_from_elapsed(elapsed_s);

    Some(ProbeResult {
        provider_id: variant.id.clone(),
        provider_name: variant.name.clone(),
        activity,
        last_active_ts: Some(last_ts),
        lines_added: None,
        files_changed: None,
        model_name: None,
        is_fallback: false,
    })
}
