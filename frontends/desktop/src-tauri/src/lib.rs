use std::process::{Command, Child};
use std::sync::Mutex;
use std::net::TcpStream;
use std::time::{Duration, Instant};
use std::thread;
use std::path::PathBuf;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

static BRIDGE_PROCESS: Mutex<Option<Child>> = Mutex::new(None);

/// Get project root (parent of frontends/)
fn project_root() -> PathBuf {
    std::env::current_exe()
        .expect("cannot get exe path")
        .parent().expect("cannot get exe dir")   // frontends/
        .parent().expect("cannot get project root") // project root
        .to_path_buf()
}

fn find_bridge_script() -> PathBuf {
    // exe is at frontends/GenericAgent.exe
    // bridge is at frontends/desktop_bridge.py
    std::env::current_exe()
        .expect("cannot get exe path")
        .parent().expect("cannot get exe dir")
        .join("desktop_bridge.py")
}

/// Find python executable:
/// 1. .portable/uv-python/ 下找 python.exe (Windows) 或 python3 (Unix)
/// 2. Fallback to system PATH
fn find_python() -> String {
    let root = project_root();
    let portable_python_dir = root.join(".portable").join("uv-python");

    if portable_python_dir.exists() {
        // uv installs python like: uv-python/cpython-3.12.x-windows-x86_64/python.exe
        // We need to search for python.exe inside subdirectories
        if let Ok(entries) = std::fs::read_dir(&portable_python_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    #[cfg(windows)]
                    {
                        let py = path.join("python.exe");
                        if py.exists() {
                            return py.to_string_lossy().to_string();
                        }
                    }
                    #[cfg(not(windows))]
                    {
                        let py = path.join("bin").join("python3");
                        if py.exists() {
                            return py.to_string_lossy().to_string();
                        }
                    }
                }
            }
        }
    }

    // Fallback: system PATH
    #[cfg(windows)]
    { "python".to_string() }
    #[cfg(not(windows))]
    { "python3".to_string() }
}

fn is_bridge_running() -> bool {
    TcpStream::connect(("127.0.0.1", 14168)).is_ok()
}

fn wait_for_port(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    false
}

fn start_bridge() {
    let script = find_bridge_script();
    if !script.exists() {
        eprintln!("[tauri] bridge script not found: {:?}", script);
        return;
    }

    let python = find_python();
    eprintln!("[tauri] using python: {}", python);

    let show_console = std::env::args().any(|a| a == "--console");

    let mut cmd = Command::new(&python);
    cmd.arg(&script)
       .current_dir(script.parent().unwrap());

    #[cfg(windows)]
    if !show_console {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(child) => {
            eprintln!("[tauri] started bridge PID={}", child.id());
            *BRIDGE_PROCESS.lock().unwrap() = Some(child);
        }
        Err(e) => {
            eprintln!("[tauri] failed to start bridge: {} (python={})", e, python);
            return;
        }
    }

    if !wait_for_port(14168, Duration::from_secs(15)) {
        eprintln!("[tauri] WARNING: bridge did not become ready within 15s");
    }
}

fn ensure_bridge_running() {
    if is_bridge_running() {
        eprintln!("[tauri] bridge already running on 127.0.0.1:14168; reusing it");
        return;
    }
    start_bridge();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    ensure_bridge_running();

    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
