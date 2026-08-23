# rtk_gain_report 脚本修复说明（交接文档）

## 涉及文件
- `deepseek_batch_20260803_a3fa24.bat` — 启动器：设置代码页后调用 ps1
- `rtk_gain_report.ps1` — 主脚本：跑 `rtk gain` / `rtk gain --history`，生成 HTML 报告并打开浏览器
- 运行方式：双击 `.bat`，或 `powershell -ExecutionPolicy Bypass -File rtk_gain_report.ps1`

## 已完成：脚本无法运行的问题（已修复）

### 根因
`rtk_gain_report.ps1` 是 **UTF-8 无 BOM** 编码，但脚本第 1 行注释明确要求 "UTF-8 with BOM required"。
在中文系统（GBK 代码页）上，Windows PowerShell 5.1 会把无 BOM 的 UTF-8 按 ANSI/GBK 读取，
脚本里的多字节字符（⚠️、—、▌ 等）被破坏，导致 here-string 解析错乱，报 4 处 ParserError
（原报错位置在 162 / 187 / 204 / 209 行）。

### 修复动作
用 PowerShell 重新以 **UTF-8 with BOM** 保存了 `rtk_gain_report.ps1`，重新解析通过（PARSE OK）。

### 验证结果
双击 `.bat` 可正常运行，生成 `rtk_gain_report.html` 并自动打开浏览器。

---

## 已修复：数据解析错误 + 原始输出乱码（2026-08-03 接手完成）

### 修复方案
1. **汇总数据改用 JSON**：`rtk gain -f json` 返回 `summary` 对象
   （`total_saved` / `avg_savings_pct` / `total_commands` / `total_input` / `total_output` / `total_time_ms`），
   用 `ConvertFrom-Json` 解析，彻底告别正则猜数字。
2. **逐命令明细仍解析文本表格**（JSON 只有汇总，无 per-command）：
   正则 `^\s*(\d+)\.\s+(.+?)\s+(\d+)\s+(\d+)\s+([\d.]+%)\s+([\d.]+ms)` 匹配 "By Command" 表格行。
3. **乱码修复**：脚本开头强制 `[Console]::OutputEncoding = UTF8` + `$OutputEncoding = UTF8`，
   使 `cmd /c` 捕获 rtk 的 UTF-8 输出被正确解码（PS 5.1 已验证，盒线字符 ═ 完好）。
4. HTML 占位符替换从 `-replace` 改为 `.Replace()`，避免 `$` 等正则/替换串字符误伤。

### 验证结果（当前 rtk 0.44.2）
- Total Tokens Saved: `106 (49.1%)` ✔（旧版错误显示 3）
- Commands: `4` ✔（旧版错误显示 6）
- 逐命令表：saved 52/45/9/0，pct 69.3%/73.8%/52.9%/0.0% ✔
- 原始输出区无乱码（文件字节级验证 E2 95 90 = ═）✔

---

## 旧待办存档（已解决，仅保留参考）

脚本能跑，但解析出来的数据是错的，报告基本不可用。原因是：
**脚本的解析正则写的是旧版 rtk 的 `命令: N tokens (xx%)` 格式，而当前 rtk 0.44.2 实际输出是表格。**

### 实际 rtk 0.44.2 输出格式（`rtk gain` / `rtk gain --history` 相同）

```
RTK Token Savings (Global Scope)
════════════════════════════════════════════════════════════

Total commands:    3
Input tokens:      199
Output tokens:     102
Tokens saved:      97 (48.7%)
Total exec time:   54ms (avg 18ms)
Efficiency meter: ████████████░░░░░░░░░░░░ 48.7%

By Command
───────────────────────────────────────────────────────────────────────
  #  Command                   Count  Saved    Avg%    Time  Impact    
───────────────────────────────────────────────────────────────────────
 1.  rtk ls -la .                  1     52   69.3%    27ms  ██████████
 2.  rtk ls -la /d/a.creat...      1     45   73.8%    12ms  █████████░
 3.  rtk proxy ls -la /d/a...      1      0    0.0%    15ms  ░░░░░░░░░░
───────────────────────────────────────────────────────────────────────

Recent Commands
──────────────────────────────────────────────────────────
08-03 13:34 ■ rtk ls -la .              -69% (52)
08-03 13:23 ▲ rtk ls -la /d/a.create... -74% (45)
08-03 13:22 • rtk proxy ls -la /d/a.... -0% (0)
```

### 当前错误表现（生成报告里的实际结果）
- "Total Tokens Saved" 显示 `3` —— 应为 `97 (48.7%)`
  - 原因：`$totalOut` 的匹配正则（46 行）未锚定，`(\d+)\s*...` 扫到的第一个数字是 "Total commands: 3" 里的 `3`
- "Commands Analyzed" 显示 6 —— 应为 3
- 表格把 "Total commands"、"Input tokens" 等汇总标签当成命令列了出来
  - 原因：`Parse-History`（22 行）正则 `^([^:]+):\s*(\d+)` 会命中这些 `标签: 数字` 行
- 原始输出区乱码：`═` `─` `█` `■` `▲` `•` 变成 `�`
  - 原因：`Run-Cmd` 用 `cmd /c` 捕获输出时走的是系统 GBK 代码页，而 rtk 输出 UTF-8

### 建议修复方向（按优先级）
1. **先查 `rtk gain --help`** 看有没有 `--json` / `--format` 之类的机器可读输出。
   如果有，直接解析 JSON 最省事、最稳（当时被你中断，还没查）。
2. 若没有 JSON，改 `Parse-History` 正则去匹配真实的 "By Command" 表格行，
   例如匹配形如 `^\s*\d+\.\s+(.+?)\s+\d+\s+(\d+)\s+([\d.]+%)` 的行，
   从 "Saved" 列取数字；"Total tokens saved" 从 "Tokens saved:      97 (48.7%)" 行提取。
3. 乱码问题：在 ps1 开头捕获输出前先 `chcp 65001`（或设置 `$OutputEncoding`），
   或让 `Run-Cmd` 用 `cmd /c chcp 65001 >nul && rtk ...`，再以 UTF-8 读取。

### 其他注意点
- 脚本最后 `Start-Process $outFile` 会打开浏览器，这是预期行为。
- 表格/原始输出里出现的中文乱码（`�T�T` 之类）是同一个编码问题，修好捕获编码即可。
- HTML 模板里图表用的是 CDN 的 Chart.js，离线打开无网时图表不显示（不影响数据）。
