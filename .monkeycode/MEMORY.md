# User Instruction Memory

This file records user instructions, preferences, and teachings for reference in future interactions.

## Format

### User Instruction Entry
User instruction entries should follow this format:

[User Instruction Summary]
- Date: [YYYY-MM-DD]
- Context: [Mentioned scenario or time]
- Instructions:
  - [Content of user teaching or instruction, described line by line]

### Project Knowledge Entry
Entries discovered by the Agent during task execution should follow this format:

[Project Knowledge Summary]
- Date: [YYYY-MM-DD]
- Context: Discovered by Agent while performing [specific task description]
- Category: [Operations & Deployment|Build Methods|Testing Methods|Troubleshooting & Debugging|Workflow & Collaboration|Environment Configuration]
- Instructions:
  - [Specific knowledge points, described line by line]

## Deduplication Strategy
- Before adding a new entry, check for similar or identical instructions.
- If a duplicate is found, skip the new entry or merge it with the existing one.
- When merging, update the context or date information.
- This helps avoid redundant entries and keeps the memory file tidy.

## Entries

[User Instruction Summary]
- Date: 2026-08-05
- Context: 讨论 brand9 数据库入库备份
- Instructions:
  - brand9.db 要作为备份入库并推送到远程仓库（用户希望记录始终是最新的，不想担心数据丢失）
  - 提交 yasi-koiyu 改动时，如 brand9.db 有变更需一并 add + commit + push
  - brand9.db-wal / brand9.db-shm / brand9.db-journal 为运行临时文件，仍保持 git 忽略

[Project Knowledge Summary]
- Date: 2026-08-05
- Context: Discovered by Agent while implementing email-verified registration for brand9
- Category: Environment Configuration
- Instructions:
  - brand9（yasi-koiyu，端口 8996）的邮件发送复用 dw-shop 的 SMTP 配置：server.py 启动时读取 `../fun/dw-shop/.env` 中的 `DW_SHOP_SMTP_*`（环境变量优先），无需重复配置；发件邮箱为 armshan@qq.com
  - 验证码逻辑：6 位数字、5 分钟有效、60 秒冷却、重发作废旧码，存 SQLite email_codes 表
