// SECURITY: LAN-only social discovery via UDP broadcast.
// No authentication — any host on the same subnet can send spoofed heartbeats.
// Acceptable for the "fun office leaderboard" use case. If stronger guarantees
// are needed (e.g. public networks), add HMAC signing or switch to TCP+TLS.

use super::protocol::*;
use std::collections::HashMap;
use std::net::UdpSocket;
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};

const MAX_PEERS: usize = 50;
const MAX_PACKETS_PER_SEC: usize = 100;

pub struct SocialEngine {
    peer_id: String,
    socket: Option<UdpSocket>,
    peers: Arc<Mutex<HashMap<String, (PeerUpdate, Instant)>>>,
    running: Arc<Mutex<bool>>,
    recv_thread: Option<JoinHandle<()>>,
}

impl SocialEngine {
    pub fn new(peer_id: String) -> Self {
        Self {
            peer_id,
            socket: None,
            peers: Arc::new(Mutex::new(HashMap::new())),
            running: Arc::new(Mutex::new(false)),
            recv_thread: None,
        }
    }

    pub fn start(&mut self, app_handle: AppHandle) -> Result<(), String> {
        let socket = UdpSocket::bind(format!("0.0.0.0:{}", BROADCAST_PORT)).map_err(|e| {
            format!(
                "Failed to bind UDP port {}: {}. Is another instance running?",
                BROADCAST_PORT, e
            )
        })?;

        socket.set_broadcast(true).map_err(|e| e.to_string())?;
        socket
            .set_read_timeout(Some(Duration::from_millis(1000)))
            .map_err(|e| e.to_string())?;

        self.socket = Some(socket.try_clone().map_err(|e| e.to_string())?);

        match self.running.lock() {
            Ok(mut running) => *running = true,
            Err(e) => eprintln!("social: running mutex poisoned on start: {}", e),
        }

        let peers = self.peers.clone();
        let running = self.running.clone();
        let peer_id = self.peer_id.clone();

        let handle = std::thread::spawn(move || {
            let mut buf = [0u8; 4096];
            let mut pkt_count: usize = 0;
            let mut pkt_window = Instant::now();

            loop {
                let is_running = match running.lock() {
                    Ok(guard) => *guard,
                    Err(_) => break,
                };
                if !is_running {
                    break;
                }

                if pkt_window.elapsed() >= Duration::from_secs(1) {
                    pkt_count = 0;
                    pkt_window = Instant::now();
                }

                match socket.recv_from(&mut buf) {
                    Ok((size, _addr)) => {
                        pkt_count += 1;
                        if pkt_count > MAX_PACKETS_PER_SEC {
                            continue;
                        }
                        if let Ok(heartbeat) = serde_json::from_slice::<Heartbeat>(&buf[..size]) {
                            if heartbeat.peer_id == peer_id {
                                continue;
                            }

                            if heartbeat.version != PROTOCOL_VERSION {
                                continue;
                            }

                            let update = PeerUpdate {
                                peer_id: heartbeat.peer_id.clone(),
                                nickname: super::util::truncate_str(heartbeat.nickname, 30),
                                daily_steps: heartbeat.daily_steps,
                                activity_score: heartbeat.activity_score,
                                movement_state: super::util::truncate_str(
                                    heartbeat.movement_state,
                                    10,
                                ),
                                pet_skin: super::util::truncate_str(heartbeat.pet_skin, 50),
                                is_online: true,
                            };

                            match peers.lock() {
                                Ok(mut peers_lock) => {
                                    let is_existing = peers_lock.contains_key(&heartbeat.peer_id);
                                    if !is_existing && peers_lock.len() >= MAX_PEERS {
                                        continue;
                                    }
                                    peers_lock.insert(
                                        heartbeat.peer_id,
                                        (update.clone(), Instant::now()),
                                    );
                                }
                                Err(e) => {
                                    eprintln!("social: peers mutex poisoned on insert: {}", e)
                                }
                            }

                            let _ = app_handle.emit("social-peer-update", &update);
                        }
                    }
                    Err(ref e)
                        if e.kind() == std::io::ErrorKind::WouldBlock
                            || e.kind() == std::io::ErrorKind::TimedOut => {}
                    Err(e) => {
                        eprintln!("social recv error: {}", e);
                    }
                }

                match peers.lock() {
                    Ok(mut peers_lock) => {
                        let timeout = Duration::from_millis(PEER_TIMEOUT_MS);
                        let expired: Vec<String> = peers_lock
                            .iter()
                            .filter(|(_, (_, last))| last.elapsed() > timeout)
                            .map(|(id, _)| id.clone())
                            .collect();

                        for id in expired {
                            if let Some((mut update, _)) = peers_lock.remove(&id) {
                                update.is_online = false;
                                let _ = app_handle.emit("social-peer-update", &update);
                            }
                        }
                    }
                    Err(e) => eprintln!("social: peers mutex poisoned on cleanup: {}", e),
                }
            }
        });

        self.recv_thread = Some(handle);
        Ok(())
    }

    pub fn broadcast(&self, heartbeat: &Heartbeat) -> Result<(), String> {
        if let Some(ref socket) = self.socket {
            let data = serde_json::to_vec(heartbeat).map_err(|e| e.to_string())?;
            let addr = format!("255.255.255.255:{}", BROADCAST_PORT);
            socket.send_to(&data, &addr).map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    pub fn stop(&mut self) {
        match self.running.lock() {
            Ok(mut running) => *running = false,
            Err(e) => eprintln!("social: running mutex poisoned on stop: {}", e),
        }
        if let Some(handle) = self.recv_thread.take() {
            let _ = handle.join();
        }
    }

    pub fn peer_id(&self) -> &str {
        &self.peer_id
    }

    pub fn get_peers(&self) -> Vec<PeerUpdate> {
        match self.peers.lock() {
            Ok(peers) => peers.values().map(|(p, _)| p.clone()).collect(),
            Err(_) => vec![],
        }
    }
}
