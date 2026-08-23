# 会话上下文摘要（脱敏版）2026-08-04

> 本文档记录 2026-08-04 云环境会话的上下文要点，账号相关敏感信息（令牌、密钥等）已脱敏（以 `<xxx>` 占位符代替），服务网址保留明文。仅用于归档参考，勿将真实凭据提交到公开仓库。

## 任务概览

- 维护 gitee 雅思口语项目 `yasi-koiyu`：按用户要求优化页面 UI（topbar、完成按钮），并通过 post-commit hook 实现每次 commit 后自动推送。
- 会话期间同时管理 nanobot（AI agent）与 yasi-koiyu（雅思口语练习站）两个常驻服务。

## 已完成的部署与改动

- nanobot 运行中：WebUI 端口 3002、gateway 端口 18790、飞书 channel 已连接；登录密钥为会话内约定值（脱敏 `<WEBUI_SECRET>`）。
- yasi-koiyu（brand9）已上线：`cd /workspace/yasi/yasi-koiyu && python3 server.py`，端口 8996，HTTP 200；静态服务，改 index.html 即时生效。
- topbar 移动端优化（more menu 收纳窄屏菜单）已提交推送。
- 完成按钮改图标流程：空心圆 ○ 版被用户否定 → 改为方形透明框 □（U+25A1）版，已推送。
- 已创建 post-commit hook（`/workspace/yasi/.git/hooks/post-commit`）：每次 commit 后自动 push 当前分支到 gitee；推送失败仅写日志不阻塞 commit。
- hook 用空提交验证通过，自动推送到 gitee，本地 master 与 origin/master 同步。

## 关键决策

- **自动推送**：采用 post-commit hook（脚本内部 `cd "$(git rev-parse --show-toplevel)"` 定位仓库根）取代手动确认推送；推送失败记录到 `/tmp/git-autopush.log`，绝不让 commit 失败。
- **完成按钮统一**：Part 1 `p1DoneBtn`、Part 2&3 `p23DoneBtn`、倒计时遮罩 `countdownDoneBtn` 三处一致处理；未完成显示 "□ 标记已完成"，完成显示 "✅ 今日已完成" 并加 `.answered` 绿色样式。
- **本地数据不提交**：`brand9.db` 的本地运行时改动一律不 commit。
- **图片分析降级**：image_analysis 工具不可用（image_url not accessible）、docparse 上传后下载 403，截图分析改用本地像素检测 + tesseract OCR。

## 环境与运行方式

- 所有服务用后台终端工具常驻运行，禁止 `&` 后台符、`pkill`/`killall` 按进程名停止；停止用后台终端管理工具。
- "启动 nanobot" = 运行 WebUI 命令于 3002 端口（带 secret）；"启动雅思口语项目" = `cd /workspace/yasi/yasi-koiyu && python3 server.py`（8996）。
- 预览通过平台 `request_preview(port)` 生成访问链接，不搭建 frp 等隧道（安全护栏）。
- 环境闲置会休眠回收进程，需要时可一键重启。

## 敏感信息（已脱敏）

| 项目 | 值 |
|------|-----|
| WebUI 登录密钥 | `<WEBUI_SECRET>` |

## 可公开的服务地址

| 服务 | URL |
|------|-----|
| nanobot WebUI | https://3002-66dec030646bda22.monkeycode-ai.online |
| yasi-koiyu 雅思口语 | https://8996-66dec030646bda22.monkeycode-ai.online |
| gitee 仓库 | https://gitee.com/devangbamboo/yasi |

## 后续待办

- 确认是否删除测试空提交（`c63960d test: verify autopush hook`，无意义历史，建议清理）。
- 等待用户反馈方形 □ 完成按钮视觉效果；若不满可用 CSS 绘制方框替代 Unicode 字符以统一各平台渲染。
- 用户呼"启动雅思口语项目/上线她"时：pull → 重启 8996（后台终端）→ request_preview。
