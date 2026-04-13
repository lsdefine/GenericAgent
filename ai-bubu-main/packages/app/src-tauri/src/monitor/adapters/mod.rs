pub mod file_mtime_adapter;
pub mod jsonl_adapter;
pub mod process_adapter;
pub mod sqlite_adapter;
pub mod vscode_ext_adapter;

use crate::monitor::adapter::ActivityAdapter;
use crate::monitor::config::{resolve_path, ProviderConfig};

use file_mtime_adapter::FileMtimeAdapter;
use jsonl_adapter::JsonlAdapter;
use process_adapter::{ProcessAdapter, SharedProcessScanner};
use sqlite_adapter::SqliteAdapter;
use vscode_ext_adapter::VscodeExtAdapter;

use std::sync::{Arc, Mutex};

pub fn build_adapters(
    config: &ProviderConfig,
    scanner: &Arc<Mutex<SharedProcessScanner>>,
) -> Vec<Box<dyn ActivityAdapter>> {
    let mut result: Vec<Box<dyn ActivityAdapter>> = Vec::new();

    let primary: Option<Box<dyn ActivityAdapter>> = match config.activity.adapter.as_str() {
        "sqlite" => resolve_path(&config.detect).and_then(|path| {
            SqliteAdapter::from_config(config, path)
                .map(|a| Box::new(a) as Box<dyn ActivityAdapter>)
        }),
        "jsonl" => resolve_path(&config.detect).and_then(|path| {
            JsonlAdapter::from_config(config, path).map(|a| Box::new(a) as Box<dyn ActivityAdapter>)
        }),
        "process" => ProcessAdapter::from_config(config, scanner.clone())
            .map(|a| Box::new(a) as Box<dyn ActivityAdapter>),
        "vscode_ext" => {
            VscodeExtAdapter::from_config(config).map(|a| Box::new(a) as Box<dyn ActivityAdapter>)
        }
        "file_mtime" => resolve_path(&config.detect).and_then(|path| {
            FileMtimeAdapter::from_config(config, path)
                .map(|a| Box::new(a) as Box<dyn ActivityAdapter>)
        }),
        _ => {
            eprintln!("monitor: unknown adapter type: {}", config.activity.adapter);
            None
        }
    };

    if let Some(adapter) = primary {
        result.push(adapter);
    }

    if let Some(fallback) = ProcessAdapter::from_fallback(config, scanner.clone()) {
        result.push(Box::new(fallback));
    }

    result
}
