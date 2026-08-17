# 配置设备互联环境

触发词：`帮我配置设备互联`。

目标：把当前电脑准备为可与手机 GA 安全配对和连接的设备。

> 当前仅适配 Windows 系统；macOS 和 Linux 暂不支持本配置流程，发现操作系统不适配时停止配置并提醒用户，并告诉用户后续测试开发完善后会上线。

实际配置顺序：

```text
安装 GAnet 插件
→ 确认 GA 登录
→ 准备 GAnet 网络组件与 OpenSSH
→ 配置 SSH 与独立授权文件
→ 登记电脑并加入 GAnet
→ 复检
→ 在用户中心配对手机
```

完成标准：插件可导入，且基础环境、GAnet 控制面、SSH 服务、设备访问四项检查均通过。

## 1. 安装 GAnet 插件

GA 根目录是本 SOP 所在 `memory/` 目录的上一级，即包含 `agent_loop.py`、`frontends/` 和 `plugins/` 的目录。先把 GA 根目录加入 `sys.path`，尝试导入：

```python
from plugins import ganet
```

导入成功则保留当前插件，直接进入第 2 节。插件不存在时，从以下固定地址读取发布清单：

```text
https://ganet.gaagent.ai/releases/plugin/manifest.json
```

核对清单中的文件大小和 SHA-256。验证通过后解压得到 ganet ，并放到到目录 `plugins` 下。

安装完成后重新导入并确认：

```python
from plugins.ganet import open_user_center
```

然后请用户在当前本地 UI 输入 `/user`。`/user` 会打开仅监听本机回环地址的 GA 用户中心；若当前 UI 提示组件尚未安装，则重新检查安装目录和导入错误，不要把插件源码放回 `frontends/`。插件目录是下载产物，不加入 Git。

## 2. 确认登录并检查环境

正式 GA 登录为后续电脑登记和 GAnet 入网提供身份。登录接口位于 `plugins/ganet/device_connection/auth.py`。

```python
from plugins.ganet.device_connection import auth
identity = auth.current_identity()
logged_in = bool(auth.get_token() and identity and identity.get("valid"))
```

未登录时，请用户在当前电脑 GA 执行 `/user` 并完成登录；已登录时继续。

环境检查由 `plugins/ganet/device_connection/network.py` 的 `check_env()` 提供。

GA 根目录就是本 SOP 所在 `memory/` 目录的上一级，即包含 `agent_loop.py`、`frontends/` 和 `plugins/` 的目录。`code_run` 的 python 脚本默认导入不到该目录下的项目模块，导入 `plugins.ganet` 前先自行把 GA 根目录加入 `sys.path`。

这一步只读，检查：

- GAnet 网络组件是否已安装、运行、加入 GAnet 并监听设备连接；
- GAnet 网络组件版本状态：`current`、`available`、`required` 或 `unknown`；
- OpenSSH 服务、SFTP、配置端口和监听状态；
- GAnet 独立授权文件与 ACL；
- 二维码和电脑截图所需的当前 GA 组件。

版本状态只影响“基础环境”节点的呈现：`available` 为黄色提示，表示当前连接仍可用；`required` 与组件缺失、无法响应一样进入修复流程；`unknown` 不影响当前可用链路。其他状态从 `chain` 和 `checks` 汇总实际缺失项。

组件本机状态和版本状态由：

```python
from plugins.ganet.device_connection import sidecar_manager
component = sidecar_manager.inspect()
```

读取。`inspect()` 返回 `installed`、`running`、`online`、`listening`、`version_state` 和脱敏 `reason`；`version_state` 取 `current`、`available`、`required` 或 `unknown`。

系统级变更前，用一句话向用户说明将自动安装或修复的项目并取得一次确认。后续技术操作由 GA 完成，用户只需接受 Windows 管理员提示。

在同一次确认里提醒用户：配置需要修改系统 SSH 配置并重启服务，这类操作常被安全软件误判拦截，建议先退出 360、火绒一类杀毒软件，配置完成后再恢复。同时 ssh 服务的安装需要一定时间，需要请用户耐心等待。

如需用当前 GA 解释器安装 Python 依赖，官方 PyPI 下载缓慢或出现读取超时时，使用镜像源重试，例如：`<当前 GA Python> -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <包名>`；不要因单次下载超时误判 Python 或虚拟环境损坏。

