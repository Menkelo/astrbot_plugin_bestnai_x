# Third-Party Notices

## Infinite-Canvas

The project workspace, canvas-card layout, canvas-creation transition, editor page structure, visual system, node presentation, viewport controls, DOM minimap, multi-selection, group dragging, creation menu, and connection interactions are reproduced and adapted from:

- Project: `hero8152/Infinite-Canvas`
- Source: https://github.com/hero8152/Infinite-Canvas
- Original author: `hero8152`
- License: the custom license distributed in the upstream repository at https://github.com/hero8152/Infinite-Canvas/blob/main/LICENSE

The upstream license prohibits commercial use without authorization, requires derivative software to remain open source, and requires attribution to the original author. This notice applies to the reproduced canvas frontend; the AstrBot integration, NovelAI generation flow, plugin services, and data model remain part of this plugin.

### Upstream License Text

> 禁止商业用途
>
> Commercial use is prohibited.
>
> 可以自己使用和公司使用，禁止用于任何形式的修改封装成商业产品，商用须取得授权。
>
> 根据代码二次开发的软件必须保持开源并注明来源作者
>
> This software is for personal and company use only, but is prohibited from being modified or packaged into commercial products in any way. Commercial use requires authorization.
>
> Software developed based on this code must remain open source and the original author must be credited.

## Lucide

The canvas bundles Lucide `1.16.0`, copied from the Infinite-Canvas local vendor mirror and used for interface icons.

- Project: `lucide-icons/lucide`
- Source: https://github.com/lucide-icons/lucide
- License: ISC

The bundled file retains its upstream license header.

## Danbooru Tag Search (hosted service)

Chinese prompt translation queries an embedded third-party tag-retrieval service to
collect candidate Danbooru tags before calling the translation model. No code from the
service is redistributed with this plugin; it is called over HTTPS at runtime.

- Service: `sakizuki/danboorusearch`
- Source: https://huggingface.co/spaces/sakizuki/danboorusearch
- Endpoint: `https://sakizuki-danboorusearch.hf.space`
- Hosting: Hugging Face Spaces

Requests contain only the prompt text being translated. No API keys, user identifiers,
or images are sent. The service is optional at runtime: when it is unreachable, returns
a non-200 status, or times out, retrieval is skipped silently and translation falls back
to the model's own knowledge.
