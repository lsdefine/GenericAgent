use std::fs;
use std::io::Write;
use std::path::Path;

fn main() {
    let skins_dir = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("public")
        .join("skins");

    let order_path = skins_dir.join("order.json");
    let ids: Vec<String> = if order_path.exists() {
        let raw = fs::read_to_string(&order_path).expect("failed to read order.json");
        let parsed: Vec<String> =
            serde_json::from_str(&raw).expect("order.json must be a JSON string array");
        for id in &parsed {
            let dir = skins_dir.join(id);
            assert!(
                dir.is_dir() && dir.join("skin.json").exists(),
                "order.json references '{}' but {}/skin.json not found",
                id,
                dir.display()
            );
        }
        parsed
    } else {
        let mut scanned: Vec<String> = Vec::new();
        if let Ok(entries) = fs::read_dir(&skins_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() && path.join("skin.json").exists() {
                    if let Some(name) = entry.file_name().to_str() {
                        scanned.push(name.to_string());
                    }
                }
            }
        }
        scanned.sort();
        scanned
    };

    let out_dir = std::env::var("OUT_DIR").unwrap();
    let dest = Path::new(&out_dir).join("builtin_skins.rs");
    let mut f = fs::File::create(dest).unwrap();
    write!(
        f,
        "const BUILTIN_SKIN_IDS: &[&str] = &[{}];",
        ids.iter()
            .map(|id| format!("\"{}\"", id))
            .collect::<Vec<_>>()
            .join(", ")
    )
    .unwrap();

    println!("cargo:rerun-if-changed=../public/skins");

    tauri_build::build()
}
