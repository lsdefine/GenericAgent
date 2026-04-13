mod monitor;
mod skin_import;
mod social;
mod steps;
mod tray;

use std::sync::{Arc, Mutex};
use tauri::Manager;

#[cfg(target_os = "macos")]
mod nspanel {
    use tauri::Manager;
    use tauri_nspanel::objc2::runtime::NSObjectProtocol;
    use tauri_nspanel::objc2::{ClassType, Message};

    tauri_nspanel::panel!(PetPanel {
        config: {
            can_become_key_window: true
        }
    });
}
#[cfg(target_os = "macos")]
use nspanel::PetPanel;

#[cfg(target_os = "macos")]
fn apply_fullscreen_overlay(app: &tauri::AppHandle, visible: bool) {
    use tauri_nspanel::{CollectionBehavior, ManagerExt, PanelLevel, StyleMask};

    match app.get_webview_panel("pet") {
        Ok(panel) => {
            if visible {
                panel.set_collection_behavior(
                    CollectionBehavior::new()
                        .can_join_all_spaces()
                        .full_screen_auxiliary()
                        .transient()
                        .ignores_cycle()
                        .value(),
                );
                panel.set_level(PanelLevel::Status.value());
                panel.set_hides_on_deactivate(false);
                panel.set_style_mask(StyleMask::empty().nonactivating_panel().value());
                eprintln!("fullscreen-overlay: enabled");
            } else {
                panel.set_collection_behavior(CollectionBehavior::new().value());
                panel.set_level(PanelLevel::Floating.value());
                panel.set_style_mask(StyleMask::empty().value());
                eprintln!("fullscreen-overlay: disabled");
            }
        }
        Err(e) => eprintln!("fullscreen-overlay: panel not found: {e:?}"),
    }
}

/// Toggle pet window fullscreen overlay from frontend.
/// Synchronous so Tauri dispatches on the main thread (AppKit requirement).
#[tauri::command]
fn set_show_over_fullscreen(app: tauri::AppHandle, visible: bool) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    apply_fullscreen_overlay(&app, visible);

    #[cfg(not(target_os = "macos"))]
    {
        let _ = (app, visible);
    }

    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init());

    #[cfg(target_os = "macos")]
    let builder = builder.plugin(tauri_nspanel::init());

    builder
        .setup(|app| {
            tray::setup_tray(app)?;

            let providers_dir = if cfg!(debug_assertions) {
                let manifest_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
                manifest_dir
                    .parent()
                    .unwrap_or(manifest_dir)
                    .join("providers")
            } else {
                let resource_dir = app.path().resource_dir().map_err(|e| {
                    eprintln!("monitor: failed to locate resource directory: {}", e);
                    e
                })?;
                resource_dir.join("providers")
            };

            let engine = Arc::new(monitor::MonitorEngine::new(providers_dir));
            app.manage(engine.clone());
            let handle = app.handle().clone();
            let runner = monitor::start_monitor(handle, engine, 3000);
            app.manage(Mutex::new(runner));

            #[cfg(target_os = "macos")]
            {
                use tauri_nspanel::WebviewWindowExt;

                if let Some(pet_window) = app.get_webview_window("pet") {
                    match pet_window.to_panel::<PetPanel>() {
                        Ok(_) => {
                            apply_fullscreen_overlay(app.handle(), true);
                        }
                        Err(e) => {
                            eprintln!("fullscreen-overlay: failed to convert to panel: {e:?}")
                        }
                    }
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            steps::save_steps,
            steps::load_steps,
            steps::load_step_history,
            social::social_start,
            social::social_stop,
            social::social_broadcast,
            social::social_get_peers,
            skin_import::list_skins,
            skin_import::import_skin_from_dir,
            skin_import::import_skin_from_zip,
            skin_import::remove_skin,
            tray::update_tray_icon,
            set_show_over_fullscreen,
        ])
        .build(tauri::generate_context!())
        .expect("error while building aibubu")
        .run(|app, event| {
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = event {
                if let Some(window) = app.get_webview_window("social") {
                    if !window.is_visible().unwrap_or(false) {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
            let _ = event;
        });
}
