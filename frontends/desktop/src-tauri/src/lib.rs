use std::process::{Command, Child, Stdio};
use std::io::{BufRead, BufReader};
use std::sync::Mutex;
use std::net::TcpStream;
use std::time::{Duration, Instant};
use std::thread;
use std::path::PathBuf;
use tauri::Manager;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

static BRIDGE_PROCESS: Mutex<Option<Child>> = Mutex::new(None);
const DEFAULT_MAIN_WINDOW_WIDTH: f64 = 1280.0;
const DEFAULT_MAIN_WINDOW_HEIGHT: f64 = 800.0;
const MIN_MAIN_WINDOW_WIDTH: f64 = 480.0;
const MIN_MAIN_WINDOW_HEIGHT: f64 = 320.0;

type SettingsMap = serde_json::Map<String, serde_json::Value>;

#[derive(Debug, PartialEq)]
struct MainWindowSettings {
    width: Option<f64>,
    height: Option<f64>,
    maximized: Option<bool>,
}

/// Get project root (parent of frontends/)
fn project_root() -> PathBuf {
    std::env::current_exe()
        .expect("cannot get exe path")
        .parent().expect("cannot get exe dir")   // frontends/
        .parent().expect("cannot get project root") // project root
        .to_path_buf()
}

/// Directory next to which a self-contained bundle keeps its runtime/ folder.
/// Windows: the exe's folder. Linux: the .AppImage's folder ($APPIMAGE) when launched as an
/// AppImage (current_exe would otherwise point inside the read-only squashfs mount).
/// macOS portable package: the folder containing GenericAgent.app and runtime/.
fn bundle_anchor_dir() -> Option<PathBuf> {
    #[cfg(not(windows))]
    {
        if let Some(p) = std::env::var_os("APPIMAGE") {
            if let Some(d) = PathBuf::from(p).parent() {
                return Some(d.to_path_buf());
            }
        }
    }

    let exe = std::env::current_exe().ok()?;

    #[cfg(target_os = "macos")]
    {
        // current_exe() inside a bundle is:
        //   <package>/GenericAgent.app/Contents/MacOS/GenericAgent
        // Prefer the standard macOS layout where runtime is embedded in the app:
        //   GenericAgent.app/Contents/Resources/runtime/app/agentmain.py
        // Fall back to the old portable layout for compatibility:
        //   <package>/runtime/app/agentmain.py
        let mut d = exe.parent();
        while let Some(dir) = d {
            if dir.extension().and_then(|s| s.to_str()) == Some("app") {
                let resources = dir.join("Contents").join("Resources");
                if resources.join("runtime").join("app").join("agentmain.py").exists() {
                    return Some(resources);
                }
                if let Some(parent) = dir.parent() {
                    return Some(parent.to_path_buf());
                }
            }
            d = dir.parent();
        }
    }

    Some(exe.parent()?.to_path_buf())
}

/// Embedded interpreter inside the bundle's runtime/python (base python, before venv).
fn bundle_python() -> Option<PathBuf> {
    let root = bundle_root()?;
    #[cfg(windows)]
    let p = root.join("python").join("python.exe");
    #[cfg(not(windows))]
    let p = root.join("python").join("bin").join("python3");
    if p.exists() { Some(p) } else { None }
}

/// Find python executable:
/// 1. The embedded bundle python (runtime/python) — deps are installed directly into it
///    (no venv), and its path is resolved relative to the bundle anchor at runtime, so the
///    package stays relocatable (moving the folder doesn't break absolute venv paths).
/// 2. .portable/uv-python/ 下找 python.exe (Windows) 或 python3 (Unix)
/// 3. Fallback to system PATH
fn find_python() -> String {
    if let Some(p) = bundle_python() {
        return p.to_string_lossy().to_string();
    }
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

/// Find the project directory (folder containing agentmain.py).
/// Bundle layout: <exe dir>/runtime/app/agentmain.py. Dev layout: walk up from the exe.
fn find_project_dir() -> Option<String> {
    // Bundle layout: source tucked under <anchor>/runtime/app/
    if let Some(anchor) = bundle_anchor_dir() {
        let app = anchor.join("runtime").join("app");
        if app.join("agentmain.py").exists() {
            return Some(app.to_string_lossy().to_string());
        }
    }

    // Dev/source layout: walk up to 8 levels from the exe location.
    let exe = std::env::current_exe().ok()?;
    let mut dir = Some(exe.parent()?);
    for _ in 0..8 {
        match dir {
            Some(d) => {
                if d.join("agentmain.py").exists() {
                    return Some(d.to_string_lossy().to_string());
                }
                dir = d.parent();
            }
            None => break,
        }
    }
    None
}

/// Settings file path: ~/.ga_desktop_settings.json
fn settings_path() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".ga_desktop_settings.json")
}

