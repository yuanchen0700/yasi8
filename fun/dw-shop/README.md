# DW Shop

一个轻量的个人商城：出售笔记与有趣的服务。拍下留言 + 线下成交，无需商户资质。

## 功能

- 商店首页：按分类展示在售商品，支持封面图
- 商品详情 + 下单：买家留称呼、联系方式、留言后生成订单
- 下单自动发信：买家留下邮箱时，自动通过 QQ 邮箱发送订单确认邮件
- 管理后台：增删改商品、上传封面图、上下架、查看并处理订单（待处理 / 已成交 / 已关闭）、备注

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入管理密码与 QQ 邮箱授权码
python3 app.py         # 默认端口 8997
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PORT` | 服务端口 | 8997 |
| `DW_SHOP_SECRET` | Flask session 密钥 | dev 默认值 |
| `DW_SHOP_ADMIN_PASSWORD` | 后台登录密码 | `dwshop123`（请用 .env 覆盖） |
| `DW_SHOP_ADMIN_PATH` | 后台路径前缀（随机字符串） | 首次启动自动生成 8 位并写入 .env |
| `DW_SHOP_SMTP_HOST` | 发件 SMTP 服务器 | smtp.qq.com |
| `DW_SHOP_SMTP_PORT` | SMTP 端口（QQ 为 465 SSL） | 465 |
| `DW_SHOP_SMTP_USER` | 发件邮箱（QQ 邮箱） | 空 |
| `DW_SHOP_SMTP_PASSWORD` | SMTP/IMAP 授权码（非 QQ 密码） | 空 |
| `DW_SHOP_MAIL_FROM` | 邮件发件人地址 | 同 SMTP_USER |

QQ 邮箱授权码获取：设置 → 账号 → 开启 SMTP/IMAP → 生成授权码。`.env` 含真实凭据，已被 git 忽略不会入库。

### 订单邮件二维码

买家下单后会收到 HTML 邮件，内含商品介绍与支付引导。邮件中预留两个二维码位置，把图片放到对应路径即可自动嵌入（已被 git 忽略）：

| 位置 | 路径 | 用途 |
|------|------|------|
| 微信支付二维码 | `static/qrcodes/wechat_qr.png` | 买家扫码加微信付款，付款后发货 |
| 公众号二维码 | `static/qrcodes/gzh_qr.png` | 关注公众号获取新品与优惠 |

图片建议正方形（如 300×300），若文件不存在，邮件会自动显示占位虚线框提示。

首次启动会自动创建 `dwshop.db` 并写入 3 个示例商品，后台登录后可在「商品」页删除或改掉。

## 管理后台

后台路径前缀是随机字符串（见 `.env` 的 `DW_SHOP_ADMIN_PATH`，如 `cs96938a`），完整入口为 `http://<地址>/<前缀>/login`。顾客可见页面不提供后台入口，路径只能通过 `.env` 查看，防止被猜出。

## 目录结构

```
dw-shop/
├── app.py              # Flask 主应用
├── helpers.py          # 模板辅助（封面色、分类图标）
├── requirements.txt
├── static/style.css
└── templates/          # 页面模板
```

## 说明

- 数据库 `dwshop.db` 不提交到 git（见 `.gitignore`），本地运行时生成。
- 交易方式为线下成交：买家下单后，通过留下的联系方式与你联系，人工收款交付。
