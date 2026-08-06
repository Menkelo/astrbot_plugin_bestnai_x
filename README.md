# astrbot_plugin_bestnai_x

在 AstrBot 中通过 OpenAI 兼容接口生成 NovelAI 风格图片，固定使用 `nai-diffusion-4-5-full`。

原版仓库：[cunzaijiang/astrbot_plugin_bestnai](https://github.com/cunzaijiang/astrbot_plugin_bestnai)

---

## 功能特性

- **基础生图**：`/nai <提示词>` 一键生图。
- **原始提示词生图**：`/nai0 <英文tag>` 跳过中文翻译，不追加画师串与质量提示词，仅沿用负面提示词。
- **中文自动翻译**：开启后，`/nai` 中的中文描述会被自动翻译为 Danbooru / NovelAI 英文 tag。
- **图片反推生图**：发送/回复一张图片后执行 `/nai`，自动用视觉模型把图片反推为 tags 再生图；反推时会先识别画面中的已知角色，命中则把角色与作品 tag 排在最前。
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

AstrBot `4.26.0+` 会在插件详情页直接提供 `Canvas` Page。画布支持多个相互独立并自动保存的项目，以及提示词、图片、备注节点和自由连线；最近使用的项目、画幅比例和画师预设会持久化，重新打开后继续沿用。

核心功能：

- 连接 `图片 -> 提示词 -> 反推图片` 后点击"生成"，会识别原图 tags、合并新提示词并生成结果；原图未变化时复用反推缓存，中文提示词未变化时复用翻译缓存。手写的提示词会自动加上正向权重，不会被反推出的几十个 tags 淹没。
- **原图内嵌参数复用**：上传的图片若是未经压缩的 NovelAI 原始 PNG，反推时会直接读出其中的种子与原始提示词，跳过视觉模型反推，用「原始提示词 + 你手写的提示词 + 同一种子」重新生成，还原度远高于反推。图片被转存为 JPEG/WebP 或经平台压缩后元数据即丢失，此时自动回退到正常反推。
- **迭代步数与引导系数**：提示词卡片内的「高级选项」里各自配置，滑动条形态，逐卡片独立并随工作区保存；未调整过的卡片沿用插件配置的默认值。
- 图片卡片底部显示该图的**种子 ID**，可用于复现；点击图片可查看完整提示词与英文 tags。
- 素材库支持图片预加载、电脑端拖入画布和手机端预览后放入画布。手机端支持单指平移与双指缩放。
- 生图或反推期间，已有图片的下载按钮会锁定；点击时只在状态栏提示，任务完成后自动恢复，避免下载操作中止生成请求。
- **调试模式**：仅在画布顶栏通过 bug 按钮开关；运行后底部状态栏会折叠显示当前节点的阶段耗时、提示词流水、请求参数和上游报错原文，后端仅在该次画布请求开启时返回调试数据。
- 常用操作：双击空白处新建提示词，中键拖动画布，右键添加节点，滚轮缩放，`Ctrl/⌘ + Enter` 生成，`Ctrl/⌘ + Z` 撤销，`Ctrl/⌘ + Shift + Z` 重做，`Delete` 删除选中节点。

Canvas Web API 不使用 QQ 平台专用的安全过滤；QQ 上的 `/nai` 与 `/nai0` 仍使用完整防封流程。画布交互参考并适配自 [hero8152/Infinite-Canvas](https://github.com/hero8152/Infinite-Canvas)，许可与归属见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。单个工作区最多 160 个节点、320 条连线，单张上传图片最大 15 MB。

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

> **生图接口二选一**：要么开启"优先使用提供商"并选择提供商，要么关闭后同时填写 `api_url` + `api_key`。两者都未配置时，`/nai` 会提示"插件未配置"。

### 2. generation_config - 生图参数

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `sampler` | string | `k_euler_ancestral` | 采样器。可选：`k_euler_ancestral`（推荐默认，随机性较强，二次元效果稳定）、`k_euler`（更稳定干净，随机性较低）、`k_dpmpp_2s_ancestral`（细节和质感较好，随机性较强，但部分代理可能不支持） |
| `default_ratio` | string | `2:3 (832×1216)` | 默认比例，当提示词未指定比例时使用。可选：`16:9 (1216×704)`、`9:16 (704×1216)`、`4:3 (1024×768)`、`3:4 (768×1024)`、`3:2 (1216×832)`、`2:3 (832×1216)`、`1:1 (1024×1024)` |
| `max_concurrency` | int | `1` | 生图并发限制。同一时刻最多同时进行的生图任务数，超出时新的生图请求会排队等待。默认 1（串行） |

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

> **角色识别**：反推时模型会先判断画面主体是否为可辨认的已知角色，是则把 canonical Danbooru 角色 tag 与作品 tag 排在提示词最前面，显著提升还原度。
> 判断不确定、或主体是原创角色 / 真人时会留空，不会瞎猜。识别结果不单独发送，只写入日志。
> 模型未按结构化格式返回时自动退回纯 tags，不影响生图。
>
> **手写提示词加权**：反推产出的 tags 往往有几十个，你自己写的那几个词容易被淹没。
> 因此反推时会用 NovelAI 数值权重语法把你手写的描述包起来（`1.3::你的提示词::`），让它在最终 prompt 里的影响力与"主动要求"相称。比例与画师名不参与加权，仍按原样解析。

### 6. safety_config - QQ 防封安全审核配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 启用发送前图片安全审核。强烈建议 QQ 机器人开启。开启后生成图片会先审核，安全才发送；审核接口报错/超时时放行 |
| `provider_id` | string | 空 | 视觉审核提供商，需选择支持视觉输入的 AstrBot 提供商。审核不使用手动生图 API |
| `prompt_block_enabled` | bool | `true` | 启用提示词敏感词过滤。开启后，用户提示词命中明显 NSFW 关键词会自动移除，并继续生成 |
| `prompt_block_words` | list | 内置检测词列表 | QQ 平台提示词过滤使用的检测词，可在插件配置中逐项添加、修改或删除；列表留空时不移除任何词 |

> **Danbooru Tag 检索**已内嵌，翻译中文提示词时自动启用，无需配置。
> 检索服务由第三方提供：[sakizuki/danboorusearch](https://huggingface.co/spaces/sakizuki/danboorusearch)（`https://sakizuki-danboorusearch.hf.space`），
> 托管于 Hugging Face Spaces。请求只包含待翻译的提示词文本，不包含任何 API Key；
> 服务不可用或超时时自动跳过，仅靠模型自身知识翻译，不影响生图。

### 调试模式（仅画布）

调试模式不出现在插件配置面板中，只能在画布顶栏通过 bug 按钮开关。开启后，每次生图 / 反推都会在底部调试栏留下这一轮的流水，同样的内容也会打进 AstrBot 后端日志：

- **各阶段耗时**：反推、生图各花了多久，以及总耗时
- **提示词流水**：输入原文 → 标签结果 → 拼上画师预设和质量词后的最终提示词
- **请求参数**：模型、尺寸、迭代步数、引导系数、种子，以及反推用的提供商与模型
- **上游报错原文**：平时只显示「内容没通过服务商的审核」这类可操作的结论，调试模式下额外附上接口返回的原始报文

调试栏里的「复制全部」按钮会把整段流水拷成纯文本，反馈问题时直接贴出来即可。
日志与面板中的 API Key（URL 查询串、`Bearer`、`api_key` 字段、`sk-` 开头的裸 Key）都会被替换成 `***`。
调试信息只活在内存里，不写进工作区存档，刷新页面即消失。

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

**比例优先级**（从高到低）：

1. 用户在生图提示词中显式写下的比例 / 尺寸。
2. 当前生效的画师预设提示词中附带的比例。
3. 图片反推时，从输入图片尺寸推断出的比例。
4. 以上都没有时，使用 `generation_config.default_ratio`。

> 画师预设串中的比例写法与提示词一致，例如 `可爱:artist:ciloranko, 16:9`。命中画师比例后会自动从最终 prompt 中移除比例 token，仅影响生图尺寸。
>
> 第 2 条优先于第 3 条：画师预设是你自己配置的，属于明确意图；从输入图片推断的比例只是程序的猜测，不会覆盖画师串里写好的比例。只有你在提示词里手写比例才能盖过画师预设。

### 画师预设用法

| 操作 | 输入示例 | 说明 |
|------|----------|------|
| 切换本会话默认预设 | `/nai 可爱` | 将该预设设为**当前群 / 私聊**的默认（持久化保存，重启后仍生效）。不影响其他群 |
| 临时调用预设 | `/nai 可爱 miku` | 本次生成使用"可爱"预设，提示词为 `miku` |
| 方括号临时调用 | `/nai [可爱] miku` | 效果同上，方括号内为预设名 |
| 清除本会话默认 | `/nai 默认`、`/nai 恢复默认`、`/nai 重置画师预设` | 清除当前会话已保存的默认预设，恢复使用配置默认 |

> 默认画师预设**按会话隔离**：每个群和私聊各自保存一份，一个群里切换不会影响其他群。无限画布没有会话概念，使用配置中的第一个预设作为默认。

---

## 安全审核机制

本插件为 QQ 场景提供了三层安全机制：

1. **提示词敏感词过滤**（`prompt_block_enabled`，默认开）
   - 用户提示词命中 `prompt_block_words` 中配置的词时，自动移除并继续生成；检测词列表可在插件配置中直接维护，留空即可不移除任何词。
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
| 提示词翻译 / 图片反推失败 | 上游接口拒绝，常见于内容审核、Key 失效、额度不足 | 报错已换成可操作的中文结论；要看接口返回的原文请在画布顶栏打开调试模式 |

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
│   ├── api_errors.py        # 上游报错可读化 + API Key 脱敏
│   ├── debug_trace.py       # 调试模式的耗时/提示词流水记录
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
    ├── preferences.json     # 最近项目、画幅比例与画师预设
    ├── workspaces/          # 按画布 ID 隔离的工作区 JSON
    └── assets/              # 上传图与生成图资源
```

---

## 依赖

- `aiohttp >= 3.8.0`：异步 HTTP 客户端
- `pillow`：画师画廊合成、图片尺寸读取
