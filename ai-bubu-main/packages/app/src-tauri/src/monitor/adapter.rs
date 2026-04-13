use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActivityLevel {
    Inactive = 0,
    ActiveLow = 1,
    ActiveMedium = 2,
    ActiveHigh = 3,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProbeResult {
    pub provider_id: String,
    pub provider_name: String,
    pub activity: ActivityLevel,
    pub last_active_ts: Option<u64>,
    pub lines_added: Option<u32>,
    pub files_changed: Option<u32>,
    pub model_name: Option<String>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub is_fallback: bool,
}

pub trait ActivityAdapter: Send + Sync {
    fn probe(&mut self) -> Option<ProbeResult>;
}

/// Shared activity-from-elapsed mapping used by all time-based adapters.
/// 60-second window: pet returns to idle within one minute of inactivity.
pub fn activity_from_elapsed(elapsed_s: u64) -> ActivityLevel {
    match elapsed_s {
        0..=10 => ActivityLevel::ActiveHigh,
        11..=30 => ActivityLevel::ActiveMedium,
        31..=60 => ActivityLevel::ActiveLow,
        _ => ActivityLevel::Inactive,
    }
}
