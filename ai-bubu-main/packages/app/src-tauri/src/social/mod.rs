pub mod discovery;
pub mod protocol;
pub mod util;

use discovery::SocialEngine;
use protocol::{Heartbeat, PeerUpdate, PROTOCOL_VERSION};
use std::sync::Mutex;
use tauri::AppHandle;
use util::truncate_str;

static SOCIAL_ENGINE: Mutex<Option<SocialEngine>> = Mutex::new(None);

const MAX_PEER_ID_LEN: usize = 64;

#[tauri::command]
pub fn social_start(app: AppHandle, peer_id: String) -> Result<(), String> {
    if peer_id.len() > MAX_PEER_ID_LEN {
        return Err(format!(
            "peer_id too long: {} (max {})",
            peer_id.len(),
            MAX_PEER_ID_LEN
        ));
    }

    let mut engine_lock = SOCIAL_ENGINE.lock().map_err(|e| e.to_string())?;

    if engine_lock.is_some() {
        return Ok(());
    }

    let mut engine = SocialEngine::new(peer_id);
    engine.start(app)?;
    *engine_lock = Some(engine);
    Ok(())
}

#[tauri::command]
pub fn social_stop() -> Result<(), String> {
    let mut engine_lock = SOCIAL_ENGINE.lock().map_err(|e| e.to_string())?;
    if let Some(ref mut engine) = *engine_lock {
        engine.stop();
    }
    *engine_lock = None;
    Ok(())
}

#[tauri::command]
pub fn social_broadcast(
    nickname: String,
    daily_steps: u64,
    activity_score: u8,
    movement_state: String,
    pet_skin: String,
) -> Result<(), String> {
    let engine_lock = SOCIAL_ENGINE.lock().map_err(|e| e.to_string())?;
    if let Some(ref engine) = *engine_lock {
        let heartbeat = Heartbeat {
            peer_id: engine.peer_id().to_string(),
            nickname: truncate_str(nickname, 30),
            daily_steps,
            activity_score: activity_score.min(100),
            movement_state: truncate_str(movement_state, 10),
            pet_skin: truncate_str(pet_skin, 50),
            version: PROTOCOL_VERSION.to_string(),
        };
        engine.broadcast(&heartbeat)?;
    }
    Ok(())
}

#[tauri::command]
pub fn social_get_peers() -> Result<Vec<PeerUpdate>, String> {
    let engine_lock = SOCIAL_ENGINE.lock().map_err(|e| e.to_string())?;
    match *engine_lock {
        Some(ref engine) => Ok(engine.get_peers()),
        None => Ok(vec![]),
    }
}
