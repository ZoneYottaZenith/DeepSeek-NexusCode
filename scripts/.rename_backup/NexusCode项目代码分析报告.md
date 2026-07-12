# Reasonix 项目代码分析报告

> 分析日期：2026-07-10  
> 项目版本：DeepSeek-Reasonix v2（main-v2，Go 重写版 1.0+）

---

## 一、项目定位

**Reasonix** 是一个 **AI 编码智能体（Coding Agent）**，用 **Go** 语言完全重写（原 TypeScript 0.x 版本已废弃，仅维护模式）。核心定位是**围绕 DeepSeek 生态构建的配置驱动编码助手**，对标 Claude Code，但针对 DeepSeek 的 prefix cache 机制做了深度优化以降低 Token 成本。

> 项目地址：https://github.com/esengine/DeepSeek-Reasonix  
> npm 安装：`npm i -g reasonix`  
> 许可证：MIT

---

## 二、整体架构分层

```
cmd/
├── reasonix/                  ← CLI 主入口
├── reasonix-plugin-example/   ← MCP 插件参考示例
└── e2ebench/                  ← 端到端性能压测

desktop/                       ← Wails 桌面应用（Go + Webview）
├── main.go                    ← 桌面入口（CGO 隔离模块）
├── app.go                     ← Wails 绑定层（前端 JS ↔ Go 桥接）
├── bot_bridge.go              ← Bot 桌面桥接
├── session_*.go               ← 会话管理
├── frontend/                  ← 前端 Webview 源码
└── build/                     ← Wails 构建产物

internal/                      ← 核心内核（30+ 包）
├── cli/                       ← CLI 子命令路由、flag 解析、UI 主题
├── boot/                      ← 唯一组装点：config → Controller
├── control/                   ← 传输无关的会话驱动层（核心枢纽）
├── agent/                     ← Agent 运行循环（核心引擎）
├── provider/                  ← Provider 接口 + 注册表
│   ├── openai/                ← OpenAI 兼容实现
│   └── anthropic/             ← Anthropic Messages API
├── tool/                      ← Tool 接口 + 注册表
│   └── builtin/               ← 30+ 个内置工具
├── plugin/                    ← MCP 客户端（stdio/HTTP/SSE）
├── config/                    ← TOML 配置加载
├── permission/                ← 权限策略引擎
├── command/                   ← 自定义斜杠命令
├── event/                     ← 类型化事件流定义
├── memory/                    ← 层级记忆系统
├── memorycompiler/            ← Memory v5 执行编译器
├── sandbox/                   ← OS 沙箱隔离
├── checkpoint/                ← 快照回滚系统
├── guardian/                  ← 安全审查子智能体
├── diff/                      ← 行级 diff 引擎
├── history/                   ← 对话历史持久化
├── lsp/                       ← LSP 客户端
├── skill/                     ← Skill 加载系统
├── hook/                      ← 钩子系统
├── jobs/                      ← 后台任务管理器
├── serve/                     ← HTTP/SSE 服务端
├── evidence/                  ← 工具调用证据簿
├── store/                     ← 自动记忆存储
├── billing/                   ← 计费/额度查询
├── acp/                       ← Agent Client Protocol
├── bot/                       ← IM 机器人网关（QQ/飞书/微信）
├── botruntime/                ← Bot 运行环境
├── retrieval/                 ← 检索模块
├── secrets/                   ← 秘密管理
├── shellparse/                ← Shell 命令解析
├── textutil/                  ← 文本工具
├── fileutil/                  ← 文件工具
├── netclient/                 ← HTTP 客户端封装
├── i18n/                      ← 国际化
├── outputstyle/               ← 输出样式
├── planmode/                  ← 计划模式
├── proc/                      ← 进程管理
├── frontmatter/               ← Markdown frontmatter 解析
├── environment/               ← 环境摘要
├── notification/              ← 系统通知
├── autorearch/                ← 自动调研
├── guardian/                  ← 安全策略审查
├── capability/                ← 能力声明
├── nilutil/                   ← nil 安全工具
├── mcpdiag/                   ← MCP 诊断
└── migration/                 ← 配置迁移

docs/                          ← 文档
├── SPEC.md                    ← 工程规范合约
├── GUIDE.md / GUIDE.zh-CN.md  ← 用户指南
├── BOT_GUIDE.md               ← Bot 部署指南
├── MIGRATING.md               ← 0.x → 1.0 迁移指南
├── CHECKPOINTS.md             ← 快照回滚文档
├── TASK_CONTRACT.md           ← 任务合约
├── TOOL_CONTRACT.md           ← 工具合约
└── ...                        ← 其他文档

npm/                           ← npm 发包脚本
scripts/                       ← CI/辅助脚本
benchmarks/                    ← 性能基准测试
workers/                       ← 工作进程
tools/                         ← 开发工具
site/                          ← 项目网站
```

