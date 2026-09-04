# brand9 · 雅思口语应用 — 功能与接口速查（开发者文档）

> 本文档是后续开发/改功能时的「地图」：先看这里，避免重复读代码。
> 适用代码目录：`yasi-koiyu/`（本目录）。零第三方依赖 Node 栈。

## 1. 一句话架构

- 前端 = **纯静态单页**：`index.html`（学员端）+ `admin.html`（管理员端）。
  无构建、无框架，`<script>` 直引；所有题目/音频/进度都是静态资源或浏览器本地存储。
- 后端 = **单个 `server.js`**：`node:http` 静态文件服务 + JSON API + `node:sqlite` 存储。
  只依赖 Node ≥ 22.5（`node:sqlite` 内置，22.5+ 可用）。
- 用户数据两层：
  - **浏览器本地**（localStorage / IndexedDB）：题库修改、录音文件、学习进度、练习日志等；
  - **云端**（SQLite `user_state` 表）：把本地关键 key 按账号同步过去，换设备不丢。

## 2. 怎么跑

```bash
cd yasi-koiyu
BRAND9_PORT=8996 node server.js     # 默认就是 8996
```

- 端口环境变量 `BRAND9_PORT`；数据库文件 `brand9.db`（自动建表/迁移，无需手动）。
- 邮件发送配置见 `.env.example`（Resend API Key）；注册验证码走 Resend，失败可回退到管理后台配置的 QQ 邮箱 SMTP。

## 3. 关键文件清单

| 文件 | 作用 |
|---|---|
| `server.js` | 后端全部：静态服务 + 全部 API + SQLite + 会员结算 |
| `index.html` | 学员端主应用（v2.6.0） |
| `admin.html` | 管理员后台（独立登录，登录后即管理） |
| `_init_data.js` | Part 1 题库，注入 `window.INIT_DATA` |
| `all_questions_part23.json` | Part 2&3 题库，运行时 `fetch` |
| `all_questions.json` | Part1 源数据备份（前端不直接引用） |
| `voice/q/`、`voice/ans/` | 题目音频与示范回答 MP3（`P2-*.mp3` 等） |
| `brand9.db` | SQLite 生产库（用户/状态/会员/密钥） |
| `.CLAUDE.md` | AI 助手项目备忘（版本/约定） |
| `CHANGELOG.html` | 版本记录 |
| `health-check.sh` / `monitor.sh` | 部署机守护脚本（在项目外层，见 §10） |

## 4. 前端数据本地 key（localStorage）

| key | 内容 | 是否云端同步 |
|---|---|---|
| `brand9::doc::v3` | Part1 题库（可编辑后本地保存） | 否 |
| `brand9::stars::v2` | Part1 收藏/星标 `{label:true}` | 是 |
| `brand9::stars_p23::v1` | Part2&3 星标 | 是 |
| `brand9::reveal::v2` | 「显示答案」开关 | 是 |
| `brand9::pos::v1` | 最后浏览位置 `{p1,p23}` | 是 |
| `brand9::practiceLog::v1` | 练习打卡日志（Date+Label+Topic+Section+分钟） | 是 |
| `brand9::auth::v1` | 登录态 `{token,username,role}` | 否 |
| `brand9::syncMeta::v1` | 各 key 同步时间戳 | 否 |
| IndexedDB `rec` | 每题的录音 blob（按题目 label） | 否（仅本机） |

> 注：云端同步的「5 个 key」即 `index.html` 中 `SYNC_KEYS`：`practiceLog/stars/reveal/stars_p23/pos`。由 `setItem` 包装器自动 track + 1.5s 防抖推送 `/api/state/sync`。

## 5. 前端功能 → 页面区块（index.html）

| 功能 | 触发点 | 说明 |
|---|---|---|
| Part1 / Part2&3 / 总览 三个 Tab | 顶部 `.tab-btn` | P1 题库来自 `INIT_DATA`，P23 为运行时 fetch JSON |
| 星标收藏、显示答案、编辑模式、全局搜索 | 工具栏/抽屉 | 纯本地 |
| 逐题录音、重听、对照示范音频 | 录音按钮 / 播放器 | IndexedDB 存录音 |
| 计时倒计时答题（45s 等） | `countdownOverlay` | 纯前端 |
| 练习打卡 | 完成一题后 `logPractice()` | 写 practiceLog 并同步 |
| 总览页：打卡热力图/连续天数/累计分钟 | Overview Tab | 由本地 practiceLog 统计 |
| 会员中心（碎片/黄钻/密钥） | 右上角账号→会员中心 | 走 membership API |
| 排行榜 | 会员中心→排行榜 | 走 `/api/scoreboard` |
| 免密直达链接 | 会员中心「我的免密直达登录链接」 | 走 `/api/me/link*` |
| 管理面板 | 管理员账号点右上角 | 走 `/api/admin/*` |