/// Read the settings file as a JSON object (empty object when missing/unparseable).
fn read_settings() -> SettingsMap {
    let path = settings_path();
    if let Ok(content) = std::fs::read_to_string(&path) {
        if let Ok(serde_json::Value::Object(m)) = serde_json::from_str(&content) {
            return m;
        }
    }
    serde_json::Map::new()
}

fn setting_dimension(settings: &SettingsMap, key: &str, fallback_key: &str, min: f64) -> Option<f64> {
    settings
        .get(key)
        .or_else(|| settings.get(fallback_key))
        .and_then(|v| v.as_f64())
        .filter(|v| v.is_finite() && *v >= min)
}

fn main_window_settings_from(settings: &SettingsMap) -> MainWindowSettings {
    MainWindowSettings {
        width: setting_dimension(settings, "window_width", "width", MIN_MAIN_WINDOW_WIDTH),
        height: setting_dimension(settings, "window_height", "height", MIN_MAIN_WINDOW_HEIGHT),
        maximized: settings.get("maximized").and_then(|v| v.as_bool()),
    }
}

fn read_main_window_settings() -> MainWindowSettings {
    main_window_settings_from(&read_settings())
}

fn apply_main_window_settings(window: &tauri::WebviewWindow) {
    let settings = read_main_window_settings();
    if settings.width.is_some() || settings.height.is_some() {
        let _ = window.set_size(tauri::LogicalSize::new(
            settings.width.unwrap_or(DEFAULT_MAIN_WINDOW_WIDTH),
            settings.height.unwrap_or(DEFAULT_MAIN_WINDOW_HEIGHT),
        ));
    }
    match settings.maximized {
        Some(true) => { let _ = window.maximize(); }
        Some(false) => { let _ = window.unmaximize(); }
        None => {}
    }
}

/// Merge `updates` into the existing settings file and write it back, preserving any keys
/// we don't touch. The old code rewrote the file with only python_path/project_dir, which
/// would silently drop sibling keys like `desktop_shortcut`. Always go through here.
fn merge_settings(updates: serde_json::Value) {
    let mut obj = read_settings();
    if let serde_json::Value::Object(m) = updates {
        for (k, v) in m {
            obj.insert(k, v);
        }
    }
    let val = serde_json::Value::Object(obj);
    if let Ok(text) = serde_json::to_string_pretty(&val) {
        let _ = std::fs::write(settings_path(), text);
    }
}

/// Desktop-shortcut preference stored in settings under `desktop_shortcut`.
/// None  = never asked (first run)
/// Some(true)/Some(false) = user's remembered choice.
fn read_shortcut_pref() -> Option<bool> {
    read_settings().get("desktop_shortcut").and_then(|v| v.as_bool())
}

fn write_shortcut_pref(enabled: bool) {
    merge_settings(serde_json::json!({ "desktop_shortcut": enabled }));
}

/// Create (or overwrite) a desktop shortcut pointing at the CURRENT exe. Overwriting on every
/// enabled launch is what makes the portable bundle relocatable: move the folder, relaunch, and
/// the shortcut is rewritten to the new path. Windows-only (uses a .lnk via WScript.Shell).
#[cfg(windows)]
fn ensure_desktop_shortcut() {
    let Ok(exe) = std::env::current_exe() else { return; };
    let Some(desktop) = dirs::desktop_dir() else { return; };
    let lnk = desktop.join("GenericAgent.lnk");
    let work_dir = exe.parent().map(|p| p.to_path_buf()).unwrap_or_else(|| exe.clone());

    let exe_s = exe.to_string_lossy().replace('\'', "''");
    let lnk_s = lnk.to_string_lossy().replace('\'', "''");
    let work_s = work_dir.to_string_lossy().replace('\'', "''");

    // Build the shortcut via WScript.Shell COM, consistent with the existing powershell usage
    // elsewhere in this file. No extra crate needed.
    let script = format!(
        "$ws = New-Object -ComObject WScript.Shell; \
         $sc = $ws.CreateShortcut('{lnk}'); \
         $sc.TargetPath = '{exe}'; \
         $sc.WorkingDirectory = '{work}'; \
         $sc.IconLocation = '{exe}'; \
         $sc.Save()",
        lnk = lnk_s, exe = exe_s, work = work_s
    );

    let mut cmd = Command::new("powershell.exe");
    cmd.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &script]);
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    let _ = cmd.status();
}