---

## 三、核心设计理念

### 3.1 配置驱动，零硬编码

```go
// 注册表模式
type Factory func(cfg Config) (Provider, error)
var registry = map[string]Factory{}

func Register(kind string, f Factory)  // init() 自注册
func New(kind string, cfg Config) (Provider, error)
```

**关键原则**：Provider 和 Tool 都是接口 + 注册表模式。DeepSeek、Claude、MiniMax 等都是配置条目，不是代码。添加一个新模型只需改 `reasonix.toml`。

### 3.2 多前端共享一个 Controller

```
┌─────────────────────────────────────────────────┐
│                control.Controller                │
│  (传输无关的会话驱动层，所有前端共享同一套生命周期)    │
└──────────────────┬──────────────────────────────┘
         ┌─────────┼─────────┐
         ▼         ▼         ▼
    CLI(TUI)   Desktop    HTTP/SSE
   (bubbletea) (Wails)   (serve)
```

`control.Controller` 是**唯一的会话驱动层**，所有前端通过 `event.Sink` 消费类型化事件流，通过命令接口（Send/Cancel/Approve/Compact）驱动会话。

### 3.3 Cache 优先架构

系统提示词前缀（base prompt + tools + memory）必须**字节稳定**，以最大化 DeepSeek prefix cache 命中率。

关键实现（`internal/agent/compact.go`）：

- **静默压缩**：达到窗口 80% 触发压缩
- **保留尾部**：最近的 16384 Token 原文保留
- **摘要替换**：旧对话通过模型自己生成的结构化摘要替换
- **缓存感知**：压缩前后保持前缀字节不变

```go
const (
    defaultSoftCompactRatio  = 0.5   // 报告上下文增长告警
    defaultCompactRatio      = 0.8   // 触发压缩
    defaultCompactTarget     = 0.5   // 压缩后不超过窗口的一半
    defaultTailTokens        = 16384 // 保留的最近原文 Token 数
)
```

### 3.4 双模型协作（Coordinator）

`internal/agent/coordinator.go` 实现了 **Planner + Executor** 双模型模式：

- **Planner**：只读权限，做计划、调研、问问题
- **Executor**：写权限，执行具体操作
- **审批门控**：`[planner_requires_approval]` 标记触发用户审批
- **用户决策**：`<planner-ask>` 结构体向用户提问
- **降级机制**：Planner 失败时自动降级为 Executor-only

---

## 四、内置工具集（30+）

