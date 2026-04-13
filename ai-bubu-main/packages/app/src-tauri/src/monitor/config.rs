use serde::Deserialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Deserialize)]
pub struct ProviderConfig {
    pub meta: MetaConfig,
    pub detect: DetectConfig,
    pub activity: ActivityConfig,
    pub process_fallback: Option<ProcessFallbackConfig>,
    pub variants: Option<Vec<VariantConfig>>,
}

#[derive(Debug, Deserialize)]
pub struct MetaConfig {
    pub id: String,
    pub name: String,
    #[allow(dead_code)]
    pub category: String,
    #[serde(default = "default_priority")]
    pub priority: u32,
}

fn default_priority() -> u32 {
    5
}

#[derive(Debug, Deserialize)]
pub struct DetectConfig {
    #[allow(dead_code)]
    pub adapter: String,
    pub paths: Option<HashMap<String, String>>,
}

#[derive(Debug, Deserialize)]
pub struct ActivityConfig {
    pub adapter: String,
    pub sqlite: Option<SqliteActivityConfig>,
    pub jsonl: Option<JsonlActivityConfig>,
    pub file_mtime: Option<FileMtimeConfig>,
    pub process: Option<ProcessActivityConfig>,
    pub status_map: Option<HashMap<String, String>>,
}

#[derive(Debug, Deserialize)]
pub struct SqliteActivityConfig {
    pub latest_query: String,
    pub timestamp_field: String,
    pub status_field: Option<String>,
    pub metrics_fields: Option<Vec<String>>,
}

#[derive(Debug, Deserialize)]
pub struct JsonlActivityConfig {
    pub file_pattern: String,
    pub timestamp_field: String,
}

#[derive(Debug, Deserialize)]
pub struct FileMtimeConfig {
    pub watch_pattern: String,
}

#[derive(Debug, Deserialize)]
pub struct ProcessActivityConfig {
    pub names: Vec<String>,
    pub cpu_active_threshold: Option<f32>,
}

#[derive(Debug, Deserialize)]
pub struct ProcessFallbackConfig {
    #[serde(default = "default_true")]
    pub enabled: bool,
    pub names: Vec<String>,
    pub parent_exclude: Option<Vec<String>>,
    pub cpu_active_threshold: Option<f32>,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Deserialize)]
pub struct VariantConfig {
    pub id: String,
    pub name: String,
    pub extension_id: String,
}

fn expand_path(template: &str) -> String {
    let home = dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("~"))
        .to_string_lossy()
        .to_string();

    #[cfg(target_os = "macos")]
    let app_support = format!("{}/Library/Application Support", home);
    #[cfg(target_os = "linux")]
    let app_support = format!("{}/.config", home);
    #[cfg(target_os = "windows")]
    let app_support =
        std::env::var("APPDATA").unwrap_or_else(|_| format!("{}\\AppData\\Roaming", home));

    template
        .replace("${HOME}", &home)
        .replace("${APP_SUPPORT}", &app_support)
        .replace("${APPDATA}", &std::env::var("APPDATA").unwrap_or_default())
}

pub fn resolve_path(config: &DetectConfig) -> Option<String> {
    let paths = config.paths.as_ref()?;

    #[cfg(target_os = "macos")]
    let key = "macos";
    #[cfg(target_os = "linux")]
    let key = "linux";
    #[cfg(target_os = "windows")]
    let key = "windows";

    paths.get(key).map(|p| expand_path(p))
}

