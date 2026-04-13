use serde::Serialize;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use tauri::Manager;

include!(concat!(env!("OUT_DIR"), "/builtin_skins.rs"));

#[derive(Serialize)]
pub struct ImportResult {
    pub success: bool,
    pub skin_id: String,
    pub message: String,
}

#[derive(Serialize, Clone)]
pub struct SkinEntry {
    pub id: String,
    pub builtin: bool,
}

fn get_skins_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let project_root = manifest_dir.parent().unwrap_or(manifest_dir);
        return Ok(project_root.join("public").join("skins"));
    }

    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to get app data dir: {}", e))?;
    Ok(data_dir.join("skins"))
}

/// Scan a directory for subdirectories containing `skin.json`.
fn scan_skin_ids(dir: &Path) -> Vec<String> {
    let mut ids = Vec::new();
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() && path.join("skin.json").exists() {
                if let Some(name) = entry.file_name().to_str() {
                    ids.push(name.to_string());
                }
            }
        }
    }
    ids.sort();
    ids
}

#[tauri::command]
pub async fn list_skins(app: tauri::AppHandle) -> Vec<SkinEntry> {
    let mut result: Vec<SkinEntry> = BUILTIN_SKIN_IDS
        .iter()
        .map(|id| SkinEntry {
            id: id.to_string(),
            builtin: true,
        })
        .collect();

    if let Ok(skins_dir) = get_skins_dir(&app) {
        for id in scan_skin_ids(&skins_dir) {
            if !BUILTIN_SKIN_IDS.contains(&id.as_str()) {
                result.push(SkinEntry { id, builtin: false });
            }
        }
    }

    result
}

fn sanitize_skin_id(raw: &str) -> Result<String, String> {
    let id = raw.to_lowercase().replace(' ', "-");
    if id.is_empty() {
        return Err("角色 ID 不能为空".to_string());
    }
    if !id
        .chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-' || c == '_')
    {
        return Err(format!(
            "角色 ID 仅允许小写字母、数字、- 和 _，当前: {}",
            id
        ));
    }
    if id.starts_with('-') || id.starts_with('_') {
        return Err(format!("角色 ID 不能以 - 或 _ 开头: {}", id));
    }
    Ok(id)
}

fn validate_skin_dir(dir: &Path) -> Result<serde_json::Value, String> {
    let skin_json_path = dir.join("skin.json");
    if !skin_json_path.exists() {
        return Err("缺少 skin.json 文件".to_string());
    }

    let content =
        fs::read_to_string(&skin_json_path).map_err(|e| format!("无法读取 skin.json: {}", e))?;

    let manifest: serde_json::Value =
        serde_json::from_str(&content).map_err(|e| format!("skin.json 格式错误: {}", e))?;

    let required_fields = ["name", "author", "format", "size", "animations"];
    for field in &required_fields {
        if manifest.get(field).is_none() {
            return Err(format!("skin.json 缺少必需字段: {}", field));
        }
    }

    let animations = manifest
        .get("animations")
        .and_then(|v| v.as_object())
        .ok_or("animations 字段格式无效")?;

    if animations.is_empty() {
        return Err("至少需要定义一个动画状态".to_string());
    }

    for (state, anim) in animations {
        let file = anim
            .get("file")
            .and_then(|v| v.as_str())
            .ok_or(format!("动画 {} 缺少 file 字段", state))?;

        if file.contains("..") {
            return Err(format!("动画 {} 的文件路径不合法: {}", state, file));
        }

        let file_path = dir.join(file);
        let canonical = file_path
            .canonicalize()
            .map_err(|_| format!("动画 {} 引用的文件不存在: {}", state, file))?;
        let dir_canonical = dir
            .canonicalize()
            .map_err(|e| format!("路径解析失败: {}", e))?;
        if !canonical.starts_with(&dir_canonical) {
            return Err(format!("动画 {} 的文件路径越界: {}", state, file));
        }
    }

    let has_pet_avatar = dir.join("pet.gif").exists() || dir.join("pet.png").exists();
    if !has_pet_avatar {
        return Err("缺少 pet.png 或 pet.gif 角色头像文件".to_string());
    }

    Ok(manifest)
}