| 工具 | 文件 | 功能描述 |
|------|------|----------|
| `read_file` | `readfile.go` | 读取文件，支持 UTF-16 编码、大文件窗口读取 |
| `write_file` | `writefile.go` | 写文件 |
| `edit_file` | `editfile.go` | 行级编辑（查找替换） |
| `multi_edit` | `multiedit.go` | 多文件批量编辑 |
| `delete_range` | `delete_range.go` | 按行范围删除 |
| `delete_symbol` | `delete_symbol.go` | 按符号名删除（Go/TS/JS 等） |
| `move_file` | `movefile.go` | 移动/重命名文件 |
| `bash` | `bash.go` | Shell 命令执行（经沙箱隔离） |
| `ls` | `ls.go` | 列目录 |
| `glob` | `glob.go` | 通配符文件搜索 |
| `grep` | `grep.go` | 全文搜索（支持多引擎） |
| `web_fetch` | `webfetch.go` | HTTP 网络请求 |
| `todo_write` | `todo.go` | 任务列表管理 |
| `complete_step` | `completestep.go` | 步骤完成确认（证据匹配） |
| `task` | `task.go` | 启动子智能体 |
| `run_skill` | — | 运行 Skill 剧本 |
| `memory` | — | 持久记忆读写 |
| `notebook_edit` | `notebookedit.go` | Jupyter Notebook 编辑 |
| `code_index` | `codeindex.go` | Tree-sitter 代码索引 |
| `bg_jobs` | `bgjobs.go` | 后台任务管理 |
| `session_guard` | `session_guard.go` | 会话保护 |
| `webfetch` | `webfetch.go` | 网页抓取渲染 |
| `confine` | `confine.go` | 路径限制工具 |
| `gitignore` | `gitignore.go` | .gitignore 匹配 |
| `preview` | `preview.go` | 文件变更预览 |
| `clientio` | `clientio.go` | 客户端 I/O 代理 |
| `managed_config` | `managed_config.go` | 配置管理 |

---

## 五、安全体系

### 5.1 沙箱隔离（Sandbox）

| 平台 | 技术方案 | 实现文件 |
|------|----------|----------|
| macOS | Seatbelt（sandbox-exec） | `sandbox/sandbox_darwin.go` |
| Linux | Bubblewrap | `sandbox/sandbox_linux.go` |
| Windows | AppContainer / Low Integrity Token + Job Object | `sandbox/sandbox_windows.go` |

**行为规则**：
- 只读命令 → AppContainer（强隔离）
- 写命令 → Low Integrity Token（中隔离）
- 沙箱不可用 → **fail-closed**（拒绝执行，不是降级）

### 5.2 权限策略（Permission）

```go
type Decision int
const (
    Allow Decision = iota  // 放行
    Ask                    // 询问用户
    Deny                   // 拒绝
)
```

支持规则匹配语法：
- `ToolName` — 匹配该工具所有调用
- `ToolName(glob)` — 按 glob 匹配参数
- `ToolName=literal` — 精确字符串匹配

### 5.3 秘密管理（Secrets）

`internal/secrets/`：
- API Key 从环境变量读取（`api_key_env`）
- 工具输出自动脱敏（`*_API_KEY`、`*TOKEN*`、`*SECRET*` 等正则模式）
- 敏感文件保护（`.env`、`.git-credentials`、`*.pem`、`~/.ssh` 等路径不可见）
- 子进程环境变量过滤（可选）

### 5.4 安全审查（Guardian）

`internal/guardian/` — 独立的子智能体审查层：

- 每次工具调用前进行安全审查
- 返回 `risk_level` + `outcome`（allow/deny）
- **熔断器**：连续拒绝 3 次触发熔断
- 专用审查模型（可配置）
- 审查策略内嵌在 `guardian_policy.md` 中

---

## 六、记忆系统（Memory v5）

### 6.1 层级文档

```
记忆优先级（高 → 低）：
1. REASONIX.local.md       ← 本地个人（git-ignored）
2. REASONIX.md             ← 仓库共享
3. ~/.config/reasonix/REASONIX.md  ← 用户全局
4. 祖先目录的 REASONIX.md
5. AGENTS.md（兼容 Claude Code 命名）
```

### 6.2 自动记忆

`internal/memory/`：
- `MEMORY.md` 索引文件
- `remember` 工具写入持久事实
- 跨会话加载到系统提示词前缀

### 6.3 Memory v5 编译器

`internal/memorycompiler/` — 革新性记忆系统：

