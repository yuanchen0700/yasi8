# CodeGraph 自动初始化 · 部署指南（Windows）

让 Claude Code / opencode **打开任何新文件夹时自动 `codegraph init`**，不用手动记。
纯本地、幂等、静默执行，可在任意 Windows 电脑上复刻部署。

---

## 1. 原理

Agent 会话启动时自动触发一个幂等脚本，脚本逻辑：

```
打开项目文件夹
   └─> 检查祖先目录是否已有 .codegraph 索引？
          ├─ 有（就在当前目录）→ codegraph sync -q   （快速增量同步）
          ├─ 有（在上级目录）  → 跳过（索引已覆盖当前目录）
          └─ 没有
               ├─ 目录里没有任何 CodeGraph 支持的代码文件？→ 跳过（不建垃圾索引）
               └─ 有代码文件 → codegraph init          （自动初始化）
```

- **Claude Code**：通过 `~/.claude/settings.json` 的 `SessionStart` 钩子触发
- **opencode**：通过 `~/.config/opencode/plugins/` 下的插件监听 `session.created` 事件触发

所有输出都静默（钩子 stdout 会被注入 AI 上下文，所以脚本设计为完全无输出）。

---

## 2. 文件清单

| 文件 | 作用 |
|---|---|
| `~/.config/codegraph/ensure-codegraph.ps1` | 核心脚本（幂等，自动 init/sync） |
| `~/.claude/settings.json` | 加 `SessionStart` 钩子（Claude Code） |
| `~/.config/opencode/plugins/codegraph-init.js` | opencode 插件（监听 session.created） |

> `~` = `C:\Users\<你的用户名>`；`.config` 是普通文件夹名，不是隐藏目录。

---

## 3. 前置条件

1. **Windows**（macOS/Linux 需把脚本里的 PowerShell 调用换成 bash，本指南只覆盖 Windows）
2. **Node.js**（≥ 18，安装 codegraph 用）
3. **codegraph CLI 已全局安装**（方式任选）：

```powershell
# 方式一：npm
npm i -g @colbymchenry/codegraph

# 方式二：官方脚本（无需 Node.js，但步骤 5 的 npm prefix 探测可跳过）
irm https://raw.githubusercontent.com/colbymchenry/codegraph/main/install.ps1 | iex
```

装完开新终端验证：`codegraph --version`

---

## 4. 创建核心脚本

新建 `C:\Users\<用户名>\.config\codegraph\ensure-codegraph.ps1`，内容如下（**逐字复制**）：

```powershell
# ensure-codegraph.ps1
# Auto-init or sync the CodeGraph index when an agent session opens a project.
# Designed for agent hooks (Claude Code SessionStart / opencode session.created):
# fully silent, idempotent, exits fast. Hook stdout would be injected into the
# agent's context, so nothing is printed on success or skip paths.

param(
    [string]$Target = (Get-Location).Path
)

$ErrorActionPreference = 'SilentlyContinue'

if (-not (Test-Path -LiteralPath $Target)) { exit 0 }
$Target = (Resolve-Path -LiteralPath $Target).Path

$home = $env:USERPROFILE
if ($Target -eq $home -or $Target -eq [System.IO.Path]::GetPathRoot($Target)) { exit 0 }

$supported = @(
    '.py', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts', '.ets',
    '.go', '.rs', '.java', '.cs', '.vb', '.php', '.rb', '.c', '.h', '.cpp', '.hpp', '.cc',
    '.mm', '.swift', '.kt', '.kts', '.scala', '.dart', '.lua', '.r', '.vue', '.svelte',
    '.astro', '.ex', '.exs', '.nix', '.erl', '.cob', '.sol', '.tf'
)

# Locate the codegraph CLI (npm global shim, may be .cmd or .ps1)
$cg = $null
$cmd = Get-Command codegraph -ErrorAction SilentlyContinue
if ($cmd) { $cg = $cmd.Source }
if (-not $cg) {
    # Auto-detect npm global prefix (works on any machine): shim lives at <prefix>\codegraph.cmd / .ps1
    $prefix = (& npm config get prefix 2>$null | Out-String).Trim()
    if ($prefix) {
        foreach ($ext in @('.cmd', '.ps1', '.exe')) {
            $candidate = Join-Path $prefix "codegraph$ext"
            if (Test-Path -LiteralPath $candidate) { $cg = $candidate; break }
        }
    }
}
if (-not $cg) {
    foreach ($p in @(
        (Join-Path $env:APPDATA 'npm\codegraph.cmd'),
        (Join-Path $env:USERPROFILE '.local\bin\codegraph')
    )) {
        if (Test-Path -LiteralPath $p) { $cg = $p; break }
    }
}
if (-not $cg) { exit 0 }

# If this dir (or any ancestor) already has an index, sync only when it is this dir
$dir = $Target
while ($true) {
    if (Test-Path -LiteralPath (Join-Path $dir '.codegraph')) {
        if ($dir -eq $Target) { & $cg sync -q $Target | Out-Null }
        exit 0
    }
    $parent = Split-Path -LiteralPath $dir -Parent
    if ($parent -eq $dir) { break }
    $dir = $parent
}

# Skip folders with no CodeGraph-supported source files (e.g. PowerShell/HTML only).
# Dependencies are pruned: codegraph ignores them anyway, and they must not
# count as "real" source (node_modules .js in a parent dir was triggering
# useless indexes). Short-circuits on the first hit.
$skipDirs = @('node_modules', '.git', 'dist', 'build', 'out', 'venv', '.venv', 'vendor', 'bin', 'obj', '.next', '.nuxt', 'site-packages', '__pycache__')

function Find-SourceFile {
    param([string]$Path)
    $items = Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    foreach ($item in $items) {
        if ($item.PSIsContainer) {
            if ($skipDirs -contains $item.Name) { continue }
            if ($item.LinkType) { continue }
            $found = Find-SourceFile $item.FullName
            if ($found) { return $found }
        }
        elseif ($supported -contains $item.Extension.ToLowerInvariant()) {
            return $item
        }
    }
    return $null
}

$hit = Find-SourceFile $Target
if (-not $hit) { exit 0 }

# Build the initial index (silent)
$null = & $cg init $Target 2>&1
exit 0
```

