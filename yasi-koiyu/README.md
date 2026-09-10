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
- 管理: `http://<IP>:8996/admin`

详见 [deploy/README_SERVER.md](deploy/README_SERVER.md)
