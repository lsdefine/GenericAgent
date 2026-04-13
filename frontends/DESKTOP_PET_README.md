# Desktop Pet Skin System

## 快速开始

运行桌面宠物：
```bash
python3 desktop_pet_v2.pyw
```

## 功能特性

### 1. 多皮肤支持
- 自动发现 `skins/` 目录下的所有皮肤
- 右键菜单切换皮肤
- 支持 sprite sheet 和 GIF 两种格式

### 2. 多动画状态
- **idle** - 待机动画
- **walk** - 行走动画
- **run** - 跑步动画
- **sprint** - 冲刺动画

右键菜单可切换动画状态

### 3. 交互功能
- **单击** - 拖动宠物
- **双击** - 关闭程序
- **右键** - 打开菜单（切换皮肤/动画）

### 4. HTTP 远程控制
```bash
# 显示消息
curl "http://127.0.0.1:51983/?msg=Hello"

# 切换动画状态
curl "http://127.0.0.1:51983/?state=run"

# POST 消息
curl -X POST -d "任务完成" http://127.0.0.1:51983/
```

## 添加新皮肤

### 目录结构
```
skins/
└── your-skin-name/
    ├── skin.json       # 配置文件（必需）
    ├── idle.png        # 动画资源
    ├── walk.png
    ├── run.png
    └── sprint.png
```

### skin.json 配置示例

#### Sprite Sheet 格式（推荐）
```json
{
  "name": "My Pet",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "描述",
  "format": "sprite",
  "animations": {
    "idle": {
      "file": "idle.png",
      "loop": true,
      "sprite": {
        "frameWidth": 44,
        "frameHeight": 31,
        "frameCount": 6,
        "columns": 6,
        "fps": 6,
        "startFrame": 0
      }
    },
    "walk": {
      "file": "walk.png",
      "loop": true,
      "sprite": {
        "frameWidth": 65,
        "frameHeight": 32,
        "frameCount": 8,
        "columns": 8,
        "fps": 8,
        "startFrame": 0
      }
    }
  }
}
```

#### GIF 格式
```json
{
  "name": "My Pet",
  "format": "gif",
  "animations": {
    "idle": {
      "file": "idle.gif",
      "loop": true
    },
    "walk": {
      "file": "walk.gif",
      "loop": true
    }
  }
}
```

### 配置说明

- **frameWidth/frameHeight**: 单帧尺寸（像素）
- **frameCount**: 帧数
- **columns**: sprite sheet 的列数
- **fps**: 播放帧率
- **startFrame**: 起始帧索引（从 0 开始）

### Sprite Sheet 布局

```
+-------+-------+-------+-------+
| 帧0   | 帧1   | 帧2   | 帧3   |  ← 第一行
+-------+-------+-------+-------+
| 帧4   | 帧5   | 帧6   | 帧7   |  ← 第二行
+-------+-------+-------+-------+
```

如果 `columns=4, startFrame=2, frameCount=3`，则读取：帧2, 帧3, 帧4

## 已包含的皮肤

1. **Glube** - 像素风小怪兽（多文件 sprite）
2. **Vita** - 像素风小恐龙（单文件 sprite）
3. **Doux** - 像素风小恐龙（单文件 sprite）

## 从 ai-bubu 导入更多皮肤

ai-bubu 项目包含更多皮肤资源，可以直接复制：

```bash
# 复制皮肤
cp -r ai-bubu-main/packages/app/public/skins/boy frontends/skins/
cp -r ai-bubu-main/packages/app/public/skins/dinosaur frontends/skins/
cp -r ai-bubu-main/packages/app/public/skins/line frontends/skins/
cp -r ai-bubu-main/packages/app/public/skins/mort frontends/skins/
cp -r ai-bubu-main/packages/app/public/skins/tard frontends/skins/
```

## 与 stapp.py 集成

在 `stapp.py` 中点击"🐱 桌面宠物"按钮会自动启动桌面宠物，并在每个 turn 结束时发送通知。

## 故障排查

### 皮肤不显示
1. 检查 `skin.json` 格式是否正确
2. 确认图片文件存在
3. 检查 sprite 配置参数是否匹配图片尺寸

### 动画不流畅
- 调整 `fps` 参数
- 检查帧数是否正确

### 透明背景问题
- 确保 PNG 文件包含 alpha 通道
- 使用 RGBA 模式的图片

## 技术细节

- 基于 Tkinter + PIL/Pillow
- 支持透明背景（#01FF01 色键）
- 窗口置顶、无边框
- HTTP 服务器端口：51983