#[tauri::command]
pub async fn import_skin_from_dir(app: tauri::AppHandle, source_dir: String) -> ImportResult {
    let source = Path::new(&source_dir);
    if !source.is_dir() {
        return ImportResult {
            success: false,
            skin_id: String::new(),
            message: "指定的路径不是文件夹".to_string(),
        };
    }

    let manifest = match validate_skin_dir(source) {
        Ok(m) => m,
        Err(msg) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: msg,
            }
        }
    };

    let raw_name = source
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown");

    let skin_id = match sanitize_skin_id(raw_name) {
        Ok(id) => id,
        Err(msg) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: msg,
            }
        }
    };

    let skins_dir = match get_skins_dir(&app) {
        Ok(d) => d,
        Err(msg) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: msg,
            }
        }
    };

    let target_dir = skins_dir.join(&skin_id);
    if target_dir.exists() {
        return ImportResult {
            success: false,
            skin_id: skin_id.clone(),
            message: format!("角色 {} 已存在", skin_id),
        };
    }

    if let Err(e) = fs::create_dir_all(&target_dir) {
        return ImportResult {
            success: false,
            skin_id: String::new(),
            message: format!("创建目录失败: {}", e),
        };
    }

    if let Err(e) = copy_dir_contents(source, &target_dir) {
        let _ = fs::remove_dir_all(&target_dir);
        return ImportResult {
            success: false,
            skin_id: String::new(),
            message: format!("复制文件失败: {}", e),
        };
    }

    let name = manifest
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or(&skin_id);

    ImportResult {
        success: true,
        skin_id: skin_id.clone(),
        message: format!("成功导入角色: {}", name),
    }
}

#[tauri::command]
pub async fn import_skin_from_zip(app: tauri::AppHandle, zip_path: String) -> ImportResult {
    let zip_file = Path::new(&zip_path);
    if !zip_file.is_file() {
        return ImportResult {
            success: false,
            skin_id: String::new(),
            message: "指定的文件不存在".to_string(),
        };
    }

    let tmp_dir = match tempfile::tempdir() {
        Ok(d) => d,
        Err(e) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: format!("创建临时目录失败: {}", e),
            }
        }
    };

    if let Err(e) = extract_zip(zip_file, tmp_dir.path()) {
        return ImportResult {
            success: false,
            skin_id: String::new(),
            message: format!("解压 ZIP 失败: {}", e),
        };
    }

    let skin_root = match find_skin_root(tmp_dir.path()) {
        Ok(p) => p,
        Err(msg) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: msg,
            }
        }
    };

    let manifest = match validate_skin_dir(&skin_root) {
        Ok(m) => m,
        Err(msg) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: msg,
            }
        }
    };

    let raw_name = skin_root
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("unknown");

    let skin_id = match sanitize_skin_id(raw_name) {
        Ok(id) => id,
        Err(msg) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: msg,
            }
        }
    };

    let skins_dir = match get_skins_dir(&app) {
        Ok(d) => d,
        Err(msg) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: msg,
            }
        }
    };

    let target_dir = skins_dir.join(&skin_id);
    if target_dir.exists() {
        return ImportResult {
            success: false,
            skin_id: skin_id.clone(),
            message: format!("角色 {} 已存在", skin_id),
        };
    }

    if let Err(e) = fs::create_dir_all(&target_dir) {
        return ImportResult {
            success: false,
            skin_id: String::new(),
            message: format!("创建目录失败: {}", e),
        };
    }

    if let Err(e) = copy_dir_contents(&skin_root, &target_dir) {
        let _ = fs::remove_dir_all(&target_dir);
        return ImportResult {
            success: false,
            skin_id: String::new(),
            message: format!("复制文件失败: {}", e),
        };
    }

    let name = manifest
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or(&skin_id);

    ImportResult {
        success: true,
        skin_id: skin_id.clone(),
        message: format!("成功导入角色: {}", name),
    }
}

const MAX_ZIP_FILES: usize = 200;
const MAX_ZIP_TOTAL_BYTES: u64 = 50 * 1024 * 1024; // 50 MB
const MAX_ZIP_SINGLE_FILE_BYTES: u64 = 20 * 1024 * 1024; // 20 MB

