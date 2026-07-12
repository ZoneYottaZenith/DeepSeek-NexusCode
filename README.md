<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo.svg">
    <img src="docs/logo.svg" alt="NexusCode" width="480"/>
  </picture>
</p>

<p align="center">
  <strong>简体中文</strong>
  &nbsp;·&nbsp;
  <a href="./README.en.md">English</a>
</p>

<br/>

<h3 align="center">CLI Vibe Coding Agent · AI编程代理</h3>
<p align="center">单一二进制 · 配置声明式 · MCP 插件化 · 缓存深度优化<br/>即装即用的 DeepSeek Vibe Coding Agent。</p>

---

## 概述

NexusCode 是一个以 Agent 为中心设计的终端编程助手。它不是一个调用 LLM API 的脚本——它是一个完整的 Agent 运行时：包含传输无关的会话驱动层、可组合的工具抽象、纵深防御的安全模型、缓存感知的上下文管理，以及 MCP 协议的完整实现。

核心设计原则：

- **传输无关**：一个 Controller 驱动多个前端（TUI / HTTP-SSE），每个前端只需处理命令下发和事件渲染
- **接口隔离**：工具、权限、记忆、沙盒全部通过接口契约组合，运行时自注册
- **缓存优先**：围绕 DeepSeek 自动前缀缓存设计，系统 prompt 跨轮次字节级稳定

## 架构

```
┌─────────────┐  ┌──────────────┐
│  Terminal   │  │  HTTP/SSE   │
│  TUI (Bubble│  │  Server     │
│  Tea)       │  │             │
└──────┬──────┘  └──────┬───────┘
       │                │
       └────────────────┘
                        │
               ┌────────▼────────┐
               │   Controller    │  ← 传输无关的会话驱动层
               │  (control包)    │     命令 + 事件流
               └────────┬────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
   ┌──────▼──────┐ ┌───▼────┐ ┌──────▼──────┐
   │   Agent     │ │ Plugin │ │   Memory    │
   │ (工具循环)   │ │ (MCP)  │ │ (记忆系统)   │
   └──────┬──────┘ └────────┘ └─────────────┘
          │
   ┌──────┼──────────┬──────────┐
   │      │          │          │
┌──▼──┐┌─▼──┐  ┌────▼───┐ ┌───▼───┐
│Tool ││Perm│  │Sandbox │ │Check- │
│Reg  ││is- │  │(OS jail│ │point  │
│istry││sion│  │)       │ │       │
└─────┘└────┘  └────────┘ └───────┘
```

## 技术要点

### 缓存感知的上下文管理

LLM 代理的上下文窗口管理是系统设计的核心约束。NexusCode 围绕 DeepSeek 的自动前缀缓存做了针对性设计：

- **系统 prompt 字节级稳定**：基座 prompt、工具 schema、加载的记忆在整个 session 内保持字节精确一致，最大化前缀缓存命中率
- **追加优先**：大多数轮次仅在消息列表尾部追加，不修改前缀——缓存始终温热
- **三级上下文折叠**：
  | 水位 | 触发条件 | 行为 |
  |------|----------|------|
  | snip | `toolResultSnipRatio` (0.6) | 重写/截断过时的工具输出，不动对话结构，保持缓存前缀 |
  | prune | `compactRatio` (0.8) | 移除非关键的 assistant/tool 消息对 |
  | compact | `compactForceRatio` (0.9) | 调用次 LLM 将早期对话摘要为结构化简报，保持用户轮次原文 |
- **归档保护**：折叠前的原始消息序列化到 `<config>/archive/`，不丢信息

三种水位配合可配置的软/硬阈值，使得会话可以在大窗口下长时间运行而不触发 full compaction。

### 纵深防御的安全模型

安全分三层，每层职责独立、分别可测：

```
┌──────────────┐
│  Permission  │  ← 纯函数规则评估：allow / ask / deny
│  Policy      │     支持精确路径、glob、bash 命令分解
├──────────────┤
│  Gate        │  ← 包装 Policy，接入可选的交互式 Approver
│              │     三种模式：ask（默认）、auto、yolo
├──────────────┤
│  Sandbox     │  ← OS 级执行隔离：
│              │     macOS  → Seatbelt (sandbox-exec)
│              │     Linux   → bubblewrap
│              │     Windows → AppContainer (只读) / 
│              │               低完整性令牌 (写入) + Job Object
└──────────────┘
```

沙盒是真正的 OS 层 jail，受许可的命令也无法逃逸。Windows 使用独立的原生 helper 二进制实现沙盒化。

### 工具抽象设计

`tool.Tool` 接口是系统的核心抽象：

```go
type Tool interface {
    Name() string
    Description() string
    Schema() json.RawMessage      // JSON Schema 参数定义
    Execute(ctx, args) (string, error)
    ReadOnly() bool               // 读/写区分，实现批量并行调度
}
```

扩展机制通过接口类型断言实现：

