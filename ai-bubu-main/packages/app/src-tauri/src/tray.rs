use tauri::{
    image::Image,
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{TrayIconBuilder, TrayIconId},
    App, LogicalPosition, Manager,
};

pub const TRAY_ID: &str = "main";

fn is_chinese() -> bool {
    if let Ok(lang) = std::env::var("LANG") {
        return lang.starts_with("zh");
    }
    #[cfg(target_os = "macos")]
    {
        let output = std::process::Command::new("defaults")
            .args(["read", "-g", "AppleLanguages"])
            .output();
        if let Ok(out) = output {
            let s = String::from_utf8_lossy(&out.stdout);
            if s.contains("zh") {
                return true;
            }
        }
    }
    false
}

pub fn setup_tray(app: &App) -> Result<(), Box<dyn std::error::Error>> {
    let zh = is_chinese();

    let show = MenuItem::with_id(
        app,
        "show",
        if zh { "显示桌宠" } else { "Show Pet" },
        true,
        None::<&str>,
    )?;
    let hide = MenuItem::with_id(
        app,
        "hide",
        if zh { "隐藏桌宠" } else { "Hide Pet" },
        true,
        None::<&str>,
    )?;
    let sep1 = PredefinedMenuItem::separator(app)?;
    let leaderboard = MenuItem::with_id(
        app,
        "leaderboard",
        if zh { "排行榜" } else { "Leaderboard" },
        true,
        None::<&str>,
    )?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(
        app,
        "quit",
        if zh { "退出" } else { "Quit" },
        true,
        None::<&str>,
    )?;

    let menu = Menu::with_items(app, &[&show, &hide, &sep1, &leaderboard, &sep2, &quit])?;

    let png_data = include_bytes!("../icons/icon.png");
    let icon = match image::load_from_memory(png_data) {
        Ok(img) => {
            let rgba = img.to_rgba8();
            let (w, h) = rgba.dimensions();
            Image::new_owned(rgba.into_raw(), w, h)
        }
        Err(e) => {
            eprintln!("tray: failed to decode icon.png, using 1x1 fallback: {}", e);
            Image::new_owned(vec![0, 0, 0, 0], 1, 1)
        }
    };

    let _tray = TrayIconBuilder::with_id(TRAY_ID)
        .icon(icon)
        .menu(&menu)
        .icon_as_template(false)
        .tooltip(if zh { "AI 步步" } else { "AIbubu" })
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(window) = app.get_webview_window("pet") {
                    let _ = window.show();
                }
            }
            "hide" => {
                if let Some(window) = app.get_webview_window("pet") {
                    let _ = window.hide();
                }
            }
            "leaderboard" => {
                toggle_social_window(app);
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;

    let app_handle = app.handle().clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_millis(800));
        position_pet_below_tray(&app_handle);
    });

    Ok(())
}

#[tauri::command]
pub fn update_tray_icon(
    app: tauri::AppHandle,
    rgba: Vec<u8>,
    width: u32,
    height: u32,
) -> Result<(), String> {
    let expected = (width as usize) * (height as usize) * 4;
    if rgba.len() != expected {
        return Err(format!(
            "rgba length {} != expected {}",
            rgba.len(),
            expected
        ));
    }
    let icon = Image::new_owned(rgba, width, height);
    let tray_id = TrayIconId::new(TRAY_ID);
    if let Some(tray) = app.tray_by_id(&tray_id) {
        tray.set_icon(Some(icon)).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn position_pet_below_tray(app: &tauri::AppHandle) {
    let tray_id = TrayIconId::new(TRAY_ID);
    let Some(tray) = app.tray_by_id(&tray_id) else {
        return;
    };
    let Some(window) = app.get_webview_window("pet") else {
        return;
    };
    let scale = window.scale_factor().unwrap_or(1.0);

    if let Ok(Some(rect)) = tray.rect() {
        let (px, py) = match rect.position {
            tauri::Position::Physical(p) => (p.x as f64 / scale, p.y as f64 / scale),
            tauri::Position::Logical(l) => (l.x, l.y),
        };
        let tray_h = match rect.size {
            tauri::Size::Physical(s) => s.height as f64 / scale,
            tauri::Size::Logical(l) => l.height,
        };
        let tray_w = match rect.size {
            tauri::Size::Physical(s) => s.width as f64 / scale,
            tauri::Size::Logical(l) => l.width,
        };

        if tray_h < 1.0 || py > 100.0 {
            return;
        }

        let win_w = window
            .outer_size()
            .map(|s| s.width as f64 / scale)
            .unwrap_or(80.0);
        let tray_center = px + tray_w / 2.0;
        let x = (tray_center - win_w / 2.0).max(0.0);
        let y = py + tray_h + 4.0;
        let _ = window.set_position(LogicalPosition::new(x, y));
    }
}

fn toggle_social_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("social") {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
            let _ = window.set_focus();
        }
    }
}