fn extract_zip(zip_path: &Path, dest: &Path) -> Result<(), String> {
    let file = fs::File::open(zip_path).map_err(|e| format!("无法打开 ZIP: {}", e))?;
    let mut archive =
        zip::ZipArchive::new(io::BufReader::new(file)).map_err(|e| format!("无效的 ZIP: {}", e))?;

    if archive.len() > MAX_ZIP_FILES {
        return Err(format!(
            "ZIP 包含过多条目（{}），上限为 {}",
            archive.len(),
            MAX_ZIP_FILES
        ));
    }

    let mut total_bytes: u64 = 0;

    for i in 0..archive.len() {
        let mut entry = archive
            .by_index(i)
            .map_err(|e| format!("读取 ZIP 条目失败: {}", e))?;

        if entry.size() > MAX_ZIP_SINGLE_FILE_BYTES {
            return Err(format!(
                "ZIP 内单文件过大（{} 字节），上限为 {} MB",
                entry.size(),
                MAX_ZIP_SINGLE_FILE_BYTES / 1024 / 1024
            ));
        }

        total_bytes += entry.size();
        if total_bytes > MAX_ZIP_TOTAL_BYTES {
            return Err(format!(
                "ZIP 解压总大小超过上限 {} MB",
                MAX_ZIP_TOTAL_BYTES / 1024 / 1024
            ));
        }

        let name = match entry.enclosed_name() {
            Some(n) => n.to_owned(),
            None => continue,
        };

        let out_path = dest.join(&name);

        if entry.is_dir() {
            fs::create_dir_all(&out_path).map_err(|e| format!("创建目录失败: {}", e))?;
        } else {
            if let Some(parent) = out_path.parent() {
                fs::create_dir_all(parent).map_err(|e| format!("创建目录失败: {}", e))?;
            }
            let mut outfile =
                fs::File::create(&out_path).map_err(|e| format!("创建文件失败: {}", e))?;
            io::copy(&mut entry, &mut outfile).map_err(|e| format!("写入文件失败: {}", e))?;
        }
    }
    Ok(())
}

/// Find the directory containing skin.json within extracted ZIP contents.
/// Handles both flat ZIPs (skin.json at root) and nested ZIPs (skin-folder/skin.json).
/// Returns an error if multiple candidate directories are found.
fn find_skin_root(extracted: &Path) -> Result<PathBuf, String> {
    if extracted.join("skin.json").exists() {
        return Ok(extracted.to_path_buf());
    }

    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(entries) = fs::read_dir(extracted) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() && path.join("skin.json").exists() {
                candidates.push(path);
            }
        }
    }

    match candidates.len() {
        0 => Ok(extracted.to_path_buf()),
        1 => Ok(candidates.into_iter().next().unwrap()),
        n => Err(format!("ZIP 内包含 {} 个皮肤目录，仅支持导入单个角色", n)),
    }
}

#[tauri::command]
pub async fn remove_skin(app: tauri::AppHandle, skin_id: String) -> ImportResult {
    if skin_id.contains("..") || skin_id.contains('/') || skin_id.contains('\\') {
        return ImportResult {
            success: false,
            skin_id: skin_id.clone(),
            message: "角色 ID 不合法".to_string(),
        };
    }

    if BUILTIN_SKIN_IDS.contains(&skin_id.as_str()) {
        return ImportResult {
            success: false,
            skin_id: skin_id.clone(),
            message: "内置角色不能移除".to_string(),
        };
    }

    let skins_dir = match get_skins_dir(&app) {
        Ok(d) => d,
        Err(msg) => {
            return ImportResult {
                success: false,
                skin_id: String::new(),
                message: msg,
            }
        }
    };

    let target_dir = skins_dir.join(&skin_id);
    if !target_dir.exists() {
        return ImportResult {
            success: false,
            skin_id: skin_id.clone(),
            message: format!("角色 {} 不存在", skin_id),
        };
    }

    if let Err(e) = fs::remove_dir_all(&target_dir) {
        return ImportResult {
            success: false,
            skin_id: skin_id.clone(),
            message: format!("移除失败: {}", e),
        };
    }

    ImportResult {
        success: true,
        skin_id: skin_id.clone(),
        message: format!("已移除角色: {}", skin_id),
    }
}

