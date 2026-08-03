# astrbot_plugin_bestnai_x

BestNAI 插件特异版（`astrbot_plugin_bestnai_x`）：通过兼容 OpenAI 格式的生图 API 在 AstrBot 中生成 NovelAI 风格（NAI Diffusion）图片。

本插件为 [astrbot_plugin_bestnai](https://github.com/cunzaijiang/astrbot_plugin_bestnai) 原版插件的特异版。

与原版的不同点：

- 固定使用 `nai-diffusion-4-5-full` 模型，不支持 3 / 4 等历史版本切换。
- 生图接口优先走 `/images/generations`，不可用时自动回退到 `/chat/completions`。
- 内置一套为 QQ 使用场景设计的防封安全审核机制（提示词敏感词过滤 + 图片发送前视觉审核）。

---

## 功能特性

- **基础生图**：`/nai <提示词>` 一键生图。
- **原始提示词生图**：`/nai0 <英文tag>` 跳过中文翻译，不追加画师串与质量提示词，仅沿用负面提示词。
- **中文自动翻译**：开启后，`/nai` 中的中文描述会被自动翻译为 Danbooru / NovelAI 英文 tag。
- **图片反推生图**：发送/回复一张图片后执行 `/nai`，自动用视觉模型把图片反推为 tags 再生图。
- **头像反推生图**：`/nai @某人` 使用对方 QQ 头像反推 tags 生图。
- **画师预设系统**：配置中可维护多个画师风格串，支持切换默认预设、按次临时调用、持久化保存。
- **画师画廊**：为每个画师预设设置预览图，可一键查看全部预设的合成画廊图。
- **比例智能解析**：提示词中可直接写比例/尺寸（`16:9`、`横屏`、`1024x1024`、`--ratio` 等），并自动校验与锚定合法分辨率。
- **安全审核**：提示词敏感词自动过滤，图片发送前调用视觉模型审核，从源头与出口双向降低封号风险。
- **Danbooru Tag 检索**：翻译中文提示词时自动注入 Danbooru 在线检索的候选 tag（服务已内嵌，默认启用），提升翻译质量。
- **生图接口容错**：主接口 `/images/generations` 不可用时自动回退到 `/chat/completions`；对返回的 base64、URL、Markdown、data URL 等多种图片格式均可解析。
- **Infinite Canvas 工作台**：以项目管理多个相互独立的持久化画布，并提供提示词、图片与备注节点以及图片/提示词素材库。

---

## Infinite Canvas

AstrBot `4.26.0` 及以上版本会在插件详情页识别 `Canvas` Page，不需要单独启动 Web 服务。打开 Page 后直接进入最近使用的画布；左上角项目菜单用于新建、切换和删除彼此独立的画布项目，切换过程不会重新加载 Page。

项目工作台支持：

- 顶部项目切换菜单与全屏深色点阵画布，布局、卡片和新建过渡复刻自 `hero8152/Infinite-Canvas`；项目管理按需展开，不占用画布空间。
- 新建、切换和删除画布项目；每个项目使用独立工作区文件，节点、连线和视口状态互不影响。
- 单一顶部状态栏显示带阴影的插件 Logo 和插件名称，灰字保留作者与版本，连接状态灯紧跟在灰字之后且不会被裁切；项目菜单位于清空画布按钮右侧，绿灯表示连接正常，红灯表示连接中断。

独立画布支持：

- 双击空白处或点击工具栏创建提示词节点；节点可独立选择比例、画师预设与原始提示词模式，悬停“原始提示词”可查看其用途。
- 提示词节点可开启“角色保持”并填写可选角色名：填写时视觉模型优先输出该角色的标准角色与作品 tags；留空时模型先识别角色身份，无法确认时保留显著外观特征。
- 图片节点右侧可连接提示词节点左侧；此时点击“反推”或普通“生成”都会按 QQ 反推流程把用户的新提示词与原图 tags 合并，再从提示词节点右侧生成“反推图片”节点，形成 `图片 -> 提示词 -> 反推图片` 链路。
- 提示词节点提供可展开的“英文 tags”区域，生成或反推后会保存翻译得到的英文 tags；展开时自动增高，收起时恢复展开前高度，展开状态和节点尺寸会一并保存，修改主提示词时自动清除过期结果。
- 提示词节点右上显示当前使用的画师预设；生成图会保存后端实际采用的预设名，并在图片节点、放大详情和素材缩略图中显示。
- 生成结果自动创建为图片节点，并与来源提示词建立连线；连续生成会向下寻找空位，避免后生成的图片卡片覆盖已有结果。聊天命令与画布共用翻译、画师预设和并发限制。
- 画布页面整体复刻自 `hero8152/Infinite-Canvas`：浮动工具栏、全屏点阵画布、圆角节点、外置端口、贝塞尔连线与 DOM 小地图均采用其页面结构和表现方式。
- 鼠标滚轮缩放、拖动空白区域平移、Ctrl 框选、Ctrl 点击多选、成组拖动、批量删除、撤销/重做与自动整理选中节点；编辑提示词或备注时，撤销/重做仅作用于当前文本。
- 点击任意节点会将其提升到最上层，重叠节点可按当前操作顺序切换前后层级。
- 双击空白处可创建提示词节点；右下角小地图支持点击和拖动定位，点击连线中点的删除按钮或双击线身可删除连线。
- 拖放或选择本地图片创建图片节点；图片节点支持右下角等比例对角缩放，备注节点可用于记录迭代方向。
- 图片与提示词使用同一个素材列表并支持统一搜索；素材图片在页面启动后后台预加载，点击打开原图、原始提示词与英文 tags 详情，拖到画布才创建图片节点。不同宽高比的素材卡片保持各自高度，空素材库使用无边框居中状态；面板仅通过顶部“素材库”按钮展开或收起。
- 图片放大详情点击内容外空白即可关闭；提示词与英文 tags 支持按钮复制和鼠标拖选复制。纯英文提示词不再重复展示两份相同文本，只保留英文 tags。
- 工作区自动保存到插件数据目录，并支持 JSON 导入/导出。

Canvas Web API 不应用 QQ 平台专用的敏感词过滤、固定安全负面词和出图审核；用户配置的普通负面提示词仍然生效。QQ 平台上的 `/nai` 与 `/nai0` 指令继续使用完整防封流程。

画布的小地图导航与连线交互参考并适配自 [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas)，许可与归属说明见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。

常用快捷操作：

| 操作 | 快捷键 |
|------|--------|
| 生成当前提示词节点 | `Ctrl/⌘ + Enter` |
| 保存工作区 | `Ctrl/⌘ + S` |
| 撤销 / 重做 | 非文本编辑状态下使用 `Ctrl/⌘ + Z` / `Ctrl/⌘ + Shift + Z`；文本编辑时仅撤销或重做输入内容 |
| 适配全部节点 | `Ctrl/⌘ + 0` |
| 删除选中节点 | `Delete` / `Backspace` |

画布 JSON 只保存节点、连线和图片资源 ID；图片文件独立保存在插件数据目录的 `canvas/assets/` 下，避免 Base64 内容反复写入工作区文件。单个工作区最多 160 个节点、320 条连线，单张上传图片最大 15 MB。

---

## 安装

最低要求：AstrBot `4.26.0`。插件 Page 基础能力始于 AstrBot `4.24.1`，但本插件还使用了 `astrbot.api.web` 服务注册接口，因此完整功能不支持低于 `4.26.0` 的版本。

1. 将插件目录放置到 AstrBot 的 `data/plugins/` 目录下（目录名应为 `astrbot_plugin_bestnai_x`）。
2. 在 AstrBot 管理面板的插件列表中启用本插件。
3. 在插件配置中完成**生图接口**配置（推荐使用 AstrBot 提供商）。

依赖安装：

```bash
pip install aiohttp pillow
```

> `pillow` 仅用于画师画廊合成与读取图片尺寸；如果不需要画廊/比例推断功能，理论上可缺省，但强烈建议安装。

---

## 配置说明

在 AstrBot 管理面板的插件配置中填写以下参数。配置按模块分组，`_conf_schema.json` 为配置模式定义。

### 1. api_config - 生图接口配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `prefer_provider` | bool | `true` | 开启时生图使用下方选择的 AstrBot 提供商；关闭时使用手动 API |
| `provider_id` | string | 空 | 生图接口提供商，需在 AstrBot 中选择。仅当"优先使用提供商"开启时生效 |
| `api_url` | string | 空 | 手动生图 API 地址。填写兼容 OpenAI 格式的 API Base，例如 `https://example.com/v1`。关闭"优先使用提供商"后生效，该服务需支持 `/chat/completions` |
| `api_key` | string | 空 | 手动生图 API Key。关闭"优先使用提供商"后，需与 `api_url` 同时填写才生效 |
| `max_concurrency` | int | `1` | 生图并发限制。同一时刻最多同时进行的生图任务数，超出时新的生图请求会排队等待。默认 1（串行） |

> **生图接口二选一**：要么开启"优先使用提供商"并选择提供商，要么关闭后同时填写 `api_url` + `api_key`。两者都未配置时，`/nai` 会提示"插件未配置"。

### 2. generation_config - 生图参数

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `sampler` | string | `k_euler_ancestral` | 采样器。可选：`k_euler_ancestral`（推荐默认，随机性较强，二次元效果稳定）、`k_euler`（更稳定干净，随机性较低）、`k_dpmpp_2s_ancestral`（细节和质感较好，随机性较强，但部分代理可能不支持） |
| `default_ratio` | string | `2:3 (832×1216)` | 默认比例，当提示词未指定比例时使用。可选：`16:9 (1216×704)`、`9:16 (704×1216)`、`4:3 (1024×768)`、`3:4 (768×1024)`、`3:2 (1216×832)`、`2:3 (832×1216)`、`1:1 (1024×1024)` |

### 3. prompt_config - 提示词拼接配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `quality_prompt` | string | `best quality, amazing quality, very aesthetic, absurdres` | 质量提示词，自动追加到最终正面提示词末尾，留空则不追加。发送前会自动清理非 ASCII 字符 |
| `negative_prompt` | string | `lowres, bad anatomy, bad hands, text, error, missing fingers` | 全局生效的负面提示词。代码会固定追加 QQ 安全负面词。发送前会自动清理非 ASCII 字符 |
| `artist_presets` | list | 内置 5 个示例预设 | 画师预设列表，每项格式为 `预设名:画师提示词` |

**内置画师预设示例**：

```text
可爱:artist:ciloranko , [artist:sho_(sho_lwlw)], [[artist:tianliang_duohe_fangdongye]],[[[[[[artist:kani_biimu]]]]]]
幼态:artist: ciloranko, [artist: tianliang duohe fangdongye], [artist: sho_(sho_lwlw)], [artist: baku-p], [artist:tsubasa_tsubasa], [[artist:as109]], [[artist:rhasta]]
水彩:{hokori sakuni}, {ciloranko}, {ke-ta}, {houkisei},{kedama milk}
海报:artist:ciloranko, {artist:menthako}, {artist:tianliang duohe fangdongye}, [artist:sho (sho lwlw)], [artist:baku-p], [[[artist:tsubasa tsubasa]]], artist: kemo camotli
鲜艳色彩:[artist:ningen_mame], {{{ciloranko}}}, [artist:sho_(sho_lwlw)], [[artist:rhasta]], [artist:wlop], [artist:ke-ta]
```

### 4. translator_config - 中文提示词翻译配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 开启后 `/nai` 中的中文描述会自动调用翻译器转为英文 Danbooru tag |
| `provider_id` | string | 空 | 翻译接口提供商（AstrBot 提供商）。翻译不使用手动生图 API |

> 翻译支持 OpenAI 兼容接口与 Gemini 官方接口（`generativelanguage.googleapis.com`），翻译失败自动重试（默认最多 3 次，指数退避）。

### 5. image_retag_config - 图片反推提示词配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 开启后，`/nai` 引用图片或附带图片时，会先调用视觉模型把图片反推为 NovelAI / Danbooru tags，再进行生图 |
| `provider_id` | string | 空 | 图片反推接口提供商，需选择支持视觉输入的 AstrBot 提供商 |
| `show_result` | bool | `false` | 开启后会在生图前发送反推得到的 tags，便于调试 |

### 6. safety_config - QQ 防封安全审核配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 启用发送前图片安全审核。强烈建议 QQ 机器人开启。开启后生成图片会先审核，安全才发送；审核接口报错/超时时放行 |
| `provider_id` | string | 空 | 视觉审核提供商，需选择支持视觉输入的 AstrBot 提供商。审核不使用手动生图 API |
| `prompt_block_enabled` | bool | `true` | 启用提示词敏感词过滤。开启后，用户提示词命中明显 NSFW 关键词会自动移除，并继续生成 |

> Danbooru Tag 检索服务已内嵌（`https://sakizuki-danboorusearch.hf.space`），翻译中文提示词时默认启用，无需额外配置。

---

## 指令说明

| 指令 | 说明 |
|------|------|
| `/nai <提示词>` | 基础生图。支持中文自动翻译、画师预设、比例解析；发送/回复图片或 `@某人` 时自动进入图片反推流程 |
| `/nai0 <英文tag>` | 原始提示词模式。跳过翻译，不追加画师串和质量提示词，仍沿用负面提示词与安全审核 |
| `/画师画廊` | 查看全部画师预设的合成预览画廊图 |
| `/查看画师 <预设名>` | 查看指定画师预设的画师串和预览图 |
| `/设置画师 <预设名>` | 为指定画师预设设置预览图，需同消息附带图片或回复图片 |

### /nai 生图流程

```
/nai <提示词>
        │
        ├─ 带图片 ──► 反推图片为 tags ──┐
        ├─ @某人 ──► 反推 QQ 头像为 tags ─┤（自动推断输入图片比例）
        │                                 ▼
        │                           合并 提示词 + 反推 tags
        ▼
   解析提示词
        ├─ 提取比例/尺寸（支持多种写法）
        ├─ 提取画师预设（临时调用 / 默认预设）
        ├─ 安全过滤：敏感词自动移除
        ├─ 中文？──► 翻译为英文 Danbooru tag（自动注入内嵌 Danbooru 检索结果）
        ├─ 拼接最终 prompt：画师串 + 提示词 + 质量提示词
        ▼
   调用生图 API（/images/generations，失败自动回退 /chat/completions）
        ▼
   图片安全审核（视觉模型，可选）
        ▼
   发送图片
```

### 比例 / 尺寸写法

默认使用 `generation_config.default_ratio`。以下写法可在提示词中指定比例或尺寸，插件会自动识别并从最终提示词中移除：

| 写法 | 示例 |
|------|------|
| 比例数字 | `16:9`、`9:16`、`4:3`、`3:4`、`3:2`、`2:3`、`1:1` |
| 中文/英文别名 | `横屏`、`横图`、`竖屏`、`竖图`、`方图`、`方形`、`landscape`、`portrait`、`square` |
| `--ratio` 参数 | `--ratio 16:9 (1216×704)`、`--ratio 2:3` |
| `--size` / `--ar` 参数 | `--size 1024x1024`、`--ar 1:1` |
| 方括号标注 | `[2:3]`、`[1024x1024]` |
| 裸尺寸 | `1024x1024` |

**尺寸校验规则**（自动执行）：

- 宽高必须为正整数，且为 64 的倍数。
- 面积不超过 `1,100,000` 像素。
- 不合法时自动锚定到最接近的合法比例预设，并输出警告日志。

**比例优先级**：

1. 用户在生图提示词中显式写下的比例 / 尺寸优先。
2. 未写时，若当前生效的画师预设提示词中附带了比例，则使用画师预设中的比例。
3. 两者均无时，使用 `generation_config.default_ratio`。

> 画师预设串中的比例写法与提示词一致，例如 `可爱:artist:ciloranko, 16:9`。命中画师比例后会自动从最终 prompt 中移除比例 token，仅影响生图尺寸。

### 画师预设用法

| 操作 | 输入示例 | 说明 |
|------|----------|------|
| 切换默认画师预设 | `/nai 可爱` | 将该预设设为默认（持久化保存，重启后仍生效） |
| 临时调用预设 | `/nai 可爱 miku` | 本次生成使用"可爱"预设，提示词为 `miku` |
| 方括号临时调用 | `/nai [可爱] miku` | 效果同上，方括号内为预设名 |
| 清除默认预设 | `/nai 默认`、`/nai 恢复默认`、`/nai 重置画师预设` | 清除已保存的默认画师预设，恢复使用配置默认 |

---

## 安全审核机制

本插件为 QQ 场景提供了三层安全机制：

1. **提示词敏感词过滤**（`prompt_block_enabled`，默认开）
   - 用户提示词命中明显 NSFW / explicit 关键词（中英文均有维护）时，自动移除并继续生成。
   - 提示词过滤后为空时会提示用户补充安全提示词。

2. **图片发送前视觉审核**（`enabled`，默认开）
   - 生成图片后、发送前，调用所选视觉提供商对图片进行安全判定。
   - **只有审核模型明确返回 `safe=false` 时才拦截**；审核供应商未配置、接口报错、超时、SSL 错误、结果解析失败、不支持的供应商类型均**放行**，避免误伤正常图片。
   - 拦截时回复固定文案：`未能通过安全检测，已拦截`。

3. **负面提示词固定追加 QQ 安全负面词**
   - 无论用户如何配置负面提示词，代码都会在发送前固定追加 `nsfw, explicit, nude, naked, ...` 等安全负面词，从模型层面压低出图风险。

---

## 错误处理

| 错误 | 说明 | 解决方案 |
|------|------|----------|
| 插件未配置 | 未开启"优先使用提供商"也未选择提供商，或手动 API 填写不完整 | 完成 `api_config` 配置 |
| API Key 错误（401/403） | API Key 无效 | 检查 API Key 是否正确 |
| 点数不足 | 账户余额不足（错误信息含 quota/余额/insufficient） | 充值或使用更小的分辨率 |
| 频率限制（429） | 请求过于频繁 | 等待后重试 |
| 服务器繁忙（5xx） | 服务端负载过高 | 稍后重试 |
| 生图请求超时 | 网络或服务器响应慢（300s 超时） | 检查网络连接，稍后重试 |
| 接口不支持（400/404/405/501 等） | `/images/generations` 不可用 | 插件会自动回退到 `/chat/completions`；若仍失败请检查 API Base 是否支持文生图 |

---

## 项目结构

```
astrbot_plugin_bestnai_x/
├── main.py                  # 主入口：插件类、指令注册、生图主流程
├── metadata.yaml            # 插件元数据
├── _conf_schema.json        # 配置模式定义（管理面板渲染依据）
├── requirements.txt         # Python 依赖
├── README.md                # 本文档
├── constants.py             # 常量定义
├── models.py                # 兼容层
├── gallery_renderer.py      # 画师画廊图片合成（Pillow）
├── image_store.py           # 图片持久化与发送辅助
├── models/
│   └── config.py            # 配置数据模型（PluginConfig / GenerationConfig / SafetyConfig 等）
├── core/
│   ├── generator.py         # 生图 API 调用核心（/images/generations + /chat/completions 回退）
│   ├── safety.py            # 安全审核（提示词过滤 + 图片视觉审核 + 负面词追加）
│   ├── translator.py        # 中文提示词翻译 + Danbooru tag 检索
│   └── image_retagger.py    # 图片反推提示词
└── services/
    ├── artist_gallery.py    # 画师画廊服务（预览图管理与画廊生成）
    ├── image_extract.py     # 从事件中提取图片
    ├── image_ratio.py       # 图片尺寸读取与比例推断
    ├── mention_avatar.py    # 提取 @ 用户与 QQ 头像 URL
    ├── prompt_builder.py    # 最终 prompt 拼接、ASCII 清理、临时文件管理
    └── runtime_state.py     # 运行时状态持久化（默认画师预设）
```

### 数据目录

插件运行时数据保存在 AstrBot 的 `data/plugin_data/astrbot_plugin_bestnai_x/`：

```
data/plugin_data/astrbot_plugin_bestnai_x/
├── runtime_state.json       # 运行时状态（默认画师预设持久化）
├── artist_preview_map.json  # 画师预设预览图映射
├── artist_previews/         # 画师预设预览图片
├── artist_gallery/          # 画师画廊合成图与指纹元数据
└── canvas/
    ├── projects.json        # 项目目录
    ├── canvases.json        # 画布目录、位置与回收站状态
    ├── library.json         # 图片与提示词素材库元数据
    ├── workspaces/          # 按画布 ID 隔离的工作区 JSON
    └── assets/              # 上传图与生成图资源
```

---

## 依赖

- `aiohttp >= 3.8.0`：异步 HTTP 客户端
- `pillow`：画师画廊合成、图片尺寸读取
