# GA Switch API Server

## 快速启动

### Windows
```bash
start_api_server.bat
```

### Linux/macOS
```bash
python api_server.py
```

服务器将在 `http://127.0.0.1:8765` 启动。

## API 端点

- `GET /api/health` - 健康检查
- `GET /api/snapshot` - 获取完整快照
- `GET /api/routes` - 路由列表
- `POST /api/routes` - 创建路由
- `PUT /api/routes/{id}` - 更新路由
- `DELETE /api/routes/{id}` - 删除路由
- `POST /api/routes/{id}/activate` - 激活路由
- `GET /api/providers` - Provider 列表
- `POST /api/providers` - 创建 Provider
- `PUT /api/providers/{id}` - 更新 Provider
- `DELETE /api/providers/{id}` - 删除 Provider
- `POST /api/providers/{id}/test` - 测试 Provider
- `GET /api/diagnostics` - 诊断事件
- `POST /api/reload` - 软重载
- `POST /api/import-legacy` - 导入配置

## 依赖安装

```bash
pip install -r requirements-api.txt
```

## 测试

```bash
curl http://127.0.0.1:8765/api/health
```
