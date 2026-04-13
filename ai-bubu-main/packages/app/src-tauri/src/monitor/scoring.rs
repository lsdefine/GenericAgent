use crate::monitor::adapter::{ActivityLevel, ProbeResult};
use std::collections::HashSet;
use std::time::{Duration, Instant};

const RUN_THRESHOLD_S: u64 = 60;
const SPRINT_THRESHOLD_S: u64 = 180;

/// After real activity is detected, keep the pet active for this long even
/// if signals temporarily drop (e.g. between agent tool calls).
const ACTIVITY_COOLDOWN: Duration = Duration::from_secs(45);

#[derive(Debug, Clone, Copy)]
pub struct ScoredOutput {
    pub score: f32,
    pub movement: Movement,
    pub active_tool_count: usize,
    /// True when the pet stays active due to cooldown bridging between
    /// intermittent bursts of real activity (e.g. agent tool-call gaps).
    pub in_cooldown: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Movement {
    Sprint,
    Run,
    Walk,
    Idle,
}

impl Movement {
    pub fn as_str(&self) -> &'static str {
        match self {
            Movement::Sprint => "sprint",
            Movement::Run => "run",
            Movement::Walk => "walk",
            Movement::Idle => "idle",
        }
    }
}

/// Determines whether a probe result counts as "real" AI activity.
/// Both primary and fallback adapters require at least ActiveMedium so
/// that the tail-end decay (ActiveLow, 31-60s after last interaction)
/// no longer keeps the state machine timer running.
fn is_real_activity(r: &ProbeResult) -> bool {
    r.activity >= ActivityLevel::ActiveMedium
}

/// Count unique active tools, deduplicating fallback adapters by base provider ID.
/// e.g. "cursor" (primary) + "cursor-process" (fallback) = 1 tool, not 2.
fn count_unique_active_tools(results: &[ProbeResult]) -> usize {
    let mut seen = HashSet::new();
    for r in results {
        if !is_real_activity(r) {
            continue;
        }
        let base_id = r
            .provider_id
            .strip_suffix("-process")
            .unwrap_or(&r.provider_id);
        seen.insert(base_id.to_string());
    }
    seen.len()
}

/// Returns true if any adapter reports at least `ActiveLow`, indicating
/// that an AI tool process is present even if not intensely active.
fn has_any_presence(results: &[ProbeResult]) -> bool {
    results
        .iter()
        .any(|r| r.activity >= ActivityLevel::ActiveLow)
}

pub struct MovementStateMachine {
    active_since: Option<Instant>,
    /// Last time we saw real (≥ ActiveMedium) activity.
    last_real_activity: Option<Instant>,
}

impl MovementStateMachine {
    pub fn new() -> Self {
        Self {
            active_since: None,
            last_real_activity: None,
        }
    }

