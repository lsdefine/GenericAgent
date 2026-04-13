# AI 步步 — 角色制作指南

本文件夹是一个完整的角色皮肤示例（Vita），可直接导入 AI 步步使用。

## 文件结构

```
my-skin/
├── skin.json       ← 必需：角色配置文件
├── pet.png         ← 必需：角色头像（或 pet.gif）
├── skin.png        ← 精灵图（单文件方案）
└── idle.png        ← 或按状态分文件（idle.png, walk.png, run.png, sprint.png）
```

### pet.png / pet.gif

角色头像，用于排行榜、角色选择等场景。建议：

- 尺寸 96×96 像素
- 透明背景 PNG
- 像素风格建议用最近邻缩放

## skin.json 格式

```json
{
  "name": "Vita",
  "version": "1.0.0",
  "author": "arks",
  "source": "https://arks.itch.io/dino-characters",
  "license": "CC0",
  "description": "像素风小恐龙 Vita",
  "style": "pixel",
  "format": "sprite",
  "size": { "width": 48, "height": 48 },
  "animations": {
    "idle": {
      "file": "skin.png",
      "loop": true,
      "sprite": {
        "frameWidth": 24,
        "frameHeight": 24,
        "frameCount": 4,
        "columns": 24,
        "fps": 6,
        "startFrame": 0
      }
    },
    "walk": { "..." },
    "run": { "..." },
    "sprint": { "..." }
  }
}
```

### 必需字段

| 字段         | 类型   | 说明                                                 |
| ------------ | ------ | ---------------------------------------------------- |
| `name`       | string | 角色显示名称                                         |
| `author`     | string | 角色作者名称                                         |
| `format`     | string | 固定为 `sprite`                                      |
| `size`       | object | 渲染尺寸 `{ width, height }`，决定角色在屏幕上的大小 |
| `animations` | object | 至少包含 `idle` 状态                                 |

### 可选字段

| 字段      | 类型   | 说明                                   |
| --------- | ------ | -------------------------------------- |
| `source`  | string | 素材来源 URL，点击作者名即可跳转       |
| `license` | string | 素材授权协议，如 `CC0`、`CC-BY 4.0` 等 |

### sprite 字段

| 字段          | 说明                                      |
| ------------- | ----------------------------------------- |
| `frameWidth`  | 精灵图中单帧的像素宽度                    |
| `frameHeight` | 精灵图中单帧的像素高度                    |
| `frameCount`  | 该状态的帧数                              |
| `columns`     | 精灵图的总列数（整张图宽度 ÷ frameWidth） |
| `fps`         | 播放帧率                                  |
| `startFrame`  | 该状态在精灵图中的起始帧索引（从 0 开始） |

## 四种运动状态

| 状态 | 键名     | 触发条件      | 建议 FPS |
| ---- | -------- | ------------- | -------- |
| 空闲 | `idle`   | AI 工具未使用 | 4-6      |
| 散步 | `walk`   | 轻度使用      | 6-8      |
| 跑步 | `run`    | 中度使用      | 8-12     |
| 飞跑 | `sprint` | 高强度使用    | 12-16    |

如果某个状态缺失，会自动回退（sprint → run → walk → idle）。

## 两种精灵图方案

### 方案 A：单文件（本示例）

所有动画帧排列在一张 `skin.png` 中，通过 `startFrame` 区分状态。适合帧尺寸相同的角色。

### 方案 B：多文件

每个状态使用独立 PNG 文件，`file` 字段指向不同文件：

```json
{
  "idle": { "file": "idle.png", "sprite": { "startFrame": 0, "..." } },
  "walk": { "file": "walk.png", "sprite": { "startFrame": 0, "..." } }
}
```

适合不同状态帧尺寸不同的角色。

## 从散帧图片构建

如果你有每帧独立的图片，可以用项目自带脚本合并：

```bash
# 准备目录
my-skin/
├── idle/     ← 站立帧图片
├── walk/     ← 散步帧图片
├── run/      ← 跑步帧图片
└── sprint/   ← 飞跑帧图片

# 运行构建
python3 scripts/build-skin.py my-skin/ --scale 64 --name "我的角色"
```

脚本会自动生成 `skin.png`、`skin.json` 和 `pet.png`。

## 导入

1. 准备好角色文件夹（skin.json + 精灵图 + pet.png）
2. 打开 AI 步步 → 角色标签页
3. 点击「导入文件夹」
4. 选择文件夹，自动校验并导入