#[cfg(target_os = "linux")]
fn ensure_desktop_shortcut() {
    // Launch target: the AppImage path when running as one, else the current exe. Writing the
    // current path on every enabled launch keeps a relocated bundle's launcher valid.
    let Some(target) = std::env::var_os("APPIMAGE").map(PathBuf::from)
        .or_else(|| std::env::current_exe().ok()) else { return; };
    let exec = target.to_string_lossy().replace('"', "");
    // Linux .desktop Icon= needs an image file (or themed name), not the AppImage path. The CI
    // ships GenericAgent.png next to the AppImage; fall back to a generic themed icon otherwise.
    let icon = bundle_anchor_dir()
        .map(|d| d.join("GenericAgent.png"))
        .filter(|p| p.exists())
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|| "application-x-executable".to_string());
    let entry = format!(
        "[Desktop Entry]\nType=Application\nName=GenericAgent\nComment=GenericAgent Desktop\n\
         Exec=\"{exec}\"\nIcon={icon}\nTerminal=false\nCategories=Utility;Development;\n",
        exec = exec, icon = icon
    );
    let write_desktop = |path: &std::path::Path| {
        if std::fs::write(path, &entry).is_ok() {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755));
        }
    };
    if let Some(home) = dirs::home_dir() {
        let apps = home.join(".local/share/applications");
        let _ = std::fs::create_dir_all(&apps);
        write_desktop(&apps.join("GenericAgent.desktop"));
    }
    if let Some(desktop) = dirs::desktop_dir() {
        let _ = std::fs::create_dir_all(&desktop);
        let f = desktop.join("GenericAgent.desktop");
        write_desktop(&f);
        // GNOME marks unknown launchers "untrusted"; flag ours so it runs on double-click. Best effort.
        let _ = Command::new("gio")
            .args(["set", &f.to_string_lossy(), "metadata::trusted", "true"])
            .status();
    }
}

#[cfg(target_os = "macos")]
fn ensure_desktop_shortcut() {
    // The .app is the launchable unit; drop a symlink to it on the Desktop.
    let Ok(exe) = std::env::current_exe() else { return; };
    let mut app: Option<PathBuf> = None;
    let mut d = exe.parent();
    while let Some(dir) = d {
        if dir.extension().and_then(|s| s.to_str()) == Some("app") { app = Some(dir.to_path_buf()); break; }
        d = dir.parent();
    }
    let (Some(app), Some(desktop)) = (app, dirs::desktop_dir()) else { return; };
    let link = desktop.join("GenericAgent.app");
    let _ = std::fs::remove_file(&link);
    let _ = std::os::unix::fs::symlink(&app, &link);
}

#[cfg(all(not(windows), not(target_os = "linux"), not(target_os = "macos")))]
fn ensure_desktop_shortcut() {}

/// First-run shortcut handling for portable bundles (all platforms). Self-heals the shortcut
/// path on every enabled launch (cheap, no UI). The first-run ASK is driven by the frontend
/// (see the `shortcut_should_ask` / `shortcut_decide` commands): a native dialog from this
/// background startup thread has no parent window and gets buried behind the main window on
/// first launch, so the prompt is owned by the web UI instead, which always renders on top.
fn maybe_setup_shortcut() {
    if bundle_root().is_none() {
        return;
    }
    // Only self-heal when the user already opted in. Never prompt here.
    if read_shortcut_pref() == Some(true) {
        ensure_desktop_shortcut();
    }
}

/// Frontend asks whether to show the first-run "create desktop shortcut?" prompt.
/// True only on a portable bundle whose preference has never been set.
#[tauri::command]
fn shortcut_should_ask() -> bool {
    bundle_root().is_some() && read_shortcut_pref().is_none()
}

/// Frontend reports the user's choice. Persists it and creates the shortcut when enabled.
#[tauri::command]
fn shortcut_decide(create: bool) {
    write_shortcut_pref(create);
    if create {
        ensure_desktop_shortcut();
    }
}

/// True when this binary is running from inside a macOS .app bundle (packaged build).
/// Used to refuse stale ~/.ga_desktop_settings.json that could point at an old checkout
/// when App Translocation hides our own runtime/ from current_exe().
#[cfg(target_os = "macos")]
fn running_inside_app_bundle() -> bool {
    std::env::current_exe()
        .ok()
        .map(|p| {
            p.components().any(|c| {
                c.as_os_str().to_string_lossy().ends_with(".app")
            })
        })
        .unwrap_or(false)
}

