# RTK (Rust Token Killer) — Windows 11 安装指南与避坑手册

> 作者记录于 2026-08-03。本文档用于在任何 Windows 11 新机器上安全安装 RTK，
> **避免重复踩坑：因安装 RTK 把用户 PATH 搞坏，导致 git / claude / codex 全部"消失"。**

---

## 1. RTK 是什么

RTK 是一个 token 优化 CLI 代理，能改写 AI 工具（Claude Code / Hermes / Codex 等）执行的
Bash 命令输出，使其更紧凑，**最多节省 90% 的 token 消耗**。

- 官方仓库：https://github.com/rtk-ai/rtk
- 本次安装版本：**rtk 0.44.2**
- 下载地址（Windows 预编译）：https://github.com/rtk-ai/rtk/releases/latest/download/rtk-x86_64-pc-windows-msvc.zip

---

## 2. 安装步骤（安全版，照抄即可）

### 2.1 下载并解压

```bash
# 在本机创建工具目录（示例）
mkdir -p /c/Users/<你的用户名>/tools/rtk
cd /c/Users/<你的用户名>/tools/rtk

# 下载（如遇证书报错 CRYPT_E_NO_REVOCATION_CHECK，加 -k 跳过）
curl -L -k -o rtk.zip https://github.com/rtk-ai/rtk/releases/latest/download/rtk-x86_64-pc-windows-msvc.zip
unzip -o rtk.zip
rm rtk.zip

# 验证
./rtk.exe --version    # 应输出 rtk 0.x.x
```

### 2.2 把 rtk 目录加入用户 PATH —— ⚠️ 高风险步骤，务必按本方法

**❌ 绝对不要这样做（git-bash 里会写进字面量 %PATH%，清空你的 PATH）：**

```bash
# 这是坑！git-bash 不认 %VAR% 语法，setx 会把 "%PATH%;..." 当纯文本写进注册表，
# 用户 PATH 被整个覆盖，git/claude/codex/npm 等所有用户 PATH 条目全部丢失！
setx PATH "%PATH%;C:\Users\<你>\tools\rtk"
```

**✅ 正确方法 A（git-bash 下用 reg 命令，推荐）：**

```bash
# 1) 先备份当前用户环境（救命备份）
reg export "HKCU\Environment" "C:\Users\<你>\Desktop\hkcu-env-backup.reg" /y

# 2) 读当前用户 PATH 的完整值
reg query "HKCU\Environment" /v Path

# 3) 把读到的值原样拼上 ;C:\Users\<你>\tools\rtk，再写回
#    （把 <完整旧值> 换成上一步读到的内容，REG_EXPAND_SZ 类型不要改）
reg add "HKCU\Environment" /v Path /t REG_EXPAND_SZ /d "<完整旧值>;C:\Users\<你>\tools\rtk" /f

# 4) 广播环境变更，让 explorer 刷新（否则新终端仍拿到旧环境）
powershell.exe -NoProfile -Command "Add-Type -Namespace Win32 -Name NativeMethods -MemberDefinition '[DllImport(\"user32.dll\", SetLastError = true, CharSet = CharSet.Auto)] public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);'; \$HWND_BROADCAST = [IntPtr]0xffff; \$WM_SETTINGCHANGE = 0x001A; \$result = [UIntPtr]::Zero; [Win32.NativeMethods]::SendMessageTimeout(\$HWND_BROADCAST, \$WM_SETTINGCHANGE, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]\$result) | Out-Null"
```

**✅ 正确方法 B（PowerShell 原生，最不容易错）：**

```powershell
# 在 PowerShell 里（不是 git-bash！）
# 只读旧值再写回，PowerShell 的 %PATH% 语义正确
$old = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", $old + ";C:\Users\<你>\tools\rtk", "User")
# 广播（同方法 A 第 4 步）
```

> 提醒：方法 B 里 `$old` 读到的只是用户级 PATH，不含系统级，拼回后类型为 REG_EXPAND_SZ 会正确处理。

### 2.3 初始化 hook（Claude Code + Hermes）

```bash
# Claude Code
rtk init -g --auto-patch

# Hermes Agent（Hermes 也支持！）
rtk init -g --agent hermes --auto-patch

# 查看配置
rtk init --show
```

注意：
- 若机器上同时装了多个 agent，分别 init 即可
- `--auto-patch` 免交互；不用则手动确认
- **claude 在 Windows 上还需要 git-bash**，见 2.4

### 2.4 让 claude 能找到 git-bash（新机器必做）

claude 报 `Claude Code on Windows requires git-bash` 时，设置用户环境变量：

```bash
reg add "HKCU\Environment" /v CLAUDE_CODE_GIT_BASH_PATH /t REG_SZ /d "D:\at-soft\1-sy\Git\bin\bash.exe" /f
# 改完记得广播 WM_SETTINGCHANGE（见 2.2 第 4 步）
```

（路径按本机 Git 实际安装位置改；若 Git 装在 `C:\Program Files\Git`，则为
`C:\Program Files\Git\bin\bash.exe`）