## 6. 后端 API 全表（server.js 路由 ~1092 行起）

约定：
- 除注册/登录/发码外，**一律 `Authorization: Bearer <token>`**；未登录返回 `401 {ok:false,error}`。
- 响应统一 `{ok:true,...}` 或 `{ok:false,error}`。
- 管理员权限 = `role === 'admin'`。

### 6.1 账号 / 登录
| 接口 | 方法 | 说明 | 参数 → 返回 |
|---|---|---|---|
| `/api/register` | POST | 注册（需邮箱验证码） | `{email,password,code,nickname?}` → `{token,username,uuid}` |
| `/api/login` | POST | 登录（用户名或邮箱） | `{username?/email?,password}` → `{token,username,uuid,role}` |
| `/api/login/link` | POST | 免密直达 token 换会话 | `{token}` → `{token,username,uuid,role}` |
| `/api/send_code` | POST | 发注册验证码（60s 冷却） | `{email}` → `{wait,ttl}` |
| `/api/logout` | POST | 注销内存 token | — |
| `/api/me` | GET | 当前用户信息 | → `{username,uuid,role}` |
| `/api/me` | POST | 改昵称 | `{nickname}` → `{username}` |

### 6.2 免密直达链接（login_token / link_open）
| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/me/link` | GET | 我的链接状态 `{open, token}`（管理员默认 open） |
| `/api/me/link/gen` | POST | 生成/重置我的直达 token |
| `/api/admin/accounts/:id/link` | GET | 管理查看某账号链接状态 |
| `/api/admin/accounts/:id/link` | PUT | `{open:true/false}` 开放/关闭（关闭即清 token，旧链接失效） |

### 6.3 云端状态同步
| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/state` | GET | 拉全部 `{key:{value,updated_at}}` |
| `/api/state/sync` | POST | 批量 upsert `{entries:[{key,value,updated_at}]}`（老时间戳不覆盖新） |
| `/api/state/clear` | POST | 清空该用户云端 state |

### 6.4 会员 / 钻石系统（核心「金碎片」逻辑全在服务端）
| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/membership/me` | GET | 我的会员状态（gold/yd_level/redeemable/day_reward/today_practice/next_gap/next_threshold） |
| `/api/membership/convert` | POST | 21 金碎片兑换黄钻 +1 级 |
| `/api/membership/activate` | POST | `{code}` 激活 7/14 天密钥 |
| `/api/scoreboard` | GET | 全服按金积分排序（读取即触发全量结算） |

会员机制速记（server.js `settleMember`）：
- **练满奖励**：一天每练满随机 **21–27 道**触发一轮，得 **1–3 金碎片**（确定性种子，不重复补发）。
- **密钥（7/14 天会员）**：有效期内每日保底 +1 金碎片、免疫黑色碎片。
- **黑色碎片**：判定以用户**所在时区当地 23:30**为界。某日练习 ≤3，且黑碎片判定已生效（即过了当地 23:30）时吃金碎片（黄钻按 grace_days 递减）。页面没开时顺留到下次 `membership/me` 请求补结算。
- **结算触发**：前端在每次 `api()` 附带 `X-Tz-Offset`（分钟）；会员/me/convert/activate 走 `allowBlack=true` 判定；30 分钟定时器、排行榜与管理后台仅做**奖励补算**（`allowBlack=false`，不扣黑碎片，避免离线被吃）。

### 6.5 管理员（admin.html + index.html 管理面板）
| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/admin/me` | GET | 校验管理员身份 |
| `/api/admin/accounts` | GET | 全部账号 + 会员/链接状态 |
| `/api/admin/accounts` | POST | 建号 `{username,password,email?,note?}` |
| `/api/admin/accounts/:id` | PUT | 改备注/邮箱 `{note?,email?}` |
| `/api/admin/accounts/:id/reset` | POST | 重置密码 `{password}`（不能重置自己） |
| `/api/admin/smtp` | GET/PUT | 读/写 QQ 邮箱+授权码（kv 表） |
| `/api/admin/keys` | GET | 密钥列表（含 used 状态） |
| `/api/admin/keys` | POST | 生成密钥 `{type:'7d'|'14d', count}` |