## 3. 准备缺失组件

GAnet 网络组件提供电脑与手机之间的私有连接，OpenSSH 提供终端和文件访问。组件准备完成不代表已经完成组网。

### Windows：GAnet 网络组件

网络组件接口位于 `plugins.ganet.device_connection.sidecar_manager`。安装、替换和入网是不同阶段：本节只处理组件文件与本机进程；第 4 节才使用正式 GA 登录态让组件加入 GAnet。

#### 读取发布列表并选择文件

```python
from plugins.ganet.device_connection import sidecar_manager

releases = sidecar_manager.list_releases()
```

`list_releases()` 读取 `https://ganet.gaagent.ai/releases/sidecar/`，返回发布页实际列出的可用条目及其签名验证结果。每个有效条目至少包含：

```python
{
    "platform": "windows",
    "architecture": "amd64",       # 以发布页实际值为准
    "version": "…",
    "url": "…",
    "sha256": "…",
    "size": 12345678,
    "update_level": "available",
}
```

先确认当前电脑的实际 Windows 架构，再从 `releases` 中选出平台、架构匹配的条目。选择必须依据本机检查结果和发布页返回内容；不得从 SOP、记忆或固定文件名推断版本或架构映射。若发布页不可读但当前组件可用，保留当前组件并继续设备互联，不把版本检查失败报告为连接故障。

#### 下载、验证与安装

```python
artifact = sidecar_manager.download_release(release)
verified = sidecar_manager.verify_release(artifact, release)
result = sidecar_manager.install_release(verified)
```

- `download_release(release)` 仅下载选定条目到临时目录，返回本地 artifact；不替换已安装组件。
- `verify_release(artifact, release)` 验证发布签名、SHA-256、PE 文件、平台和架构；任一检查失败立即停止，不返回可安装 artifact。
- `install_release(verified)` 安装缺失组件，或安全替换已安装组件：停止旧进程、保留可回滚副本、原子替换、恢复当前用户登录启动项并验证二进制版本；已有入网配置时启动组件并确认可响应，首次安装尚未入网时允许保持未运行；失败恢复旧版。

安装成功后重新运行第 2 节检查。组件缺失、无法响应或版本 `required` 时，完成本节后才进入第 4 节；版本 `available` 时当前连接仍可用，但用户本次要求配置或修复设备互联则按本节完成替换后再复检。

### Windows：OpenSSH Server

安装前先阅读 Microsoft 官方文档，再按其中适用于当前 Windows 版本的方式安装 OpenSSH Server：<https://learn.microsoft.com/zh-cn/windows-server/administration/openssh/openssh_install_firstuse>。OpenSSH 安装耗时较长（有时达 20 多分钟），长时间未响应不一定是安装出问题，必要可让用户看看有没有出现进度条，帮忙检查进度。

只安装，不要启动 sshd 服务，也不要设置服务启动类型：官方文档在安装之后还给出了启动服务的步骤，这一步由第 4 节统一负责。原因是 sshd 首次启动会生成默认配置并开始监听默认端口 22，一旦提前启动，第 4 节就无法分辨 22 端口上的服务是用户原有的还是本轮刚装出来的，只能保守地把 22 一起保留下来。

如果本轮由 GA 安装了 OpenSSH Server，请记住这一点，第 4 节调用时需要显式说明。

安装失败时，保留完整错误和检查结果，向用户报告系统组件存储或 Windows Update 的实际问题；不要套用其他 Windows 版本的固定安装命令。

系统组件安装完成后，重新运行第 2 节检查。

## 4. 配置电脑并加入 GAnet

完整编排入口是 `plugins/ganet/device_connection/pairing.py` 的 `configure_environment()`。它先检查正式登录态，再依次调用 `plugins/ganet/device_connection/network.py` 中的系统配置和入网实现，最后返回权威环境检查结果。

GAnet 网络组件就绪后：

```python
from plugins.ganet.device_connection import pairing
result = pairing.configure_environment(approved=True)
```

若第 3 节由 GA 安装了 OpenSSH Server，则加上：

```python
from plugins.ganet.device_connection import pairing
result = pairing.configure_environment(
    approved=True,
    sshd_installed_by_ganet=True,
)
```

