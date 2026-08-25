# 配置设备互联环境

触发词：`帮我配置设备互联`、`帮我配置 GAnet`；卸载见第 7 节，触发词：`帮我卸载 GAnet`、`帮我卸载设备互联`。

目标：把当前电脑准备为可与手机 GA 安全配对和连接的设备。

> 当前仅适配 Windows 系统；macOS 和 Linux 暂不支持本配置流程，发现操作系统不适配时停止配置并提醒用户，并告诉用户后续测试开发完善后会上线。

实际配置顺序：

```text
安装 GAnet 组件
→ 准备设备访问环境并打开 GAnet 用户中心
→ 确认 GA 登录
→ 准备 GAnet 网络组件
→ 准备内嵌 SSH 环境（授权文件与主机密钥）
→ 登记电脑并加入 GAnet
→ 复检
→ 在用户中心配对手机
```

SSH 终端与文件访问由 GAnet 网络组件内嵌提供，全程不需要 Windows 管理员权限。

遇到环境缺失或安装失败，可以向用户说明情况、给出建议并提问，但问题必须是首次配置ganet的新手也能回答的（例如是否同意安装、是否继续、屏幕上是否出现某个提示）；不要询问用户不知道的信息。

完成标准：GAnet 组件和设备访问环境已准备，且基础环境、GAnet 控制面、SSH 服务、安全性检查四项检查均通过。

## 1. 安装 GAnet 组件

GAnet 是独立组件：组件形态是 GAnet 仓库的 git 检出，运行在当前 GA 的 Python 环境上，没有自带 Python 运行时。组件位置由用户决定，可整体移动；唯一位置约束是不把组件内容提交进 GenericAgent 的 Git。