## 7. SQLite 表结构（server.js 建表 ~240 行起）

- `users`：id, username(唯一), pass_salt/hash(PBKDF2 120k), email, role('user'|'admin'), parent_id, note, nickname, uuid, link_open, login_token
- `user_state`：`(user_id, key)` 主键 + value + updated_at（云端同步桶）
- `email_codes`：验证码（5 分钟有效）
- `vip_keys`：code(PK), type('7d'|'14d'), used_by/used_at, created_by/created_at
- `membership`：user_id(PK), key_type/start/expires, gold(金碎片), yd_level, grace_days, last_day_reward, last_status_day, updated_at
- `kv`：k,v（存 smtp 配置）

> 表结构有启动迁移逻辑：缺列自动 `ALTER TABLE ADD COLUMN`，无需手动。

## 8. 已实现功能 → 接口 对照表（改功能时看这张）

| 你想改的需求方向 | 涉及文件/接口 |
|---|---|
| 题库、星标、答案开关、搜索、编辑 | 纯前端 `index.html` + `_init_data.js`，无后端 |
| 录音/重听/倒计时 | 纯前端 IndexedDB |
| 打卡热力图/总览统计 | 前端 practiceLog → `/api/state` `/api/state/sync` |
| 换设备同步 | `/api/state*`（6 个 key） |
| 登录/注册/验证码 | `/api/login` `/api/register` `/api/send_code` `/api/me` |
| 免密直达登录 | `/api/login/link` `/api/me/link*` `/api/admin/accounts/:id/link`，前端读 URL `?pass=`/`?key=` |
| 金碎片/黄钻/兑换 | `/api/membership/me` `/convert`，结算在 server.js `settleMember()` |
| 密钥会员 | `/api/admin/keys*`（发密钥）+ `/api/membership/activate`（激活） |
| 排行榜 | `/api/scoreboard` |
| 管理账号 | `/api/admin/accounts*` `/api/admin/me` |
| SMTP/发信 | `/api/admin/smtp*` |

## 9. 常见改动坑（给下次开发）

1. **前端版本号**在 `index.html` 顶部 `APP_VERSION`，改完记得同步更新并记录到 `.CLAUDE.md` / `CHANGELOG.html`。
2. 会员/金碎片任何改动，重点看 `server.js` 的 `settleMember()`（结算）与 `apiMembershipMe`（读会员）。它是**幂等补算**设计：`last_day_reward` 是当日快照，新增练习后重复结算只补差额。
3. 直改 SQLite 时，生产库表结构以「启动自动迁移」为准；手工加列记得同时更新建表 SQL 与迁移分支。
4. 静态服务缓存策略：HTML 现已 `no-cache`（新逻辑即时生效），mp3 长缓存 immutable，其余 10 分钟。改 js/html 后手机如仍旧版，需清浏览器缓存。
5. 录音/题库等大对象**不**走云端同步，只存本机；多端只同步「进度/星标/打卡」这类轻量 key。

## 10. 运行/守护（生产环境约定）

- 部署端口 **8996**；进程用 `BRAND9_PORT=8996 node server.js` 启动。
- 外层有 `health-check.sh`（`--service yasi-koiyu`）与项目内 `monitor.sh`（15s 轮询，异常自动拉起并写 `monitor.log`）。
- 变更后端后重启服务；改纯前端只需重启让 `no-cache` 分发新 HTML。

## 11. 快速定位（行号可能随版本漂移，按函数名搜）

- 会员结算：`settleMember` / `rewardForCount` / `roundThreshold` / `roundReward`
- 直达登录：`apiLoginLink` / `genLinkToken` / `magicLogin`（前端）
- 前端登录初始化流程：`loadAuth → loadSyncMeta → (读 ?pass/?key) → updateAuthUI → magicLogin/refreshMember/pullCloudState`
- 权限：`auth()` / `requireAdmin()`（server.js）