fn copy_dir_contents(src: &Path, dst: &Path) -> Result<(), std::io::Error> {
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let meta = entry.metadata()?;
        let dest_path = dst.join(entry.file_name());

        if meta.file_type().is_symlink() {
            continue;
        }

        if meta.is_dir() {
            fs::create_dir_all(&dest_path)?;
            copy_dir_contents(&entry.path(), &dest_path)?;
        } else if meta.is_file() {
            fs::copy(entry.path(), &dest_path)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write_valid_skin(dir: &Path) {
        fs::write(dir.join("idle.png"), b"fake png").unwrap();
        fs::write(dir.join("pet.png"), b"fake avatar").unwrap();
        fs::write(
            dir.join("skin.json"),
            r#"{
                "name": "Test Skin",
                "author": "Test Author",
                "format": "sprite",
                "size": { "width": 48, "height": 48 },
                "animations": {
                    "idle": { "file": "idle.png", "sprite": { "frameWidth": 48, "frameHeight": 48, "frameCount": 4, "columns": 4, "fps": 8 } }
                }
            }"#,
        )
        .unwrap();
    }

    #[test]
    fn validate_skin_dir_ok() {
        let tmp = TempDir::new().unwrap();
        write_valid_skin(tmp.path());
        let result = validate_skin_dir(tmp.path());
        assert!(result.is_ok());
        let manifest = result.unwrap();
        assert_eq!(manifest["name"], "Test Skin");
    }

    #[test]
    fn validate_skin_dir_missing_skin_json() {
        let tmp = TempDir::new().unwrap();
        let err = validate_skin_dir(tmp.path()).unwrap_err();
        assert!(err.contains("skin.json"));
    }

    #[test]
    fn validate_skin_dir_invalid_json() {
        let tmp = TempDir::new().unwrap();
        fs::write(tmp.path().join("skin.json"), "not json!!!").unwrap();
        let err = validate_skin_dir(tmp.path()).unwrap_err();
        assert!(err.contains("格式错误"));
    }

    #[test]
    fn validate_skin_dir_missing_required_field() {
        let tmp = TempDir::new().unwrap();
        fs::write(tmp.path().join("skin.json"), r#"{"name":"X"}"#).unwrap();
        let err = validate_skin_dir(tmp.path()).unwrap_err();
        assert!(err.contains("缺少必需字段"));
    }

    #[test]
    fn validate_skin_dir_empty_animations() {
        let tmp = TempDir::new().unwrap();
        fs::write(
            tmp.path().join("skin.json"),
            r#"{"name":"X","author":"A","format":"sprite","size":{"width":48,"height":48},"animations":{}}"#,
        )
        .unwrap();
        let err = validate_skin_dir(tmp.path()).unwrap_err();
        assert!(err.contains("至少需要定义一个动画状态"));
    }

    #[test]
    fn validate_skin_dir_missing_animation_file() {
        let tmp = TempDir::new().unwrap();
        fs::write(
            tmp.path().join("skin.json"),
            r#"{"name":"X","author":"A","format":"sprite","size":{"width":48,"height":48},"animations":{"idle":{"file":"missing.png"}}}"#,
        )
        .unwrap();
        let err = validate_skin_dir(tmp.path()).unwrap_err();
        assert!(err.contains("不存在"));
    }

    #[test]
    fn validate_skin_dir_missing_file_field() {
        let tmp = TempDir::new().unwrap();
        fs::write(
            tmp.path().join("skin.json"),
            r#"{"name":"X","author":"A","format":"sprite","size":{"width":48,"height":48},"animations":{"idle":{}}}"#,
        )
        .unwrap();
        let err = validate_skin_dir(tmp.path()).unwrap_err();
        assert!(err.contains("缺少 file 字段"));
    }

    #[test]
    fn copy_dir_contents_copies_files_and_subdirs() {
        let src = TempDir::new().unwrap();
        let dst = TempDir::new().unwrap();

        fs::write(src.path().join("a.txt"), "hello").unwrap();
        fs::create_dir(src.path().join("sub")).unwrap();
        fs::write(src.path().join("sub/b.txt"), "world").unwrap();

        copy_dir_contents(src.path(), dst.path()).unwrap();

        assert_eq!(
            fs::read_to_string(dst.path().join("a.txt")).unwrap(),
            "hello"
        );
        assert_eq!(
            fs::read_to_string(dst.path().join("sub/b.txt")).unwrap(),
            "world"
        );
    }

    #[test]
    fn builtin_skin_ids_contains_expected() {
        assert!(BUILTIN_SKIN_IDS.contains(&"vita"));
        assert!(BUILTIN_SKIN_IDS.contains(&"doux"));
        assert!(BUILTIN_SKIN_IDS.contains(&"line"));
        assert!(!BUILTIN_SKIN_IDS.contains(&"custom-uploaded"));
    }

    #[test]
    fn scan_skin_ids_finds_valid_dirs() {
        let tmp = TempDir::new().unwrap();

        let skin_a = tmp.path().join("alpha");
        fs::create_dir(&skin_a).unwrap();
        fs::write(skin_a.join("skin.json"), "{}").unwrap();

        let skin_b = tmp.path().join("beta");
        fs::create_dir(&skin_b).unwrap();
        fs::write(skin_b.join("skin.json"), "{}").unwrap();

        // Directory without skin.json should be ignored
        let no_skin = tmp.path().join("empty");
        fs::create_dir(&no_skin).unwrap();

        // Regular file should be ignored
        fs::write(tmp.path().join("readme.txt"), "hi").unwrap();

        let ids = scan_skin_ids(tmp.path());
        assert_eq!(ids, vec!["alpha", "beta"]);
    }

    #[test]
    fn scan_skin_ids_empty_dir() {
        let tmp = TempDir::new().unwrap();
        let ids = scan_skin_ids(tmp.path());
        assert!(ids.is_empty());
    }

    #[test]
    fn scan_skin_ids_nonexistent_dir() {
        let ids = scan_skin_ids(Path::new("/nonexistent/path"));
        assert!(ids.is_empty());
    }
}