先读取固定定位记录 `~/.genericagent/ganet/component.json`；记录只用于发现组件位置，不是可信或完整性证明。若记录结构有效，则以记录中的组件目录为工作目录、用当前 GA 进程的绝对 `sys.executable` 运行 `<sys.executable> -m ganet inspect-component --json`；只有命令成功，且返回的 `ok` 为 `true`、`layout` 为 `source`、`packageRoot` 和 `launcher` 与实际位置一致时，才复用该组件。定位记录不存在或自检失败时，以同样标准检查默认安装位置 `<GA 根目录>\temp\GAnet\`；不要扫描磁盘，也不要仅凭目录、`ganet.cmd` 或定位记录认定组件有效。两处都没有有效组件时，按新安装处理。`inspect-component` 是只读检查，不会写入定位记录。

组件不存在时，用 git 克隆固定公开仓库获取代码：

```text
git clone https://github.com/nianyucatfish/GAnet "<GA 根目录>\temp\GAnet"
```

也可克隆到用户选择的其他目录。git 不可用时先安装 Git 再继续，不要改用 ZIP 或 raw 文件获取源代码。首次克隆前向用户说明：GAnet 是可选设备互联组件，Python 代码来自上述公开 GitHub 仓库，网络组件二进制后续从 `ganet.gaagent.ai` 下载并经服务器签名清单校验；当前 Windows 发布文件尚未进行 Authenticode 签名。组件代码同样需要更新检查：用户要求配置或修复设备互联而组件已存在时，先在组件目录执行一次 `git pull` 再复用；用户对组件有本地改动时按普通 git 合并处理，不要强制覆盖；拉取失败但当前组件自检通过时，保留当前代码继续，不把网络失败报告为组件损坏。克隆或更新后必须按上段运行 `inspect-component --json` 自检。不要将组件内容加入 GenericAgent Git；若 Windows 应用控制策略阻止运行网络组件，停止并如实报告，不关闭或绕过系统安全策略。

组件的轻量 Python 依赖安装进当前 GA 解释器，用当前进程的 `<sys.executable> -m pip install "cryptography>=42" "Pillow>=10" "qrcode>=7.4"` 做最小安装；不得调用裸 `pip`、猜测虚拟环境或安装到其他 Python。GA 解释器缺少 `pip` 模块时，先运行 `<sys.executable> -m ensurepip --upgrade` 补齐再安装。

GA 根目录是本 SOP 所在 `memory\` 目录的上一级，按你读取本 SOP 时实际使用的绝对路径计算，并在传参前确认该目录下 `ga.py`、`agent_loop.py`、`TMWebDriver.py` 和 `assets/tools_schema.json` 齐全；不要用临时脚本的 `__file__`、工作目录或相对层级推算（临时脚本不一定位于 GA 根目录下）。由当前 GA runtime 确定 `sys.executable` 的绝对路径；不要猜测路径，不让用户填写，也不要直接编辑 GAnet 配置文件。以组件目录为工作目录，用当前 GA 解释器准备设备访问环境：

```text
<sys.executable> -m ganet configure-host --ga-root "<GA 根目录绝对路径>" --ga-python "<当前 sys.executable 绝对路径>"
```

相同环境重复执行应直接通过。若现有记录指向另一套或已经移动的 GA/Python，先向用户说明需要修复，再仅在本次明确修复流程中追加 `--repair`；不要静默替换。命令成功后，绑定的 GA Python 会写入 `~/.genericagent/ganet/ga_python.cmd`；该文件只由本命令生成和更新，不要手工创建或编辑。

打开 GAnet 用户中心：无参数运行 `<组件目录>\ganet.cmd`（用户双击同样有效）。它以绑定的 GA Python 启动仅监听本机回环地址的用户中心，打印访问地址并自动打开系统默认浏览器；该进程前台驻留，由 GA 代为打开时作为独立进程启动，不要在当前会话阻塞等待。日常打开用户中心不要求 GA 正在运行，也不需要再次传入 GA 根目录或 Python；组件整体移动后从新位置启动会刷新自身入口和定位记录，不应改变已保存的 GA/Python。

## 2. 确认登录并检查环境

正式 GA 登录为后续电脑登记和 GAnet 入网提供身份。登录接口位于 GAnet 组件的 `ganet/device_connection/auth.py`。

```python
from ganet.device_connection import auth
identity = auth.current_identity()
logged_in = bool(auth.get_token() and identity and identity.get("valid"))
```

未登录时，请用户在已经打开的 GAnet 用户中心完成登录；已登录时继续。

环境检查由 GAnet 组件的 `ganet/device_connection/network.py` 中的 `check_env()` 提供。

本节及后续 Python 接口均使用当前 GA 进程的绝对 `sys.executable`，并以 GAnet 组件目录为工作目录执行，`ganet` 包直接从组件目录导入；不要把 `ganet` 安装进 site-packages，也不要把 GA 根目录临时加入 `sys.path`。

这一步只读，检查：

- GAnet 网络组件是否已安装、运行、加入 GAnet 并监听设备连接；
- GAnet 网络组件版本状态：`current`、`available`、`required` 或 `unknown`；
- 内嵌 SSH 服务状态：私有网络监听、本机回环监听、端口可达；
- GAnet 独立授权文件、ACL 与内嵌 SSH 主机密钥；
- 二维码和电脑截图所需的当前 GA 组件。

版本状态只影响“基础环境”节点的呈现：`available` 为黄色提示，表示当前连接仍可用；`required` 与组件缺失、无法响应一样进入修复流程；`unknown` 不影响当前可用链路。其他状态从 `chain` 和 `checks` 汇总实际缺失项。

组件本机状态和版本状态由：

```python
from ganet.device_connection import sidecar_manager
component = sidecar_manager.inspect()
```

读取。`inspect()` 返回 `installed`、`running`、`online`、`listening`、`version_state` 和脱敏 `reason`；`version_state` 取 `current`、`available`、`required` 或 `unknown`。

变更前，用一句话向用户说明将自动安装或修复的项目并取得一次确认。配置全程运行在当前用户权限下；只有下载运行网络组件可能被安全软件拦截，被拦截时如实报告，不关闭或绕过系统安全策略。

如需向 GA 解释器修复 Python 依赖，官方 PyPI 下载缓慢或出现读取超时时，使用镜像源重试，例如：`<sys.executable> -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <包名>`；不要因单次下载超时误判 Python 或运行环境损坏。

## 3. 准备缺失组件

GAnet 网络组件提供电脑与手机之间的私有连接，并内嵌 SSH/SFTP 服务提供终端和文件访问。组件准备完成不代表已经完成组网。

### Windows：GAnet 网络组件

网络组件接口位于 `ganet.device_connection.sidecar_manager`。安装、替换和入网是不同阶段：本节只处理组件文件与本机进程；第 4 节才使用正式 GA 登录态让组件加入 GAnet。

#### 读取发布列表并选择文件

```python
from ganet.device_connection import sidecar_manager

releases = sidecar_manager.list_releases()
release = sidecar_manager.select_release(releases)
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

条目选择只用 `select_release(releases)`：它按本机实际平台和架构筛选，并返回其中版本最新的一条，没有匹配项时报错。不要自行筛选列表，不得从 SOP、记忆或固定文件名推断版本或架构映射。若发布页不可读但当前组件可用，保留当前组件并继续设备互联，不把版本检查失败报告为连接故障。

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

连通性验证使用系统自带的 OpenSSH Client（`ssh.exe`，Windows 10 及以上默认存在），用于配置完成后的模拟手机连接。

组件安装完成后，重新运行第 2 节检查。

## 4. 配置电脑并加入 GAnet

完整编排入口是 GAnet 组件 `ganet/device_connection/pairing.py` 的 `configure_environment()`。它先检查正式登录态，再依次调用 `ganet/device_connection/network.py` 中的系统配置和入网实现，最后返回权威环境检查结果。

GAnet 网络组件就绪后，先不带参数调用一次，探明是否有待授权的变更：

```python
from ganet.device_connection import pairing
result = pairing.configure_environment()
```