- **执行追踪**：记录每条策略的使用情况和效果
- **策略评分**：基于历史成功率动态调整
- **变异优化**：以 10% 探索率尝试策略变异
- **衰减机制**：长时间未使用的策略自动降权
- **反馈冷却**：30 分钟内不重复反馈同一策略

```go
const (
    explorationRatePercent   = 10   // 探索率
    mutationAcceptThreshold  = 0.60 // 变异接受阈值
    strategyDecayK           = 10.0 // 衰减系数
    staleConfidenceThreshold = 0.2  // 置信度阈值
)
```

---

## 七、扩展机制

### 7.1 MCP 插件系统

`internal/plugin/` — 完整的 MCP（Model Context Protocol）客户端：

| 传输类型 | 描述 |
|----------|------|
| stdio | 子进程 JSON-RPC（默认） |
| Streamable HTTP | HTTP 流式传输 |
| SSE（legacy） | 传统 Server-Sent Events |

- 工具自动适配为 `mcp__<server>__<tool>` 命名空间
- 支持读写权限标注（`annotations.readOnlyHint`）
- 支持超时配置（全局/调用级/工具级）
- 支持前缀剥离（`StripRawPrefix`）

### 7.2 Skills 技能剧本

`internal/skill/` — Markdown 编写的可执行剧本：

| 执行模式 | 描述 |
|----------|------|
| `inline` | 内容嵌入当前 turn |
| `subagent` | 隔离子循环，只返回最终答案 |

- 支持触发器（`triggers`）自动建议
- 支持 `allowed-tools` 限制子智能体工具集
- 支持 `read-only` 只读模式
- 支持模型/耗力覆盖配置

### 7.3 钩子系统（Hooks）

`internal/hook/` — 围绕 Agent 循环的 Shell 钩子：

| 事件 | 触发点 | 可阻断 |
|------|--------|--------|
| `PreToolUse` | 工具调用前 | ✅ |
| `PostToolUse` | 工具调用后 | ❌ |
| `PermissionRequest` | 权限审批前 | ✅ |
| `UserPromptSubmit` | 用户提交提示前 | ✅ |
| `SessionStart` | 会话启动 | ❌ |
| `SessionEnd` | 会话结束 | ❌ |
| `SubagentStop` | 子智能体结束 | ❌ |
| `Stop` | 停止信号 | ❌ |
| `PostLLMCall` | 模型调用完成 | ❌ |
| `Notification` | 需要用户注意 | ❌ |
| `PreCompact` | 上下文压缩前 | ❌ |

退出码协议：0=放行，2=阻断，其他=告警。

### 7.4 斜杠命令

`internal/command/` — 从 `.md` 文件加载的自定义命令：
- 参数替换：`$ARGUMENTS`、`$1`..`$N`、`$$`
- 目录扫描：按优先级覆盖
- 支持 symlink 跟随

---

## 八、Bot 多渠道网关

`internal/bot/` 实现了三端机器人接入：

| 平台 | 实现文件 |
|------|----------|
| QQ | `bot/qq/` |
| 飞书/Lark | `bot/feishu/` |
| 微信 | `bot/weixin/` |

**核心能力**：
- 通过桌面端 `DesktopBridge` 获得"上帝视角"
- `/desktop` 命令体系：status / watch / approve / deny / answer / takeover / release
- 远程审批：对桌面端待审批项进行远程操作
- 会话接管：IM 消息直接驱动桌面端会话
- 事件推送：审批请求、任务完成/出错实时推送到 IM

---

## 九、桌面应用

`desktop/` 基于 **Wails v2** 构建：

| 特性 | 描述 |
|------|------|
| 前端框架 | Webview（HTML/JS/TS） |
| 后端绑定 | Wails runtime + Go binding |
| 多标签 | 多项目同时工作 |
| 自动更新 | stable / canary 双通道 |
| 系统托盘 | Windows/macOS/Linux |
| 单实例 | 同名二进制只启动一个实例 |
| Windows 沙箱 | 隐藏 helper 进程模式 |
| GPU 策略 | Linux DRI 设备检测，canary 通道默认禁用 WebView2 GPU |