> 脚本刻意写成 PowerShell 5.1 兼容语法，Windows PowerShell / PowerShell 7 都能跑。
> 无需改任何路径——codegraph CLI 会自动定位（PATH → npm prefix → 常见位置）。

---

## 5. 配置 Claude Code 钩子

编辑 `C:\Users\<用户名>\.claude\settings.json`，在 `"hooks"` 对象里加 `"SessionStart"` 一项：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "shell": "powershell",
            "command": "& 'C:\\Users\\<用户名>\\.config\\codegraph\\ensure-codegraph.ps1'"
          }
        ]
      }
    ]
  }
}
```

注意：
- `shell: "powershell"` 让钩子在 PowerShell 里运行（Windows 上默认是 bash/Git Bash，必须指定）
- 钩子运行时的当前目录 = 你打开的项目目录，脚本默认就在那里找 `.codegraph`
- 生效时机：**下次启动 Claude Code 会话时**（settings.json 不热加载）
- 如果之前 `codegraph install` 已配置过 `UserPromptSubmit` 钩子，保留即可，两者不冲突

---

## 6. 配置 opencode 插件

新建 `C:\Users\<用户名>\.config\opencode\plugins\codegraph-init.js`（目录不存在就创建）：

```javascript
import { execFile, execFileSync } from "node:child_process"

const SCRIPT =
  process.env.CODEGRAPH_ENSURE_SCRIPT ||
  "C:\\Users\\<用户名>\\.config\\codegraph\\ensure-codegraph.ps1"

let shell = "powershell.exe"
try {
  execFileSync("where.exe", ["pwsh"], { stdio: "ignore" })
  shell = "pwsh"
} catch {}

export const CodeGraphInit = async ({ directory }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.created") return
      await new Promise((resolve) => {
        execFile(
          shell,
          [
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            SCRIPT,
            "-Target",
            directory,
          ],
          { timeout: 180000, windowsHide: true },
          () => resolve()
        )
      })
    },
  }
}
```

唯一要改的地方：`SCRIPT` 路径里的 `<用户名>` 换成你的（或用环境变量 `CODEGRAPH_ENSURE_SCRIPT` 指向脚本，优先级更高）。

生效时机：**重启 opencode**。

---

## 7. 验证

```powershell
# 场景 1：已有索引的项目 → 应静默退出（无任何输出）
& "$HOME\.config\codegraph\ensure-codegraph.ps1" -Target "你的项目路径"
# 场景 2：全新目录 → 自动建索引
$t = "$env:TEMP\cg-demo"; New-Item -ItemType Directory $t | Out-Null
Set-Content "$t\a.py" "x = 1"
& "$HOME\.config\codegraph\ensure-codegraph.ps1" -Target $t
Test-Path "$t\.codegraph"   # 应为 True
Remove-Item $t -Recurse -Force
# 场景 3：纯脚本目录（无支持的代码）→ 静默跳过，不建索引
# 场景 4：手动确认索引内容
codegraph status            # 在项目目录里执行
```

---

## 8. 自定义

| 想改什么 | 改哪里 |
|---|---|
| 支持的语言扩展名 | 脚本里 `$supported` 数组 |
| 忽略的目录（不当作源码） | 脚本里 `$skipDirs` 数组 |
| 建索引超时 | opencode 插件里 `timeout: 180000`（毫秒） |
| 换成非默认脚本路径 | 环境变量 `CODEGRAPH_ENSURE_SCRIPT`（opencode）/ settings.json 里改 `command`（Claude Code） |

---

## 9. 故障排查

| 现象 | 原因 / 解决 |
|---|---|
| 打开项目没有 `.codegraph` | 项目里没有受支持语言的代码（.ps1/.bat/.html 不算）→ 属预期行为 |
| 钩子没执行 | 改了配置没重启工具；Claude Code 检查 `settings.json` JSON 是否合法（可用 `ConvertFrom-Json` 验证） |
| 索引一直很旧 | 检查脚本是否定位到 codegraph CLI：先手动跑一遍 `& "$HOME\.config\codegraph\ensure-codegraph.ps1" -Target .` 看退出码 |
| opencode 报插件错误 | 确认 `plugins` 目录名和文件拼写；文件必须是 `.js` 且 export 出插件函数 |
| 想重建索引 | 项目里执行 `codegraph index`（全量重建） |

---

## 10. 移除

```powershell
# 删 Claude Code 钩子：settings.json 里删掉 SessionStart 块
# 删 opencode 插件
Remove-Item "$HOME\.config\opencode\plugins\codegraph-init.js"
# 删核心脚本
Remove-Item "$HOME\.config\codegraph" -Recurse -Force
# 删某项目的索引（可选）
codegraph uninit   # 在项目目录执行
```