---

## 3. 验证清单

**开一个全新的终端窗口**（必须新开！已打开的窗口环境是旧的）：

```bash
git --version      # Git 正常
claude --version   # Claude Code 正常
codex --version    # Codex 正常
rtk --version      # RTK 正常
rtk gain           # 显示 token 节省统计
```

如果新窗口里某个命令找不到 → 说明 explorer 没刷新成功，先注销/重启 Windows 再试，
再不行按第 4 节恢复。

---

## 4. 出事故了怎么办（PATH 被覆盖/清空时的救援）

症状：`git` / `claude` / `codex` 全部 "无法识别"；`reg query "HKCU\Environment" /v Path`
显示的是一串以 `%PATH%;` 开头的字面量或只有几个条目。

救援步骤（按顺序）：

```bash
# 1) 如果装 RTK 前有备份，直接恢复
reg import "C:\Users\<你>\Desktop\hkcu-env-backup.reg"

# 2) 没有备份的话，从"当前还活着的 bash 进程"里捞旧 PATH：
#    bash 进程的内存里通常还保留着启动时的完整 PATH（含所有用户条目）
echo "$PATH" | tr ';' '\n' | grep -v -E "mingw64|usr/bin|hermes-web-ui|/bin$" | sort -u
#    把列出的 Windows 目录（/c/... 转回 C:\...，/d/... 转回 D:\...）拼回分号分隔，写回注册表

# 3) 写回后广播 WM_SETTINGCHANGE，然后注销/重启 Windows
```

> ⚠️ **恢复 PATH 时最容易漏掉的两段（都踩过坑）：**
> 1. **系统目录段**：`%SystemRoot%\system32;%SystemRoot%;%SystemRoot%\System32\Wbem;
>    %SystemRoot%\System32\WindowsPowerShell\v1.0;%SystemRoot%\System32\OpenSSH`
>    —— 漏了它，cmd / notepad / ipconfig 全部"不是内部或外部命令"。
> 2. **Git 目录段**：`D:\at-soft\1-sy\Git\cmd` —— 漏了它，git 找不到。
>    用 `reg query "HKLM\SOFTWARE\GitForWindows" /v InstallPath` 确认 Git 真实安装位置。

本机（Cheng 的 Win11）已恢复的用户 PATH 条目清单（2026-08-03 实测）：

```
C:\Users\Cheng\.minimax\bin
C:\Users\Cheng\AppData\Local\AtomCode
C:\Users\Cheng\.cargo\bin
C:\Users\Cheng\.mimocode\bin
D:\at-soft\1-sy\sqlite
D:\at-soft\1-sy\ffmpeg
D:\at-soft\1-sy\Git\cmd
D:\at-soft\1-sy\node\npm-global
D:\at-soft\1-sy\nodejs
D:\at-soft\1-sy\uv
D:\at-soft\1-sy\python\bin
%SystemRoot%\system32
%SystemRoot%
%SystemRoot%\System32\Wbem
%SystemRoot%\System32\WindowsPowerShell\v1.0
%SystemRoot%\System32\OpenSSH
D:\at-soft\1-sy\nvm
D:\at-soft\1-sy\nvm\nodejs
D:\at-soft\1-sy\powershell7\7
C:\Users\Cheng\.local\bin        ← claude.exe 在这里
D:\at-soft\2-tools\02\hotkey\AutoHotkey\v2
D:\at-soft\2-tools\02\free-graph\Project Graph
C:\Users\Cheng\bin
C:\Users\Cheng\tools\rtk          ← RTK 新增
```

---

## 5. 本机现状（2026-08-03 已修复）

| 项目 | 值 |
|------|-----|
| rtk.exe | `C:\Users\Cheng\tools\rtk\rtk.exe`（v0.44.2） |
| Claude Code hook | `~/.claude/RTK.md` + settings.json hook，`rtk init -g` |
| Hermes 插件 | `~/.hermes/plugins/rtk-rewrite`，`rtk init -g --agent hermes` |
| CLAUDE_CODE_GIT_BASH_PATH | `D:\at-soft\1-sy\Git\bin\bash.exe` |
| 用户 PATH | 已恢复全部条目 + rtk（见第 4 节清单） |
| 效果 | 实测节省约 63.6% token |

---

## 6. 常见问题

- **Q: curl 报 `CRYPT_E_NO_REVOCATION_CHECK`？** A: 加 `-k` 跳过证书吊销检查。
- **Q: `rtk init --show` 只显示 Claude 不显示 Hermes？** A: 正常，Hermes 插件单独用
  `rtk init -g --agent hermes --auto-patch` 装，装完看 `~/.hermes/plugins/rtk-rewrite`。
- **Q: 改完 PATH 后新终端还是不生效？** A: explorer 没刷新。注销/重启 Windows 最稳。
- **Q: rtk 文件放哪都行吗？** A: 可以，但路径一旦定了就别挪，PATH 里写死了。
