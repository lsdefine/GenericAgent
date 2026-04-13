# AIbubu 品牌命名规范

## 产品名称

| 场景               | 名称             |
| ------------------ | ---------------- |
| 中文品牌名         | AI 步步          |
| 英文品牌名         | AIbubu           |
| 打包/安装名        | AIbubu           |
| npm package (root) | aibubu           |
| npm package (app)  | aibubu           |
| npm package (site) | aibubu-site      |
| Rust crate         | aibubu           |
| Tauri productName  | AIbubu           |
| macOS .app 名称    | AIbubu.app       |
| 域名               | aibubu.app       |
| GitHub repo        | funAgent/ai-bubu |

## localStorage key 前缀

所有 localStorage key 统一使用 `aibubu-` 前缀：

- `aibubu-settings`
- `aibubu-skin`
- `aibubu-theme`
- `aibubu-lang`
- `aibubu-active-tab`

## i18n brand key

- zh: `AI 步步`
- en: `AIbubu`

## 添加新皮肤

1. 在 `packages/app/public/skins/` 下创建目录（如 `my-skin/`）
2. 添加 `skin.json`（必填字段：name, version, author, style, format, size, animations）
3. 添加 `pet.png`（精灵图）
4. 运行 `pnpm validate:skins` 校验一致性

皮肤放入目录即自动发现，无需手动注册。