/// Read config from settings file, or auto-discover and save.
/// Self-contained bundles always prefer their own runtime/app over stale user settings,
/// otherwise an old ~/.ga_desktop_settings.json can silently point the UI at a different checkout.
pub fn get_or_discover_config() -> (String, String) {
    let path = settings_path();

    if bundle_root().is_some() {
        let python = find_python();
        let project = find_project_dir().unwrap_or_default();
        if !python.is_empty() && !project.is_empty() {
            merge_settings(serde_json::json!({
                "python_path": python,
                "project_dir": project
            }));
            return (python, project);
        }
    }

    // Try reading existing settings.
    // On macOS, a packaged .app must never trust ~/.ga_desktop_settings.json: App
    // Translocation can run the bundle from a random read-only copy where bundle_root()
    // fails to see our own runtime/, and an old settings file would then silently point
    // the bridge at a previously installed checkout. In that case fall through to
    // auto-discovery (which still resolves the bundle via .app-relative search below).
    #[cfg(target_os = "macos")]
    let trust_settings = !running_inside_app_bundle();
    #[cfg(not(target_os = "macos"))]
    let trust_settings = true;

    if trust_settings && path.exists() {
        if let Ok(content) = std::fs::read_to_string(&path) {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                let python = val.get("python_path")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                let project = val.get("project_dir")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string();
                if !python.is_empty() && !project.is_empty() {
                    return (python, project);
                }
            }
        }
    }

    // Auto-discover
    let python = find_python();
    let project = find_project_dir().unwrap_or_default();

    // Save discovered config
    if !python.is_empty() && !project.is_empty() {
        merge_settings(serde_json::json!({
            "python_path": python,
            "project_dir": project
        }));
    }

    (python, project)
}

/// Self-contained bundle support dir: holds python/, wheels/, install_windows.ps1 and app/.
/// Typical portable layout keeps only the exe (+README) at the top level and tucks everything
/// else under <exe dir>/runtime/. Returns None when this is not a bundle (e.g. dev build).
fn bundle_root() -> Option<PathBuf> {
    let runtime = bundle_anchor_dir()?.join("runtime");
    if runtime.join("app").join("agentmain.py").exists() {
        return Some(runtime);
    }
    None
}

/// Marker written after a successful offline prepare. Lives under runtime/ so it travels
/// with the bundle: a relocated folder stays "prepared" (deps live in the embedded python,
/// which is itself relocatable) and won't re-run prepare.
fn prepared_marker() -> Option<PathBuf> {
    Some(bundle_root()?.join(".prepared"))
}

/// True when this is a self-contained bundle whose python env has not been prepared yet
/// (embedded python present but deps not yet installed into it).
fn needs_first_run_prepare(project_dir: &str) -> bool {
    if project_dir.is_empty() { return false; }
    bundle_python().is_some() && prepared_marker().map(|m| !m.exists()).unwrap_or(false)
}

/// Clear env vars a host launcher injects pointing at its own runtime. The Linux AppImage exports
/// PYTHONHOME/PYTHONPATH (-> bundled python crashes with "No module named 'encodings'") and
/// LD_LIBRARY_PATH (-> wrong shared libs). Our bundled python / prepare / bridge must run clean.
fn sanitize_bundle_env(cmd: &mut Command) {
    cmd.env_remove("PYTHONHOME");
    cmd.env_remove("PYTHONPATH");
    cmd.env_remove("LD_LIBRARY_PATH");
    // Stamp the bridge we spawn with this build's id so a later app launch can tell whether the
    // bridge holding :14168 is ours (see bridge_identity_matches / GET /services/identity).
    cmd.env("GA_BUILD_ID", env!("GA_BUILD_ID"));
}

