# opencode 会话管理工具

本工具是 [opencode](https://opencode.ai)（AI 编程助手）的本地 Web 管理界面，用于查看、检索、重命名历史会话，并**直接在网页上续写对话**（无需回到终端）。

## 架构（v2.0.0）

本工具是官方 `opencode serve` HTTP API 的一个轻量代理与前端，不再直接读取数据库、也不再后台拉起 `opencode run` 子进程：

- 启动后自动探测 `opencode serve --port 4599 --hostname 127.0.0.1`（仅监听本机回环地址，无需鉴权）。若未运行则自动拉起。
- 会话列表 / 详情 / 重命名走官方 REST 接口，始终是最新数据，跨目录，无 sqlite 锁竞争。
- 网页续写对话走 `POST /session/:id/prompt_async`，再订阅 `/global/event` 的 SSE 事件流实现**真实流式回复**，没有子进程、没有 codegraph 收尾挂起的问题。

参考实现：[opencode-visualizer-cn](https://github.com/qiyuanhuakai/opencode-visualizer-cn)（同样基于官方 serve API 的客户端）。

## 功能

- 会话列表：标题、更新时间、所在目录、内容预览，支持按标题 / 内容 / 目录搜索
- 会话详情：完整对话内容（用户消息、助手回复、思考过程、工具调用输入输出、图片附件、改动文件）
- 会话内搜索：过滤消息并高亮关键字
- 重命名：给旧会话起一个好记的名字（便于日后找到）
- **网页对话（续写）**：选中会话后直接在网页输入框继续对话，回复以流式方式实时显示在页面上，上下文完整延续
- 复制命令：复制 `opencode -s <会话ID>`，供在终端里手动打开同一会话
- 统计：顶部展示会话数、Token 总量与累计成本

## 使用方式

方式一（推荐）：双击 `start.bat`，自动启动服务并打开浏览器。

方式二（命令行）：

```
node server.js [端口]
```

默认端口 4123，浏览器访问 http://127.0.0.1:4123

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `OCM_PORT` | `4123` | 本工具 Web 界面端口 |
| `OCM_SERVE_PORT` | `4599` | 后端 `opencode serve` 端口 |
| `OCM_DEFAULT_PROVIDER` | `zen2` | 新会话 / 无模型会话续写时使用的默认 provider |
| `OCM_DEFAULT_MODEL` | `deepseek-v4-flash-free` | 默认 modelID |

续写对话时优先使用**该会话自身记录的模型**；若会话没有模型信息（例如全新空会话），则回退到上面的默认模型，确保网页续写始终可用。

## 数据来源

- 全部数据来自本机 `opencode serve` 的 REST / SSE 接口：`/session`、`/session/:id`、`/session/:id/message`、`PATCH /session/:id`、`POST /session/:id/prompt_async`、`/global/event`（SSE）
- 服务仅监听本机 `127.0.0.1`，不对外暴露

## 安全说明

- 重命名操作只向 serve 发送 `title` 一个字段，不触碰消息、凭证或项目文件
- 不读取任何 API Key、Access Secret 等凭证数据
- 网页续写会在会话原目录里真实执行 AI 工具命令，请注意该目录下可能产生的文件改动

## 目录结构

```
opencode-manager/
  server.js   本地 HTTP 服务（Node 零依赖，作为 opencode serve 的代理 + SSE 转发）
  index.html  前端界面（单文件）
  start.bat   双击启动脚本
  README.md   本说明
```

## 常见问题

- 端口被占用：先关掉其它占用 4123 端口的进程，或改用 `node server.js 8080`
- 网页续写无回复 / 报 `session.error`：通常是默认模型在该环境下没有配置可用的 API Key。可在会话有模型时续写（会沿用会话自身模型），或通过 `OCM_DEFAULT_PROVIDER` / `OCM_DEFAULT_MODEL` 指定一个本机已配置凭证的模型
- 续写等待时间较长：每条消息需要等模型完整回复（可能几分钟），期间界面会实时显示流式内容
- 想换 serve 端口：`set OCM_SERVE_PORT=4600` 后再启动