不确定时不要传：漏传的后果是保守而安全的。sshd 只要写入任何显式端口，原本隐式生效的默认端口 22 就会失效，因此在无法确认这台电脑的 sshd 是本轮新装的情况下，受管配置会把 22 一并显式保留，避免静默切断用户已经在用的 SSH 访问。本轮新装的 sshd 不存在这类既有访问，只有明确传了这一项，配置才会只监听 GAnet 端口。

一次调用按以下阶段执行：

### 4.1 配置电脑访问能力

`network.apply_confirmed()` 通过 Windows 管理员权限完成：

1. 在 OpenSSH 配置中写入 GAnet 管理块，使用配置端口，同时保留用户原有 SSH 密钥与认证策略；用户原有的显式端口一律保留，原本依赖默认端口 22 的电脑也会把 22 显式保留，除非已说明 OpenSSH Server 由本轮 GA 安装；Windows 管理员账户还会在原有管理员授权文件之外，显式读取该账户独立的 GAnet 授权文件；
2. 准备独立的 `.ssh/authorized_keys_ganet`，并设置 Windows OpenSSH 可接受且当前用户可维护的 ACL；
3. 缓存 SSH Ed25519 主机公钥并重启 sshd；
4. 对嵌入式网络组件，验证 OpenSSH 仅作为本机连接后端可用；不再为旧系统级网络客户端创建入站防火墙规则。

这些操作使用受管标记块和独立授权文件，重复执行应修复现状而不是累加配置。

UAC 提权后的受管配置跑在独立进程，原终端看不到逐步输出。排障时读取：

```text
~/.genericagent/ganet/setup-elevated.log
```

失败返回的 `message` 也会带上该路径。

### 4.2 登记电脑并加入 GAnet

电脑访问配置完成后，`network.enroll()`：

1. 使用正式 GA 登录态向设备登记服务提交电脑身份和 SSH 连接信息；
2. 获取一次性入网授权；
3. 将授权仅交给网络 provider 的受管 `join()` 调用，使已安装组件加入 GAnet；
4. 保存本机入网回执。

一次性授权只在本次入网过程中传递，不得显示、记录或长期保存。嵌入式网络组件不修改 Windows 系统 DNS、路由或用户已有网络客户端。

### 4.3 处理结果

- `needs_project_setup`：说明 `message` 中缺失的当前 GA 组件，补齐后从第 1 节重新开始。
- `needs_system_setup`：说明 `message` 中缺失的系统组件，按第 3 节安装后重新开始。
- `needs_login`：当前正式登录态无效，请用户执行 `/user`，登录后重新开始。
- `blocked`：根据 `stage`、`message` 和环境检查报告失败阶段、真实原因及已经完成的状态，不把 SSH、防火墙失败解释为登录或入网失败。
- `ok`：进入验收。若基础环境仅有 `available` 版本提示，仍可进入验收；在本轮按第 3 节完成组件替换后再复检。

每轮只调用一次 `configure_environment()`。若 `blocked` 信息不足或返回状态与上述阶段职责不一致，可读取 `pairing.py` 中的 `configure_environment()` 以及 `network.py` 中对应的 `apply_confirmed()` 或 `enroll()` 定位接口故障；不要用临时脚本或手工命令绕开受管接口修改 sshd 或网络组件状态。

## 5. 复检与手机配对

`configure_environment()` 返回的 `environment` 是本轮最终检查结果。必要时只再运行一次第 2 节的只读检查，确认：

```text
基础环境 → GAnet 控制面 → SSH 服务 → 设备访问
```

四项均通过后，向用户说明：

```text
设备互联环境已配置完成。
请回到已打开的“GA 用户中心”页面，在“我的设备”中点击“添加设备”，再使用手机 GA 扫描电脑显示的二维码。
```

完成扫码、电脑确认和一次真实连接验证后，才能确认端到端设备互联可用（这些由用户完成）。

## 6. 安全边界

- 导入 `plugins.ganet` 前先把 GA 根目录（本 SOP 所在 `memory/` 的上一级）加入 `sys.path`；Python 依赖用当前 GA 解释器管理。
- 保留用户原有 SSH 密钥、`authorized_keys`、密码登录策略、监听端口、DNS、hosts 与已有网络客户端状态。
- SSH 默认端口为 `48222`；设备连接仅使用 GAnet 的受管网络组件和本机 OpenSSH 后端。
- token、一次性入网授权、配对短消息和 SSH 私钥不写入日志或聊天记录。