/// Run the offline prepare (install_windows.ps1 -Mode PrepareOnly) using bundled python + wheels.
/// Streams the script's stdout and forwards GAPROGRESS markers to `report(pct, message)`.
/// Blocking; intended to run on a background thread. Writes ~/.ga_desktop_settings.json.
fn run_offline_prepare(project_dir: &str, report: &dyn Fn(i32, &str)) -> Result<(), String> {
    let root = bundle_root().ok_or("cannot locate bundle root")?;
    let wheels = root.join("wheels");

    #[cfg(windows)]
    let (script, py) = (
        root.join("install_windows.ps1"),
        root.join("python").join("python.exe"),
    );
    #[cfg(target_os = "macos")]
    let (script, py) = (
        root.join("install_macos.sh"),
        root.join("python").join("bin").join("python3"),
    );
    #[cfg(all(not(windows), not(target_os = "macos")))]
    let (script, py) = (
        root.join("install_linux.sh"),
        root.join("python").join("bin").join("python3"),
    );

    if !script.exists() || !py.exists() || !wheels.exists() {
        return Err(format!("prepare resources missing under {:?}", root));
    }

    #[cfg(windows)]
    let mut cmd = {
        let mut c = Command::new("powershell.exe");
        c.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
            .arg(&script)
            .arg("-PythonPath").arg(&py)
            .arg("-ProjectDir").arg(project_dir)
            .arg("-WheelDir").arg(&wheels)
            .arg("-ExtraPipPackages").arg("fastapi uvicorn websockets")
            // -NoVenv: install deps straight into the embedded python (no venv) so the
            // bundle is relocatable. See prepared_marker / find_python.
            .args(["-Mode", "PrepareOnly", "-SkipNpmInstall", "-NoVenv"]);
        c
    };
    #[cfg(not(windows))]
    let mut cmd = {
        let mut c = Command::new("bash");
        c.arg(&script)
            .arg("--python-path").arg(&py)
            .arg("--project-dir").arg(project_dir)
            .arg("--wheel-dir").arg(&wheels)
            .arg("--extra-packages").arg("fastapi uvicorn websockets")
            // --no-venv: install deps straight into the embedded python (no venv) so the
            // bundle is relocatable. See prepared_marker / find_python.
            .args(["--mode", "PrepareOnly", "--no-venv"]);
        c
    };

    cmd.stdout(Stdio::piped()).stderr(Stdio::null());
    sanitize_bundle_env(&mut cmd);
    #[cfg(windows)]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    let mut child = cmd.spawn().map_err(|e| format!("failed to launch prepare: {}", e))?;

    // Forward the script's ASCII progress keys to the loading window, which localizes them
    // (window.gaProgress maps key -> zh/en by navigator.language).
    if let Some(out) = child.stdout.take() {
        for line in BufReader::new(out).lines().flatten() {
            if let Some(key) = line.trim().strip_prefix("GAPROGRESS|") {
                match key.trim() {
                    "venv" => report(15, "venv"),
                    "deps" => report(45, "deps"),
                    "done" => report(90, "done"),
                    _ => {}
                }
            }
        }
    }

    let status = child.wait().map_err(|e| format!("prepare wait failed: {}", e))?;
    if !status.success() {
        return Err(format!("prepare exited with status {:?}", status.code()));
    }
    // Record success so later launches (and relocated copies) skip the prepare step.
    if let Some(marker) = prepared_marker() {
        let _ = std::fs::write(&marker, b"ok\n");
    }
    Ok(())
}

/// GET /services/identity from a running bridge; returns the parsed JSON (or None when the
/// endpoint is absent — i.e. an older/foreign bridge).
fn bridge_reported_identity() -> Option<serde_json::Value> {
    use std::io::{Read, Write};
    let mut stream = TcpStream::connect_timeout(
        &"127.0.0.1:14168".parse().unwrap(),
        Duration::from_millis(800),
    ).ok()?;
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(600)));
    let req = b"GET /services/identity HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    stream.write_all(req).ok()?;
    let mut buf = Vec::new();
    let _ = stream.read_to_end(&mut buf);
    let text = String::from_utf8_lossy(&buf);
    let body = text.split("\r\n\r\n").nth(1)?;
    serde_json::from_str(body.trim()).ok()
}

fn norm_path(p: &str) -> String {
    std::fs::canonicalize(p)
        .map(|c| c.to_string_lossy().to_string())
        .unwrap_or_else(|_| p.to_string())
}

/// A running bridge is "ours" only when it serves the same install path AND was spawned by the
/// same build. The build id (commit+timestamp, see build.rs) changes on every build, so an
/// in-place upgrade or a same-version re-publish still counts as a different bridge → take over.
/// An old bridge with no /identity (None) or no build_id field ("") never matches → taken over.
fn bridge_identity_matches(project_dir: &str) -> bool {
    let Some(id) = bridge_reported_identity() else { return false; };
    let reported_root = id.get("ga_root").and_then(|v| v.as_str()).unwrap_or("");
    let reported_build = id.get("build_id").and_then(|v| v.as_str()).unwrap_or("");
    if reported_build != env!("GA_BUILD_ID") {
        return false;
    }
    let (a, b) = (norm_path(reported_root), norm_path(project_dir));
    #[cfg(windows)]
    { a.eq_ignore_ascii_case(&b) }
    #[cfg(not(windows))]
    { a == b }
}

