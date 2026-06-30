# astrbot_plugin_bestnai

通过 BestNAI API（NovelAI 图片生成）在 AstrBot 中生成 AI 图片的插件。

> **作者**：存在酱  
> **联系方式**：QQ `1204999675`  
> **仓库**：https://github.com/Menkelo/astrbot_plugin_bestnai_x

## 功能特性

- 🎨 **基础生成**：`/nai <提示词>` 一键生成图片，支持中文自动翻译
- 🔤 **直接生图**：`/nai0 <英文tag>` 跳过翻译直接使用英文 tag
- ⚙️ **高级生成**：`/nai_adv` 支持自定义分辨率、步数、CFG Scale、负面提示词
- 🎭 **模型切换**：`/nai_set 3|4|4.5` 切换 NAI 模型版本
- 📐 **尺寸预设**：`/nai_size` 快速切换竖图/横图/方图等预设
- 🖼️ **画师预设**：`/nai_artist` 管理和切换画师风格串
- 🔞 **NSFW 控制**：`/nai_nsfw on|off` 控制内容过滤；关闭时自动切换至 Curated 模型（官方审查）
- ↩️ **撤回功能**：`/nai_recall` 撤回最后一张图（QQ 平台）
- ⏱️ **冷却机制**：每个用户独立冷却时间，防止滥用
- 💾 **图片保存**：可选持久化保存生成的图片

## 安装

1. 将插件目录放置到 AstrBot 的 `data/plugins/` 目录下
2. 在 AstrBot 管理面板中启用插件
3. 配置 API URL 和 API Key

## 配置

在 AstrBot 管理面板的插件配置中填写以下参数：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_url` | BestNAI API 地址 | （必填） |
| `api_key` | API 密钥（Bearer Token） | （必填） |
| `default_version` | 默认模型版本（3/4/4.5） | `4.5` |
| `default_size` | 默认分辨率预设 | `竖图` |
| `default_steps` | 默认生成步数 | `23` |
| `default_scale` | 默认 CFG Scale | `5.0` |
| `user_cooldown` | 用户冷却时间（秒） | `30` |
| `negative_prompt` | 默认负面提示词 | `lowres, bad anatomy...` |
| `save_images` | 是否保存生成的图片 | `false` |
| `save_dir` | 图片保存目录 | （空） |
| `auto_recall` | 是否自动撤回图片 | `false` |
| `auto_recall_delay` | 自动撤回延迟（秒） | `30` |
| `translator_enabled` | 启用中文自动翻译 | `false` |
| `translator_base_url` | 翻译 API 地址 | （空） |
| `translator_api_key` | 翻译 API Key | （空） |
| `artist_presets` | 画师预设列表（JSON） | `[]` |
| `default_artist_preset` | 默认画师预设名 | （空） |
| `prompt_suffix` | 提示词后缀（自动追加） | （空） |

## 指令说明

| 指令 | 说明 |
|------|------|
| `/nai <描述>` | 基础生图（支持中文自动翻译） |
| `/nai0 <英文tag>` | 跳过翻译直接生图 |
| `/nai_adv <提示词> [参数]` | 高级参数生图 |
| `/nai_set 3\|4\|4.5` | 切换会话模型版本 |
| `/nai_size <预设\|宽x高>` | 切换尺寸 |
| `/nai_nsfw on\|off` | NSFW 开关 |
| `/nai_pt on\|off` | 提示词显示开关 |
| `/nai_on` / `/nai_off` | 开关插件 |
| `/nai_recall` | 撤回最后一张图（QQ 平台） |
| `/nai_artist [序号/名称/none/reset]` | 切换/查看画师预设 |
| `/nai_status` | 当前会话状态 |
| `/nai_help` | 详细帮助 |
| `/nai_cfg` | 查看全局配置（管理员） |

### 尺寸预设

| 预设名 | 分辨率 |
|--------|--------|
| 竖图 | 832×1216 |
| 横图 | 1216×832 |
| 方图 | 1024×1024 |
| 小竖图 | 512×768 |
| 小横图 | 768×512 |
| 小方图 | 640×640 |
| 大竖图 | 1024×1536 |
| 大横图 | 1536×1024 |

### 高级生成参数

```
/nai_adv 1girl, masterpiece --size 1024x1024 --steps 28 --scale 7 --neg "bad quality"
```

| 参数 | 说明 |
|------|------|
| `--size 宽x高` | 自定义分辨率 |
| `--steps N` | 生成步数 |
| `--scale F` | CFG Scale |
| `--neg "提示词"` | 负面提示词 |

## NSFW 控制机制

- `/nai_nsfw off`（默认）：自动切换至 **NAI Curated 模型**，该模型内置官方内容审查，从模型层面过滤 explicit 内容，同时清理正向 prompt 中的 NSFW 关键词并使用最严格的 UC 预设
- `/nai_nsfw on`：使用 Full 模型，无内容限制

## 错误处理

| 错误 | 说明 | 解决方案 |
|------|------|----------|
| API Key 未配置 | 未填写 API URL 或 API Key | 在管理面板中完成配置 |
| 401 认证失败 | API Key 无效 | 检查 API Key 是否正确 |
| 402 点数不足 | 账户余额不足 | 充值或使用更小的分辨率 |
| 429 频率限制 | 请求过于频繁 | 等待后重试 |
| 503 服务器繁忙 | 服务端负载过高 | 稍后重试 |
| 超时 | 网络或服务器响应慢 | 检查网络连接 |

## 项目结构

```
astrbot_plugin_bestnai/
├── main.py               # 主入口，插件类和指令处理
├── metadata.yaml         # 插件元数据
├── _conf_schema.json     # 配置模式定义
├── requirements.txt      # Python 依赖
├── README.md             # 本文档
├── constants.py          # 常量定义
├── models.py             # 兼容层
├── core/
│   ├── generator.py      # BestNAI API 调用核心逻辑
│   ├── session_state.py  # 会话级状态管理
│   └── translator.py     # 中文提示词翻译
├── models/
│   └── config.py         # 配置数据模型
└── utils/
    └── helpers.py        # 工具函数
```

## 依赖

- `aiohttp >= 3.8.0`：异步 HTTP 客户端

## 更新日志

### v2.1.0
- 🔒 NSFW 关闭时自动切换至 Curated 模型（官方内置审查），修复 SFW 模式仍生成色图问题
- 🧹 关闭 NSFW 时自动清理正向 prompt 中的 NSFW 关键词
- ✨ 同步修复 `/nai_adv` 的 NSFW 过滤逻辑

### v2.0.0
- 重构为模块化结构
- 新增会话级状态管理
- 新增多模型版本切换（NAI3/4/4.5）
- 新增画师预设系统
- 新增中文自动翻译
- 新增自动撤回功能
- 独立化所有子命令指令

## License

MIT
