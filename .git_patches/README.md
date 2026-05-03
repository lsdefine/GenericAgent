恢复补丁目录

说明：将自定义项目级补丁放在此目录，方便在项目被上游更新、覆盖或回退后一键重新应用。

约定：
- 所有补丁以 `patch-{n}-{desc}.patch` 命名（git 格式 diff）。
- `apply_patches.bat` 会按字典序应用所有 `.patch` 文件。
- 如果补丁已应用（git 空差异），会跳过并继续下一个。

使用：在项目根目录运行：

    .\.git_patches\apply_patches.bat

注意：该脚本会运行 `git apply --index`，因此需要在有未提交改动的情况下小心使用。建议先 stash 未提交改动或在分支上运行。