/// Last resort when a stale bridge ignores POST /services/bridge/exit (e.g. an old build with
/// no such endpoint): force-kill whatever process is listening on :14168 so the new bridge can
/// bind it. Only called after an identity mismatch, so we never kill a bridge that is ours.
fn force_free_bridge_port() {
    #[cfg(windows)]
    {
        // netstat -ano: last column is the PID for the :14168 LISTENING row.
        if let Ok(out) = Command::new("netstat").args(["-ano", "-p", "tcp"]).output() {
            let text = String::from_utf8_lossy(&out.stdout);
            for line in text.lines() {
                if line.contains(":14168") && line.to_uppercase().contains("LISTENING") {
                    if let Some(pid) = line.split_whitespace().last() {
                        let mut c = Command::new("taskkill");
                        c.args(["/F", "/PID", pid]);
                        c.creation_flags(0x08000000);
                        let _ = c.status();
                    }
                }
            }
        }
    }
    #[cfg(not(windows))]
    {
        // lsof prints the listening PIDs; kill -9 each.
        if let Ok(out) = Command::new("lsof").args(["-ti", "tcp:14168", "-sTCP:LISTEN"]).output() {
            for pid in String::from_utf8_lossy(&out.stdout).split_whitespace() {
                let _ = Command::new("kill").args(["-9", pid]).status();
            }
        }
    }
}

fn request_bridge_shutdown() {
    use std::io::{Read, Write};
    let Ok(mut stream) = TcpStream::connect_timeout(
        &"127.0.0.1:14168".parse().unwrap(),
        Duration::from_millis(800),
    ) else {
        return;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(600)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(600)));
    let req = b"POST /services/bridge/exit HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
    let _ = stream.write_all(req);
    let _ = stream.read(&mut [0u8; 512]);
}