pub fn load_providers(dir: &Path) -> Vec<ProviderConfig> {
    let mut providers = Vec::new();

    let pattern = dir.join("*.toml");
    let pattern_str = pattern.to_string_lossy().to_string();

    if let Ok(entries) = glob::glob(&pattern_str) {
        for entry in entries.flatten() {
            match std::fs::read_to_string(&entry) {
                Ok(content) => match toml::from_str::<ProviderConfig>(&content) {
                    Ok(config) => {
                        providers.push(config);
                    }
                    Err(e) => {
                        eprintln!("monitor: failed to parse {}: {}", entry.display(), e);
                    }
                },
                Err(e) => {
                    eprintln!("monitor: failed to read {}: {}", entry.display(), e);
                }
            }
        }
    }

    providers.sort_by(|a, b| b.meta.priority.cmp(&a.meta.priority));
    providers
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn expand_path_replaces_home() {
        let home = dirs::home_dir().unwrap().to_string_lossy().to_string();
        let result = expand_path("${HOME}/test");
        assert_eq!(result, format!("{}/test", home));
    }

    #[test]
    fn expand_path_replaces_app_support() {
        let result = expand_path("${APP_SUPPORT}/Cursor");
        assert!(!result.contains("${APP_SUPPORT}"));
        assert!(result.contains("Cursor"));
    }

    #[test]
    fn expand_path_no_placeholders() {
        let result = expand_path("/usr/local/bin");
        assert_eq!(result, "/usr/local/bin");
    }

    #[test]
    fn load_providers_from_dir() {
        let tmp = TempDir::new().unwrap();
        let toml_content = r#"
[meta]
id = "test-tool"
name = "Test Tool"
category = "ide"
priority = 8

[detect]
adapter = "sqlite"

[detect.paths]
macos = "${HOME}/.test/db.sqlite"

[activity]
adapter = "sqlite"

[activity.sqlite]
latest_query = "SELECT ts FROM data LIMIT 1"
timestamp_field = "ts"
"#;
        std::fs::write(tmp.path().join("test.toml"), toml_content).unwrap();

        let providers = load_providers(tmp.path());
        assert_eq!(providers.len(), 1);
        assert_eq!(providers[0].meta.id, "test-tool");
        assert_eq!(providers[0].meta.name, "Test Tool");
        assert_eq!(providers[0].meta.priority, 8);
        assert_eq!(providers[0].activity.adapter, "sqlite");
    }

    #[test]
    fn load_providers_skips_invalid_toml() {
        let tmp = TempDir::new().unwrap();
        std::fs::write(tmp.path().join("bad.toml"), "this is not valid toml {{{").unwrap();
        let providers = load_providers(tmp.path());
        assert!(providers.is_empty());
    }

    #[test]
    fn load_providers_empty_dir() {
        let tmp = TempDir::new().unwrap();
        let providers = load_providers(tmp.path());
        assert!(providers.is_empty());
    }

    #[test]
    fn load_providers_sorts_by_priority_desc() {
        let tmp = TempDir::new().unwrap();

        let make_toml = |id: &str, priority: u32| -> String {
            format!(
                r#"
[meta]
id = "{id}"
name = "{id}"
category = "ide"
priority = {priority}

[detect]
adapter = "process"

[activity]
adapter = "process"

[activity.process]
names = ["test"]
"#
            )
        };

        std::fs::write(tmp.path().join("low.toml"), make_toml("low", 1)).unwrap();
        std::fs::write(tmp.path().join("high.toml"), make_toml("high", 10)).unwrap();
        std::fs::write(tmp.path().join("mid.toml"), make_toml("mid", 5)).unwrap();

        let providers = load_providers(tmp.path());
        assert_eq!(providers.len(), 3);
        assert_eq!(providers[0].meta.id, "high");
        assert_eq!(providers[1].meta.id, "mid");
        assert_eq!(providers[2].meta.id, "low");
    }

    #[test]
    fn resolve_path_returns_expanded() {
        let detect = DetectConfig {
            adapter: "sqlite".to_string(),
            paths: Some({
                let mut m = std::collections::HashMap::new();
                #[cfg(target_os = "macos")]
                m.insert("macos".to_string(), "${HOME}/.config/test".to_string());
                #[cfg(target_os = "linux")]
                m.insert("linux".to_string(), "${HOME}/.config/test".to_string());
                #[cfg(target_os = "windows")]
                m.insert("windows".to_string(), "${HOME}\\.config\\test".to_string());
                m
            }),
        };

        let result = resolve_path(&detect);
        assert!(result.is_some());
        let path = result.unwrap();
        assert!(!path.contains("${HOME}"));
        assert!(path.contains(".config/test") || path.contains(".config\\test"));
    }

    #[test]
    fn resolve_path_none_without_paths() {
        let detect = DetectConfig {
            adapter: "sqlite".to_string(),
            paths: None,
        };
        assert!(resolve_path(&detect).is_none());
    }

    #[test]
    fn default_priority_is_5() {
        assert_eq!(default_priority(), 5);
    }
}
