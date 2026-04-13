use serde::{Deserialize, Serialize};

pub const BROADCAST_PORT: u16 = 23456;
pub const PEER_TIMEOUT_MS: u64 = 15000;
pub const PROTOCOL_VERSION: &str = "0.1.0";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Heartbeat {
    pub peer_id: String,
    pub nickname: String,
    pub daily_steps: u64,
    pub activity_score: u8,
    pub movement_state: String,
    pub pet_skin: String,
    pub version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PeerUpdate {
    pub peer_id: String,
    pub nickname: String,
    pub daily_steps: u64,
    pub activity_score: u8,
    pub movement_state: String,
    pub pet_skin: String,
    pub is_online: bool,
}