返回 `needs_approval` 时，按 4.1 向用户说明并取得同意，再带 `approved=True` 重新调用。`approved=True` 授权写入内嵌 SSH 授权文件与主机密钥，并继续完成登记入网；未取得用户同意不要传入。本调用不安装网络组件：组件缺失或版本 `required` 时返回 `needs_system_setup`，按第 3 节完成后重新开始。

带授权的调用在当前用户权限下依次执行两个阶段：先配置电脑访问能力（独立授权文件 `~/.genericagent/ganet/authorized_keys` 与内嵌 SSH 主机密钥），再用正式登录态登记电脑并加入 GAnet。两个阶段都幂等，重复执行修复现状而不是累加配置。排障时读取 `~/.genericagent/ganet/setup-elevated.log`，失败返回的 `message` 也会带上该路径。

### 4.1 处理结果

- `needs_project_setup`：说明 `message` 中缺失的当前 GAnet 组件，补齐后从第 1 节重新开始。
- `needs_system_setup`：说明 `message` 中缺失或需更新的网络组件，按第 3 节完成后重新开始。
- `needs_login`：当前正式登录态无效，请用户在 GAnet 用户中心登录，登录后重新开始。
- `needs_approval`：需要配置内嵌 SSH 环境。向用户一句话说明并取得同意后，带 `approved=True` 重新调用；用户不同意则停止并如实说明现状。
- `blocked`：根据 `stage`、`message` 和环境检查报告失败阶段、真实原因及已经完成的状态，不把本地 SSH 环境失败解释为登录或入网失败。
- `ok`：进入验收。若基础环境仅有 `available` 版本提示，仍可进入验收；在本轮按第 3 节完成组件替换后再复检。

带授权参数的 `configure_environment()` 每轮只调用一次；无参调用只用于探明待授权事项，不作为失败重试手段。若 `blocked` 信息不足或返回状态与上述阶段职责不一致，可读取 `pairing.py` 中的 `configure_environment()` 以及 `network.py` 中对应的 `apply_confirmed()` 或 `enroll()` 定位接口故障；不要用临时脚本或手工命令绕开受管接口修改授权文件或网络组件状态。

## 5. 复检与手机配对

`configure_environment()` 返回的 `environment` 是本轮最终检查结果。必要时只再运行一次第 2 节的只读检查，确认：

```text
基础环境 → GAnet 控制面 → SSH 服务 → 安全性检查
```

同时确认第 1 节设备访问环境准备命令已成功；四项均通过后，向用户说明：

```text
设备互联环境已配置完成。
请回到已打开的“GAnet 用户中心”页面，在“我的设备”中点击“添加设备”，再使用手机 GA 扫描电脑显示的二维码。
```

完成扫码、电脑确认和一次真实连接验证后，才能确认端到端设备互联可用（这些由用户完成）。

## 6. 安全边界

- GAnet 组件内容不提交进 GenericAgent 的 Git；运行其 Python 接口时使用当前 GA 解释器并以组件目录为工作目录，轻量依赖装在 GA 环境中，当前 GA 根目录和 `sys.executable` 只由第 1 节内部配置入口显式传入。
- 保留用户原有 SSH 密钥、`authorized_keys`、系统服务、防火墙规则、DNS、hosts 与已有网络客户端状态；不代装或修改任何系统服务。
- SSH 默认端口为 `48222`，由网络组件内嵌服务提供；仅接受 GAnet 私有网络与本机回环连接，只允许公钥认证、命令执行和 SFTP，不提供交互终端和端口转发。
- token、一次性入网授权、配对短消息和 SSH 私钥不写入日志或聊天记录。

## 7. 卸载

用户要求卸载时，先按第 1 节定位组件；组件代码不存在则本机没有可卸载的 GAnet，如实说明即可。向用户确认一次「将移除本机 GAnet 设备互联环境（配对密钥、网络组件与本机数据），组件代码目录保留」，取得同意后在组件目录以 GA 解释器执行：

```python
from ganet.device_connection import pairing
result = pairing.remove_environment(approved=True)
```

该调用按固定顺序完成全部卸载：注销远端设备记录（未登录或不可达时自动跳过，结果无须向用户展开）、停止常驻 Worker 与 GAnet 网络组件、移除登录自启动、删除配对密钥与配对记录、删除 `%LOCALAPPDATA%\GenericAgent\GAnet` 和 `~/.genericagent/ganet`。不要用手工命令替代或补充这些步骤。

- `removed`：向用户说明卸载完成，组件代码目录保留、以后可随时重新配置；提醒用户可在手机 GA 的设备列表中删除这台电脑。用户如要求彻底删除，此时可再删除组件代码目录本身。
- `partial`：按 `message` 与 `steps` 如实报告未完成的本机步骤（常见原因是文件被占用），处理后重新执行同一调用即可，卸载操作可安全重复。
- 未取得用户同意不要传 `approved=True`；无参调用仅返回卸载计划，不做任何变更。