**关键文件**：
- `main.go` — 桌面入口，CGO 隔离模块
- `app.go` — Wails 绑定层（43+ 导出方法供前端调用）
- `bot_bridge.go` — Bot 桌面桥接
- `tray.go` — 系统托盘
- `updater*.go` — 自动更新（各平台实现）

---

## 十、Provider 实现

### 10.1 OpenAI 兼容（`internal/provider/openai/`）

支持众多厂商，通过 `base_url` 自动识别协议：

| 厂商 | 识别特征 | 特殊行为 |
|------|----------|----------|
| DeepSeek | `api.deepseek.com` | `thinking.type=enabled` + `reasoning_effort` |
| MiniMax | `api.minimaxi.com` | `thinking.type=adaptive\|disabled` |
| Zhipu GLM | `open.bigmodel.cn` / `api.z.ai` | `thinking.type=enabled\|disabled` |
| LongCat | `api.longcat.chat` | 同上，忽略 `reasoning_effort` |
| Ollama | `ollama.com` | 支持 `reasoning_effort` scale（含 max） |
| 通用 | 其他 | 标准 `reasoning_effort`（low/medium/high） |

### 10.2 Anthropic（`internal/provider/anthropic/`）

- Messages API（`/v1/messages`）
- SSE 流式响应
- 扩展思维（extended thinking）支持，含签名回放
- 无 temperature/top_p（Claude 模型拒绝采样参数）

---

## 十一、关键设计模式

### 11.1 组装器模式（Boot）

`internal/boot/` 是**唯一的组装点**：

```go
func Build(ctx context.Context, opts Options) (*control.Controller, error)
```

- 加载配置 → 解析模型 → 构建注册表 → 创建权限门 → 组装 Agent
- 所有前端（CLI/Desktop/Serve）共用同一个 `Build`
- 确保各前端行为一致

### 11.2 事件流模式（Event）

`internal/event/` 定义了 25+ 种事件类型：

```go
type Kind int
const (
    TurnStarted     Kind = iota
    Reasoning       // 思维链文本
    Text            // 回答文本
    Message         // 完整消息
    ToolDispatch    // 工具调用开始
    ToolResult      // 工具调用结果
    Usage           // Token 用量
    ApprovalRequest // 审批请求
    AskRequest      // 提问请求
    TurnDone        // Turn 结束
    CompactionStarted/Done  // 压缩状态
    // ...
)
```

每个 `Sink` 实现者（CLI TUI / Desktop / Serve）独立决定如何渲染事件。

### 11.3 会话生命周期

```
Controller 状态机：
├── idle（等待用户输入）
├── running（Turn 进行中）
│   ├── prompting（等待模型流式响应）
│   ├── tool_calling（执行工具）
│   └── compacting（上下文压缩中）
└── paused（等待用户审批/问答）
```

- 支持 `/new` 开启新会话
- 支持 `/resume` 恢复历史会话
- 支持 `/fork` 从检查点分叉
- 支持 `Esc+Esc` 回滚

### 11.4 上下文压缩（Compaction）

`internal/agent/compact.go`：

```
压缩触发条件：prompt 长度 > window * 0.8
压缩目标：保留最近 16384 tokens 原文
压缩方式：
  1. 裁剪过大的工具输出（0.6 阈值）
  2. 模型生成结构化摘要
  3. 用摘要替换旧对话
  4. 保持前缀字节不变
```

摘要格式包含节：
- Standing facts & constraints
- Goal
- Decisions & rationale
- Files & code
- Commands & outcomes
- Errors & fixes
- Pending & next step

---

## 十二、工具链与开发

### 构建

```bash
make build      # → bin/reasonix(.exe)
make cross      # → 6 平台交叉编译
make test       # 运行测试
make fmt        # gofmt
make vet        # go vet
```

### CI 验证（本地预检）