fn takeover_stale_bridge(project_dir: &str) {
    if project_dir.is_empty() || !is_bridge_running() {
        return;
    }
    if bridge_identity_matches(project_dir) {
        return;
    }
    eprintln!("[tauri] a different/stale bridge holds 127.0.0.1:14168; taking over");
    request_bridge_shutdown();
    let start = Instant::now();
    while is_bridge_running() && start.elapsed() < Duration::from_secs(10) {
        thread::sleep(Duration::from_millis(200));
    }
    // Old bridges have no /services/bridge/exit endpoint and ignore the request above — if the
    // port is still held, force-kill the listener so our fresh bridge can bind it.
    if is_bridge_running() {
        eprintln!("[tauri] stale bridge did not exit; force-freeing :14168");
        force_free_bridge_port();
        let start = Instant::now();
        while is_bridge_running() && start.elapsed() < Duration::from_secs(5) {
            thread::sleep(Duration::from_millis(200));
        }
    }
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

fn spawn_bridge_process(python_path: &str, project_dir: &str) -> Result<(), String> {
    if is_bridge_running() {
        return Ok(());
    }
    let py = PathBuf::from(python_path);
    let dir = PathBuf::from(project_dir);
    let script = dir.join("frontends").join("desktop_bridge.py");
    if !script.exists() {
        return Err(format!("desktop_bridge.py not found at {:?}", script));
    }

    let mut cmd = Command::new(&py);
    cmd.arg(&script).current_dir(&dir);
    sanitize_bundle_env(&mut cmd);
    #[cfg(windows)]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    let child = cmd.spawn().map_err(|e| format!("Failed to spawn: {}", e))?;
    *BRIDGE_PROCESS.lock().unwrap() = Some(child);
    Ok(())
}

fn show_bridge_window(app_handle: &tauri::AppHandle) {
    if let Some(main_win) = app_handle.get_webview_window("main") {
        let url = tauri::Url::parse("http://127.0.0.1:14168/").unwrap();
        let _ = main_win.navigate(url);
        apply_main_window_settings(&main_win);
        let _ = main_win.show();
        let _ = main_win.set_focus();
    }
    if let Some(setup_win) = app_handle.get_webview_window("setup") {
        let _ = setup_win.hide();
    }
}

#[tauri::command]
fn start_bridge_with_config(app_handle: tauri::AppHandle, python_path: String, project_dir: String) -> Result<(), String> {
    // Save to settings (merge so sibling keys like desktop_shortcut survive).
    merge_settings(serde_json::json!({"python_path": python_path, "project_dir": project_dir}));

    spawn_bridge_process(&python_path, &project_dir)?;

    // Wait for port
    if !wait_for_port(14168, Duration::from_secs(20)) {
        return Err("Bridge did not become ready within 20s".into());
    }

    show_bridge_window(&app_handle);
    Ok(())
}

#[tauri::command]
fn start_bridge(app_handle: tauri::AppHandle) -> Result<(), String> {
    let (python_path, project_dir) = get_or_discover_config();
    spawn_bridge_process(&python_path, &project_dir)?;
    if !wait_for_port(14168, Duration::from_secs(20)) {
        return Err("Bridge did not become ready within 20s".into());
    }
    show_bridge_window(&app_handle);
    Ok(())
}

#[tauri::command]
fn get_config() -> (String, String) {
    get_or_discover_config()
}

#[tauri::command]
fn export_mykey(content: String) -> Result<Option<String>, String> {
    let path = rfd::FileDialog::new()
        .set_file_name("mykey.py")
        .add_filter("Python", &["py"])
        .save_file();
    match path {
        Some(p) => {
            std::fs::write(&p, content.as_bytes()).map_err(|e| e.to_string())?;
            Ok(Some(p.to_string_lossy().into_owned()))
        }
        None => Ok(None),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let args: Vec<String> = std::env::args().collect();
    let no_autostart = args.iter().any(|a| a == "--no-autostart");
    let dev_mode = args.iter().any(|a| a == "--dev");

    let project_dir = find_project_dir().unwrap_or_default();
    let needs_prepare = needs_first_run_prepare(&project_dir);

    takeover_stale_bridge(&project_dir);

    let bridge_ok = is_bridge_running();
    let mut spawned_bridge = false;
    // Skip the early spawn when a first-run prepare is required (no venv yet);
    // the setup thread prepares the env first and then starts the bridge.
    if !bridge_ok && !no_autostart && !needs_prepare {
        // Try to start bridge with saved/discovered config
        let (py_str, dir_str) = get_or_discover_config();
        let dir = PathBuf::from(&dir_str);
        let script = dir.join("frontends").join("desktop_bridge.py");
        if script.exists() {
            let mut cmd = Command::new(&py_str);
            cmd.arg(&script).current_dir(&dir);
            sanitize_bundle_env(&mut cmd);
            #[cfg(windows)]
            cmd.creation_flags(0x08000000);
            if let Ok(child) = cmd.spawn() {
                *BRIDGE_PROCESS.lock().unwrap() = Some(child);
                spawned_bridge = true;
            }
        }
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .invoke_handler(tauri::generate_handler![start_bridge_with_config, start_bridge, get_config, export_mykey, shortcut_should_ask, shortcut_decide])
        .setup(move |app| {
            // Show the loading window immediately so the first-run prepare isn't a blank screen.
            // The window starts on loading.html (a local page), so no "connection refused" flash.
            if let Some(w) = app.get_webview_window("main") {
                apply_main_window_settings(&w);
                let _ = w.show();
            }

            let handle = app.handle().clone();
            let project_dir = project_dir.clone();
            thread::spawn(move || {
                // Progress reporter: push status into the loading window (window.gaProgress).
                let main_win = handle.get_webview_window("main");

                let report = |pct: i32, msg: &str| {
                    if let Some(w) = &main_win {
                        let js = format!(
                            "window.gaProgress && window.gaProgress({}, {})",
                            pct,
                            serde_json::to_string(msg).unwrap_or_else(|_| "\"\"".to_string())
                        );
                        let _ = w.eval(&js);
                    }
                };

                // First-run (self-contained bundle): prepare the embedded python env offline,
                // then start the bridge with the freshly created venv.
                if needs_prepare {
                    report(5, "start");
                    if let Err(e) = run_offline_prepare(&project_dir, &report) {
                        eprintln!("[tauri] first-run prepare failed: {}", e);
                        if let Some(sw) = handle.get_webview_window("setup") { let _ = sw.show(); }
                        if let Some(mw) = handle.get_webview_window("main") { let _ = mw.hide(); }
                        return;
                    }
                    report(95, "starting");
                    if !is_bridge_running() {
                        let (py_str, dir_str) = get_or_discover_config();
                        let dir = PathBuf::from(&dir_str);
                        let script = dir.join("frontends").join("desktop_bridge.py");
                        if script.exists() {
                            let mut cmd = Command::new(&py_str);
                            cmd.arg(&script).current_dir(&dir);
                            sanitize_bundle_env(&mut cmd);
                            #[cfg(windows)]
                            cmd.creation_flags(0x08000000);
                            if let Ok(child) = cmd.spawn() {
                                *BRIDGE_PROCESS.lock().unwrap() = Some(child);
                            }
                        }
                    }
                }

                // First run (prepare) and cold bridge start may take a while; allow up to 60s.
                let wait = if needs_prepare || spawned_bridge {
                    Duration::from_secs(60)
                } else {
                    Duration::from_secs(2)
                };
                let bridge_ready = wait_for_port(14168, wait);

                if bridge_ready {
                    // The bridge auto-starts conductor + scheduler itself (on_startup), so we do
                    // NOT probe their ports here: that would self-detect the bridge's own
                    // just-started extras and falsely report "ports busy".
                    if !wait_for_port(14168, Duration::from_secs(15)) {
                        eprintln!("[tauri] bridge not reachable before navigate");
                        if let Some(w) = &main_win {
                            let msg = "无法连接 bridge (127.0.0.1:14168)，请关闭程序后重试。";
                            let js = format!(
                                "alert({})",
                                serde_json::to_string(msg).unwrap_or_else(|_| "\"\"".to_string())
                            );
                            let _ = w.eval(&js);
                        }
                        return;
                    }
                    // Navigate to the bridge HTTP only after it is ready.
                    if let Some(w) = handle.get_webview_window("main") {
                        if let Ok(url) = tauri::Url::parse("http://127.0.0.1:14168/") {
                            let _ = w.navigate(url);
                        }
                        if dev_mode {
                            w.open_devtools();
                        } else {
                            // Disable F5/F12/Ctrl+R/right-click in production
                            let _ = w.eval(r#"
                                document.addEventListener('keydown', function(e) {
                                    if (e.key === 'F12' || e.key === 'F5' ||
                                        (e.ctrlKey && e.key === 'r') ||
                                        (e.ctrlKey && e.shiftKey && e.key === 'I')) {
                                        e.preventDefault();
                                    }
                                });
                                document.addEventListener('contextmenu', function(e) {
                                    e.preventDefault();
                                });
                            "#);
                        }
                        apply_main_window_settings(&w);
                        let _ = w.show();
                        let _ = w.set_focus();
                    }
                    if let Some(sw) = handle.get_webview_window("setup") { let _ = sw.hide(); }
                    // App is up and reachable: ask-once / self-heal the desktop shortcut.
                    // Runs last so it never blocks the loading/navigation path.
                    maybe_setup_shortcut();
                } else {
                    // Bridge never came up -> let the user fix paths in the setup window.
                    if let Some(sw) = handle.get_webview_window("setup") {
                        if dev_mode { sw.open_devtools(); }
                        let _ = sw.show();
                    }
                    if let Some(mw) = handle.get_webview_window("main") { let _ = mw.hide(); }
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let label = window.label();
                if label == "main" {
                    // Persistent backend: closing the window does NOT stop the bridge or its
                    // services, so relaunching attaches to the warm backend on 14168.
                    window.app_handle().exit(0);
                } else if label == "setup" {
                    // Setup closed -> exit if main is not visible
                    if let Some(main_win) = window.app_handle().get_webview_window("main") {
                        if !main_win.is_visible().unwrap_or(false) {
                            window.app_handle().exit(0);
                        }
                    } else {
                        window.app_handle().exit(0);
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn main_window_settings_accept_explicit_keys() {
        let settings = serde_json::json!({
            "window_width": 1024,
            "window_height": 720,
            "maximized": false
        });
        let serde_json::Value::Object(settings) = settings else { panic!("object expected"); };

        assert_eq!(main_window_settings_from(&settings), MainWindowSettings {
            width: Some(1024.0),
            height: Some(720.0),
            maximized: Some(false),
        });
    }

    #[test]
    fn main_window_settings_accept_legacy_size_keys() {
        let settings = serde_json::json!({
            "width": 900,
            "height": 640,
            "maximized": true
        });
        let serde_json::Value::Object(settings) = settings else { panic!("object expected"); };

        assert_eq!(main_window_settings_from(&settings), MainWindowSettings {
            width: Some(900.0),
            height: Some(640.0),
            maximized: Some(true),
        });
    }

    #[test]
    fn main_window_settings_ignore_invalid_values() {
        let settings = serde_json::json!({
            "window_width": 120,
            "window_height": "large",
            "maximized": "false"
        });
        let serde_json::Value::Object(settings) = settings else { panic!("object expected"); };

        assert_eq!(main_window_settings_from(&settings), MainWindowSettings {
            width: None,
            height: None,
            maximized: None,
        });
    }
}
