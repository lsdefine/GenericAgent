use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tauri::AppHandle;
use tauri_plugin_store::StoreExt;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StepRecord {
    pub date: String,
    pub steps: u64,
    pub peak_score: f64,
    pub active_minutes: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hourly_steps: Option<Vec<u64>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provider_minutes: Option<HashMap<String, u32>>,
}

static STORE_PATH: &str = "steps.json";

fn get_or_create_store(
    app: &AppHandle,
) -> Result<Arc<tauri_plugin_store::Store<tauri::Wry>>, String> {
    app.store(STORE_PATH).map_err(|e| e.to_string())
}

fn is_valid_date(date: &str) -> bool {
    if date.len() != 10 {
        return false;
    }
    let parts: Vec<&str> = date.split('-').collect();
    if parts.len() != 3 {
        return false;
    }
    if parts[0].len() != 4 || parts[1].len() != 2 || parts[2].len() != 2 {
        return false;
    }
    if !parts.iter().all(|p| p.chars().all(|c| c.is_ascii_digit())) {
        return false;
    }
    let year: u32 = match parts[0].parse() {
        Ok(v) => v,
        Err(_) => return false,
    };
    let month: u32 = match parts[1].parse() {
        Ok(v) => v,
        Err(_) => return false,
    };
    let day: u32 = match parts[2].parse() {
        Ok(v) => v,
        Err(_) => return false,
    };
    if !(1..=12).contains(&month) || day < 1 {
        return false;
    }
    let max_day = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if (year.is_multiple_of(4) && !year.is_multiple_of(100)) || year.is_multiple_of(400) {
                29
            } else {
                28
            }
        }
        _ => return false,
    };
    day <= max_day
}

#[tauri::command]
pub fn save_steps(
    app: AppHandle,
    date: String,
    steps: u64,
    peak_score: f64,
    active_minutes: u32,
    hourly_steps: Option<Vec<u64>>,
    provider_minutes: Option<HashMap<String, u32>>,
) -> Result<(), String> {
    if !is_valid_date(&date) {
        return Err("Invalid date format, expected YYYY-MM-DD".to_string());
    }

    let store = get_or_create_store(&app)?;

    let record = StepRecord {
        date: date.clone(),
        steps,
        peak_score,
        active_minutes,
        hourly_steps,
        provider_minutes,
    };

    store.set(
        &date,
        serde_json::to_value(&record).map_err(|e| e.to_string())?,
    );
    store.save().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn load_steps(app: AppHandle, date: String) -> Result<Option<StepRecord>, String> {
    if !is_valid_date(&date) {
        return Err("Invalid date format, expected YYYY-MM-DD".to_string());
    }

    let store = get_or_create_store(&app)?;

    match store.get(&date) {
        Some(val) => {
            let record: StepRecord =
                serde_json::from_value(val.clone()).map_err(|e| e.to_string())?;
            Ok(Some(record))
        }
        None => Ok(None),
    }
}

#[tauri::command]
pub fn load_step_history(app: AppHandle) -> Result<Vec<StepRecord>, String> {
    let store = get_or_create_store(&app)?;

    let mut records: Vec<StepRecord> = Vec::new();

    for (key, val) in store.entries() {
        match serde_json::from_value::<StepRecord>(val.clone()) {
            Ok(record) => {
                records.push(record);
            }
            Err(e) => eprintln!("steps: skipping corrupt entry '{}': {}", key, e),
        }
    }

    records.sort_by(|a, b| a.date.cmp(&b.date));

    if records.len() > 90 {
        let to_remove = records.len() - 90;
        let stale_dates: Vec<String> = records[..to_remove]
            .iter()
            .map(|r| r.date.clone())
            .collect();
        records = records[to_remove..].to_vec();

        for date in &stale_dates {
            store.delete(date);
        }
        if !stale_dates.is_empty() {
            let _ = store.save();
        }
    }

    Ok(records)
}
