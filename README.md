这是有过个项目的文件集合

1 背单词的

2 备考作文相关的

3 使用的经验合集

---

## 踩坑记录（经验教训，避免下次再犯）

### 1. 不要盲目 `git add -A` / `git add .`
同步脚本里用 `git add -A` 会把运行日志、bat 脚本、临时文件等不该入库的东西一起暂存，
下次 `git pull` 时若远程有同名文件就会报：
`error: Your local changes to the following files would be overwritten by merge`
被挡下来的文件曾包括：`fun/opencode-manager/server.log`、`push-gitee.bat`、`fun/words/today.md`、`fun/EADME.md`。
正确做法：
- 用 `git add <具体文件>` 或 `git add -p` 只加需要的内容；
- 给目录写 `.gitignore`（如 opencode-manager 已忽略 `server.log` / `*.log`）。

### 2. 命令行里 push / pull 会被 GCM 交互登录卡住
本机 Git 用 Git Credential Manager，命令行非交互环境弹不出登录框，`git push` / `git pull`
会停在 `could not read Username`。解决办法：在有图形界面的本地双击仓库里的
`push-gitee.bat` 登录后推送；或把 remote 改成 SSH（`git@gitee.com:...`）。

### 3. 不要强制走没开的代理
同步脚本第二段尝试 `127.0.0.1:7890` 代理，本机没开代理就报
`Failed to connect to gitee.com port 443 via 127.0.0.1`。没开代理时不要走代理。

### 4. 子模块 `yasi-rdtli/_super_build` 已取消跟踪
这个 cnb 子模块不好用，已取消跟踪（`git rm --cached` + 清理 `.gitmodules` / `.git/config`），
目录已删除到回收站。今后不要再用这种大目录子模块方式挂仓库。