    pub fn update(&mut self, results: &[ProbeResult]) -> ScoredOutput {
        let active_tool_count = count_unique_active_tools(results);
        let has_activity = active_tool_count > 0;
        let presence = has_any_presence(results);

        if has_activity {
            self.last_real_activity = Some(Instant::now());
        }

        let in_cooldown = !has_activity
            && presence
            && self
                .last_real_activity
                .map(|t| t.elapsed() < ACTIVITY_COOLDOWN)
                .unwrap_or(false);

        if !has_activity && !in_cooldown {
            if !presence {
                self.last_real_activity = None;
            }
            self.active_since = None;
            return ScoredOutput {
                score: 0.0,
                movement: Movement::Idle,
                active_tool_count: 0,
                in_cooldown: false,
            };
        }

        let now = Instant::now();
        let since = *self.active_since.get_or_insert(now);

        let raw_duration_s = now.duration_since(since).as_secs();

        let effective_tool_count = if in_cooldown { 1 } else { active_tool_count };

        let speed_multiplier: f64 = if effective_tool_count >= 3 {
            2.5
        } else if effective_tool_count >= 2 {
            1.8
        } else {
            1.0
        };
        let effective_s = (raw_duration_s as f64 * speed_multiplier) as u64;

        let (movement, score) = if effective_s >= SPRINT_THRESHOLD_S {
            let extra = (effective_s - SPRINT_THRESHOLD_S).min(120) as f32;
            (Movement::Sprint, 75.0 + (extra / 120.0) * 25.0)
        } else if effective_s >= RUN_THRESHOLD_S {
            let progress = (effective_s - RUN_THRESHOLD_S) as f32
                / (SPRINT_THRESHOLD_S - RUN_THRESHOLD_S) as f32;
            (Movement::Run, 50.0 + progress * 24.0)
        } else {
            let progress = effective_s as f32 / RUN_THRESHOLD_S as f32;
            (Movement::Walk, 25.0 + progress * 24.0)
        };

        ScoredOutput {
            score: score.min(100.0),
            movement,
            active_tool_count: effective_tool_count,
            in_cooldown,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_result(activity: ActivityLevel, fallback: bool) -> ProbeResult {
        make_result_with_id("test", activity, fallback)
    }

    fn make_result_with_id(id: &str, activity: ActivityLevel, fallback: bool) -> ProbeResult {
        ProbeResult {
            provider_id: id.into(),
            provider_name: id.into(),
            activity,
            last_active_ts: Some(0),
            lines_added: None,
            files_changed: None,
            model_name: None,
            is_fallback: fallback,
        }
    }

    #[test]
    fn no_results_gives_idle() {
        let mut sm = MovementStateMachine::new();
        let out = sm.update(&[]);
        assert_eq!(out.movement, Movement::Idle);
        assert_eq!(out.score, 0.0);
    }

    #[test]
    fn all_inactive_gives_idle() {
        let mut sm = MovementStateMachine::new();
        let r = make_result(ActivityLevel::Inactive, false);
        let out = sm.update(&[r]);
        assert_eq!(out.movement, Movement::Idle);
    }

    #[test]
    fn fallback_low_cpu_does_not_count() {
        let mut sm = MovementStateMachine::new();
        let r = make_result(ActivityLevel::ActiveLow, true);
        let out = sm.update(&[r]);
        assert_eq!(out.movement, Movement::Idle);
    }

    #[test]
    fn fallback_medium_cpu_counts() {
        let mut sm = MovementStateMachine::new();
        let r = make_result(ActivityLevel::ActiveMedium, true);
        let out = sm.update(&[r]);
        assert_eq!(out.movement, Movement::Walk);
    }

    #[test]
    fn primary_active_low_gives_idle() {
        let mut sm = MovementStateMachine::new();
        let r = make_result(ActivityLevel::ActiveLow, false);
        let out = sm.update(&[r]);
        assert_eq!(out.movement, Movement::Idle);
    }

    #[test]
    fn activity_stops_fully_resets_to_idle() {
        let mut sm = MovementStateMachine::new();
        let active = make_result(ActivityLevel::ActiveHigh, false);
        sm.update(&[active]);
        assert!(sm.active_since.is_some());

        let inactive = make_result(ActivityLevel::Inactive, false);
        let out = sm.update(&[inactive]);
        assert_eq!(out.movement, Movement::Idle);
        assert!(sm.active_since.is_none());
    }

    #[test]
    fn cooldown_keeps_walk_during_low_dip() {
        let mut sm = MovementStateMachine::new();

        let active = make_result(ActivityLevel::ActiveHigh, false);
        let out = sm.update(&[active]);
        assert_eq!(out.movement, Movement::Walk);
        assert!(sm.last_real_activity.is_some());

        let low = make_result(ActivityLevel::ActiveLow, false);
        let out = sm.update(&[low]);
        assert_eq!(
            out.movement,
            Movement::Walk,
            "ActiveLow within cooldown should stay Walk"
        );
    }

    #[test]
    fn cooldown_expires_then_idle() {
        let mut sm = MovementStateMachine::new();

        let active = make_result(ActivityLevel::ActiveHigh, false);
        sm.update(&[active]);

        sm.last_real_activity = Some(Instant::now() - ACTIVITY_COOLDOWN - Duration::from_secs(1));

        let low = make_result(ActivityLevel::ActiveLow, false);
        let out = sm.update(&[low]);
        assert_eq!(
            out.movement,
            Movement::Idle,
            "ActiveLow after cooldown expires should be Idle"
        );
    }

    #[test]
    fn cooldown_not_triggered_without_presence() {
        let mut sm = MovementStateMachine::new();

        let active = make_result(ActivityLevel::ActiveHigh, false);
        sm.update(&[active]);

        let inactive = make_result(ActivityLevel::Inactive, false);
        let out = sm.update(&[inactive]);
        assert_eq!(
            out.movement,
            Movement::Idle,
            "No presence at all should not trigger cooldown"
        );
    }

    #[test]
    fn new_activity_resets_cooldown_timer() {
        let mut sm = MovementStateMachine::new();

        let high = make_result(ActivityLevel::ActiveHigh, false);
        sm.update(&[high.clone()]);

        sm.last_real_activity = Some(Instant::now() - ACTIVITY_COOLDOWN + Duration::from_secs(5));

        sm.update(&[high]);
        let elapsed = sm.last_real_activity.unwrap().elapsed();
        assert!(
            elapsed < Duration::from_secs(1),
            "New ActiveHigh should reset cooldown timer"
        );
    }

    #[test]
    fn cooldown_reports_in_cooldown_flag() {
        let mut sm = MovementStateMachine::new();

        let high = make_result(ActivityLevel::ActiveHigh, false);
        let out = sm.update(&[high]);
        assert!(!out.in_cooldown, "Direct activity should not be cooldown");

        let low = make_result(ActivityLevel::ActiveLow, false);
        let out = sm.update(&[low]);
        assert!(
            out.in_cooldown,
            "ActiveLow within cooldown should flag in_cooldown"
        );
    }

    #[test]
    fn alternating_high_low_stays_active() {
        let mut sm = MovementStateMachine::new();
        let high = make_result(ActivityLevel::ActiveHigh, false);
        let low = make_result(ActivityLevel::ActiveLow, false);

        sm.update(&[high.clone()]);
        let out = sm.update(&[low.clone()]);
        assert_eq!(out.movement, Movement::Walk);

        sm.update(&[high.clone()]);
        let out = sm.update(&[low]);
        assert_eq!(out.movement, Movement::Walk);
        assert!(
            sm.active_since.is_some(),
            "active_since should persist across alternating cycles"
        );
    }

    #[test]
    fn multi_tool_speeds_up_progression() {
        let mut sm1 = MovementStateMachine::new();
        let mut sm2 = MovementStateMachine::new();

        let one_tool = [make_result_with_id(
            "cursor",
            ActivityLevel::ActiveHigh,
            false,
        )];
        let two_tools = [
            make_result_with_id("cursor", ActivityLevel::ActiveHigh, false),
            make_result_with_id("claude-code", ActivityLevel::ActiveMedium, false),
        ];

        let out1 = sm1.update(&one_tool);
        let out2 = sm2.update(&two_tools);

        assert_eq!(out2.active_tool_count, 2);
        assert!(out2.active_tool_count > out1.active_tool_count);
    }

    #[test]
    fn fallback_same_provider_does_not_double_count() {
        let primary = make_result_with_id("cursor", ActivityLevel::ActiveHigh, false);
        let fallback = ProbeResult {
            provider_id: "cursor-process".into(),
            provider_name: "Cursor (process)".into(),
            activity: ActivityLevel::ActiveMedium,
            is_fallback: true,
            ..primary.clone()
        };

        let count = count_unique_active_tools(&[primary, fallback]);
        assert_eq!(count, 1, "primary + its fallback should count as 1 tool");
    }

    #[test]
    fn different_providers_count_separately() {
        let cursor = make_result_with_id("cursor", ActivityLevel::ActiveHigh, false);
        let claude = make_result_with_id("claude-code", ActivityLevel::ActiveMedium, false);
        let count = count_unique_active_tools(&[cursor, claude]);
        assert_eq!(count, 2);
    }

    #[test]
    fn score_capped_at_100() {
        let mut sm = MovementStateMachine::new();
        sm.active_since = Some(Instant::now() - std::time::Duration::from_secs(600));
        let r = make_result(ActivityLevel::ActiveHigh, false);
        let out = sm.update(&[r]);
        assert!(out.score <= 100.0);
    }

    #[test]
    fn movement_str() {
        assert_eq!(Movement::Sprint.as_str(), "sprint");
        assert_eq!(Movement::Run.as_str(), "run");
        assert_eq!(Movement::Walk.as_str(), "walk");
        assert_eq!(Movement::Idle.as_str(), "idle");
    }

    #[test]
    fn progression_walk_to_run() {
        let mut sm = MovementStateMachine::new();
        sm.active_since = Some(Instant::now() - std::time::Duration::from_secs(65));
        let r = make_result(ActivityLevel::ActiveHigh, false);
        let out = sm.update(&[r]);
        assert_eq!(out.movement, Movement::Run);
        assert!(out.score >= 50.0 && out.score < 75.0);
    }

    #[test]
    fn progression_run_to_sprint() {
        let mut sm = MovementStateMachine::new();
        sm.active_since = Some(Instant::now() - std::time::Duration::from_secs(200));
        let r = make_result(ActivityLevel::ActiveHigh, false);
        let out = sm.update(&[r]);
        assert_eq!(out.movement, Movement::Sprint);
        assert!(out.score >= 75.0);
    }
}
