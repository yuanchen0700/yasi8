# brand9 (yasi-koiyu) 服务器部署指南

## 系统要求
- Linux (Ubuntu 20.04+ / Debian 11+)
- Node.js >= 22.x
- 端口 8996（可自定义）

## 快速安装
```bash
sudo mkdir -p /opt && sudo tar xzf brand9-server-20260910.tar.gz -C /opt
cd /opt && sudo ./install.sh
```

## 配置邮件（可选）
编辑 `.env` 填写 `RESEND_API_KEY` 或 SMTP 配置。

## 启动
```bash
sudo systemctl start brand9 && sudo systemctl enable brand9
```

## 访问
- 博客: `http://<IP>:8996/`
- 管理后台: `http://<IP>:8996/admin.html`

## 数据库合并（多服务器用户合并）

如果另一台服务器上已有注册的用户，不要直接 `cp` 整个 `brand9.db`（会覆盖现有数据），用合并脚本：

```bash
# 把另一台服务器的 brand9.db 传到当前服务器
scp other-server:/opt/yasi-koiyu/brand9.db /tmp/brand9-other.db

# 执行合并（自动跳过已有用户，只追加新用户）
node merge-db.js /tmp/brand9-other.db brand9.db

# 确认无误后重启服务
sudo systemctl restart brand9
```

脚本行为：按 user id 去重，只追加新用户及其会员/进度数据；已存在的用户完全不动。

---

## 文件结构

| 文件/目录 | 说明 |
|-----------|------|
| `server.js` | Node.js 后端（零第三方依赖） |
| `index.html` | 学员端主界面 |
| `admin.html` | 管理员后台 |
| `brand9.db` | SQLite 数据库（用户/会员/状态） |
| `voice/q/` + `voice/ans/` | 题目音频 (814个 mp3) |
| `.env.example` | 邮件配置模板 |
| `install.sh` | 一键安装脚本 |
| `merge-db.js` | 多服务器数据库合并脚本 |
| `deploy/` | TLS 证书 |

详见下方「数据库合并」章节。