- **`Previewer`**：写工具实现此接口后可提供操作预览（影响哪些文件、diff 内容），用于审批卡片渲染和 checkpoint 快照触发
- **`PlanModeClassifier`**：工具声明自己在规划阶段是否安全，规划模式默认 fail-closed

内置工具通过 `init()` 在编译期自注册到全局 registry；MCP 插件工具在运行时适配到同一 `Tool` 接口——agent 看到的只是一个统一的 `*Registry`，无差别对待。

### 快照安全网（Checkpoints）

不依赖 git 的编辑安全网。每次写工具执行前，agent 记录文件的编辑前快照：

```go
type Checkpoint struct {
    Turn     int         // 用户轮次
    MsgIndex int         // 会话消息索引——用于同时回退对话
    Files    []FileSnap  // 涉及的文件快照
}
```

- 每个 turn 独立 JSON 文件，隔离损坏风险
- 支持代码回退 + 会话回退（对话和代码一起 fork）
- 跨会话持久化，重启后仍可 rewind
- 仅跟踪可 Preview 的写操作，bash 等不可预测操作不在此列

### MCP 协议实现

完整实现了 Model Context Protocol（JSON-RPC 2.0），三种传输策略：

| 传输 | 场景 | 实现 |
|------|------|------|
| stdio | 本地子进程 | `exec.Command`，stdin/stdout JSON-RPC |
| Streamable HTTP | 远程端点 | HTTP POST，支持流式响应 |
| Legacy HTTP+SSE | 兼容 | 初始化 SSE + 调用 HTTP |

插件工具的调用超时、资源管理、断线重连由统一的 `plugin` 包管理。

### 记忆系统

分层记忆架构：

```
项目级: .nexuscode/NEXUSCODE.md
用户级: ~/.config/nexuscode/NEXUSCODE.md
全局:  ~/.nexuscode/NEXUSCODE.md
自动记忆: BM25 检索 + Memory Compiler v5 事实提取
快速记忆: #<note> 内联添加
```

记忆在 session 启动时一次性加载并注入 system prompt，session 内不修改前缀以保持缓存。

### 双模型协作

可选的规划器-执行器模式：

- **Planner**：使用只读工具集调研代码、分析依赖、制定执行计划
- **Executor**：根据计划使用完整工具集实施修改
- 两个模型运行在独立 session 中，互不干扰各自的 prompt 前缀缓存
- 规划器可通过 `[planner_requires_approval]` 请求用户审批，或通过 `<planner-ask>` 向用户提问

## 安装

### 方式一：npm 安装（推荐）

需要 [Node.js](https://nodejs.org/)（npm 随 Node.js 一起安装）。验证 npm 是否可用：

```sh
npm --version
```

如未安装，前往 [nodejs.org](https://nodejs.org/) 下载 LTS 版本，安装后重新打开终端。

```sh
npm i -g nexuscode                  # 任意平台，自动拉取预编译原生二进制
```

安装完成后直接使用：

```sh
nexuscode
```

> `npm i -g nexuscode` 自动检测当前操作系统和 CPU 架构（Windows/Linux/macOS × amd64/arm64），安装对应平台的预编译二进制。npm 只充当安装器，运行时不依赖 Node.js。

### 方式二：从源码构建

需要 [Go 1.25+](https://go.dev/dl/)。验证 Go 是否已安装：

```sh
go version
```

```sh
make build      # -> bin/nexuscode
make cross      # -> dist/（darwin|linux|windows × amd64|arm64）
```

## 快速开始

```sh
nexuscode setup                      # 交互式配置向导
export DEEPSEEK_API_KEY=sk-...
nexuscode                            # 启动交互式会话
nexuscode run "实现 main.go 里的 TODO"
echo "解释这段代码" | nexuscode run
```

## CLI 参考

| 命令 | 描述 |
|------|------|
| `nexuscode` | 交互式会话（Bubble Tea TUI） |
| `nexuscode run <task>` | 单次任务执行 |
| `nexuscode review` | AI 代码审查（基于 git diff） |
| `nexuscode serve` | HTTP/SSE 服务 |
| `nexuscode setup` | 配置向导 |
| `nexuscode config` | 运行时配置管理 |
| `nexuscode mcp` | MCP 服务器管理 |
| `nexuscode doctor` | 环境诊断 |
| `nexuscode upgrade` | 自更新 |

## 配置

配置声明式，所有 provider、agent 参数、工具开关、插件声明均在 `nexuscode.toml` 中。

```toml
default_model = "deepseek"

[[providers]]
name        = "deepseek"
kind        = "openai"
base_url    = "https://api.deepseek.com"
models      = ["deepseek-v4-flash", "deepseek-v4-pro"]
default     = "deepseek-v4-flash"
api_key_env = "DEEPSEEK_API_KEY"
context_window = 1000000
```

优先级：**flag > 项目 `nexuscode.toml` > 用户配置 > 内置默认**。密钥通过环境变量或 `<NexusCode home>/.env` 管理，不写入配置文件。

---

<p align="center">
  <sub>MIT — 见 <a href="./LICENSE">LICENSE</a></sub>
</p>