```bash
gofmt -w .                          # 格式检查（节省 ~13s CI）
go vet ./...                        # 静态分析（节省 ~52s CI/lint）
go test ./internal/tool/builtin/ ./internal/boot/  # 工具/引导测试
```

### 重要约束

- **导入循环规则**：引入新依赖前先检查目标包的测试文件是否反向导入
- **Cache-impact PR 元数据**：修改 cache 敏感路径时 PR 必须标注影响等级
- **无过度工程**：最小代码解决问题，不加未被要求的功能

---

## 十三、数据流示例

```
用户输入 "修复 main.go 的 bug"
  │
  ▼
control.Controller.Send("修复 main.go 的 bug")
  │
  ├─► hook.UserPromptSubmit（钩子检查）
  │
  ├─► agent.Agent.Run()
  │     │
  │     ├─► 构建请求 → provider.Stream()
  │     │     └─► OpenAI/Anthropic API → SSE 流
  │     │           ├─► event.Reasoning（思维链）
  │     │           └─► event.Text（回答文本）
  │     │
  │     ├─► 模型返回 ToolCall → 权限门检查
  │     │     ├─► guardian.Session.Review()（安全审查）
  │     │     ├─► permission.Policy.Evaluate()（权限规则）
  │     │     ├─► hook.PreToolUse（钩子检查）
  │     │     └─► 需要审批 → event.ApprovalRequest
  │     │           └─► 用户批准 → tool.Execute()
  │     │                 ├─► checkpoint.Snapshot()（快照备份）
  │     │                 ├─► sandbox 沙箱执行
  │     │                 └─► hook.PostToolUse（钩子检查）
  │     │
  │     ├─► 循环直到模型认为任务完成
  │     │
  │     └─► 必要时上下文压缩（compact）
  │
  └─► event.TurnDone（Turn 完成）
```

---

## 十四、配置解析顺序

```
1. 命令行 flag（最高优先级）
2. ./reasonix.toml（项目级）
3. ~/.reasonix/config.toml（用户级，v1.8.1+）
   或 %AppData%/reasonix/config.toml（Windows）
4. 内置默认值（最低优先级）
```

秘密变量配置：
- `api_key_env` 指定环境变量名
- Reasonix 家目录下的 `.env` 文件（CLI 和桌面共享）
- 项目 `.env` 文件仅用于非 Provider 的 `${VAR}` 展开

---

## 十五、项目规模估算

| 维度 | 数据 |
|------|------|
| Go 包数量 | 50+ 个 `internal/` 包 |
| 内置工具 | 30+ 个独立工具 |
| 测试文件 | 200+ 个 `_test.go` 文件 |
| 核心行数 | 100K+ 行 Go 代码 |
| 文档数量 | 20+ 个 MD 文档 |
| 三方依赖 | 30+ 个（纯 Go） |
| 贡献者 | 50+ 人 |

---

## 总结

Reasonix 是一个**深度围绕 DeepSeek 生态优化、配置驱动、安全优先的 AI 编码智能体**。它的架构设计体现了几个突出的工程理念：

1. **接口优先 + 注册表模式** — Provider 和 Tool 彻底解耦，通过 `init()` 自注册
2. **一个 Controller 服务所有前端** — CLI、桌面、HTTP/SSE 共享同一套会话逻辑
3. **Cache 感知架构** — 极致利用 DeepSeek prefix cache，从系统提示词到压缩策略全部围绕 cache 命中率设计
4. **零信任安全模型** — 沙箱隔离 + 权限策略 + 秘密脱敏 + Guardian 审查四层防护
5. **Go 单二进制交付** — `CGO_ENABLED=0`，六平台交叉编译，无运行时依赖
6. **丰富的扩展生态** — MCP 插件、Skills 剧本、Hooks 钩子、Slash 命令四重扩展机制
7. **多渠道接入** — 除了 CLI 和桌面，还支持 QQ/飞书/微信 Bot 远程控制
