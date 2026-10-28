# 自定义三维生成接口

## 无需生成服务的功能

运行 `npm ci --ignore-scripts --no-audit --no-fund` 安装锁定版本 Three.js 后，启动 `python3 server.py`。
进入“三维模型库”上传 GLB / OBJ / STL / STEP；文件保存在 `.data/models/`，索引保存在同目录 SQLite 数据库中。
模型库不覆盖装配工作台的参数项目，两者数据独立。

- STEP/STP：本地 Open Cascade 转换，源文件和 GLB 预览分别保留，详见 [STEP 接入说明](STEP_IMPORT.md)。
- GLB：2.0 格式，缓冲区与纹理必须内嵌。保留节点层级与文件材质。
- OBJ：UTF-8，保留 `o`/`g` 分组。不加载 MTL 或外部纹理。
- STL：支持 ASCII 与二进制，作为单个网格显示，不自动推断机械零件。
- 不支持 Draco / Meshopt / KTX2 等需要额外解码器的压缩扩展，需先导出普通 GLB。
- 单文件最多 50MB，视图最多 100 万三角面、300 万顶点、10000 节点。
- 鼠标左键旋转、滚轮缩放、右键平移；支持适应视图、Y/Z 向上轴、线框、选择、显隐与隔离。
- 原文件可下载。零件树来自文件节点，不能证明存在工程上的装配关系。
- GLB 通常使用米，STL/OBJ 不提供可靠单位。本工具显示原生单位，不自动推断或转换尺寸。
- 可将当前参数项目送到三维视图查看；模型库网格不会自动转成可编辑的 CAD 特征。

## 已预留的生成接口：form-glb-v1

这不是任何商业平台 API 的默认适配器。需要自有服务或额外适配层实现下述合同。
本项目没有内置模型权重、默认供应商、试用密钥或免费推理额度。

环境设置：

| 名称 | 用途 |
| --- | --- |
| `MODEL_GENERATOR_URL` | 必需；自定义生成端点完整 HTTPS URL，不能在 URL 中嵌入凭据 |
| `MODEL_GENERATOR_KEY` | 可选；服务需要授权时配置为秘密绑定，发送为 Bearer 头 |

在环境设置中安全填写，不要将密钥写入仓库或聊天。端点所在域名需要允许网络访问。
如使用代理秘密绑定，目的域名应为生成服务的确切主机名。设置后重启服务以重新读取变量。
未配置 URL 时界面禁用生成按钮，后端生成请求返回 HTTP 503；上传和查看仍可使用。

本地 API：`POST /api/model-generation`，请求为 JSON：

```json
{
  "prompt": "一个具有底座、主体和顶盖的机械组件",
  "image_data_url": null
}
```

自定义接口 `prompt` 为 1–4000 字符；Meshy 文字生成限制为 1–800 字符，图片模式的本地名称可为 1–4000 字符。可选图像使用 `data:image/png;base64,...`、JPEG 或 WebP，界面限制原图 5MB。

后端发送至配置端点：

```http
POST /configured-path
Content-Type: application/json
Accept: model/gltf-binary
Authorization: Bearer <从环境读取，不记录>
```

```json
{"prompt":"描述","image_data_url":null,"format":"glb"}
```

端点应在约 55 秒内同步返回 HTTP 2xx 和 **原始 GLB 2.0 二进制**，不是 JSON、下载链接或任务 ID。
异步任务式商业 API 需由适配层完成提交、轮询和下载，再返回 GLB。
不会跟随重定向，以免授权头被带到其他主机。TLS 验证和系统代理保持开启。

成功后保存生成文件，并向浏览器返回 HTTP 201：

```json
{"id":"32位资源标识","name":"generated.glb","extension":".glb","bytes":12345}
```

界面从本地模型库加载文件。不自动把网格解释成 CAD 零件或已通过制造验证的模型。
端点错误或输出格式错误返回 HTTP 502，不将远端响应或密钥写入错误消息。
已用模拟上游测试请求合同与文件持久化；Meshy 的真实文字生成已完成端到端验证；自定义服务仍只做模拟合同测试。

## 验证

```sh
python3 -m unittest discover -s tests -v
python3 tests/browser_smoke.py
python3 tests/viewer_smoke.py
```

浏览器测试需要 Playwright 和 `/usr/bin/chromium`，在独立临时数据库和临时端口运行。
Three.js 为 MIT 许可，固定于 package-lock.json；通过本地服务提供浏览器模块，无运行时 CDN 请求。

Meshy 生成策略、目标面数和历史参数记录详见 [GENERATION_OPTIONS.md](GENERATION_OPTIONS.md)。

## Meshy 直接接入

已实现 Meshy 异步任务适配，不再要求自行搭建中间服务。Meshy 属于第三方付费服务，消耗供应商账户额度，价格与权限以供应商后台为准。
当前发布环境已通过 Meshy 只读授权检查。2026-10-28 已完成一次真实文字预览生成：任务成功、GLB 下载入库并通过 WebGL 加载（118,076 个三角面）。此验证不代表图片生成或工程 CAD 语义已验证。

在环境设置中配置：

- `MODEL_GENERATOR_PROVIDER=meshy`（默认：未设自定义 URL 时使用 Meshy）。
- 安全填写秘密绑定 `MESHY_API_KEY`，仅发送至 `api.meshy.ai`。
- 放行 `api.meshy.ai`（任务 API）、`assets.meshy.ai`（生成文件）。`docs.meshy.ai` 用于核对官方文档。
- 保存、发布环境配置后重启服务；代理密钥只在配置的 HTTPS 目的域名注入，不能复制其占位值当作原始密钥。

界面“三维模型库 → 文字 / 图片生成”支持：

1. 文字模式：`POST https://api.meshy.ai/openapi/v2/text-to-3d`，`{"mode":"preview","prompt":"描述"}`，生成预览几何，不包含自动材质精修。
2. 图片模式：`POST https://api.meshy.ai/openapi/v1/image-to-3d`，`{"image_url":"data:image/...;base64,...","should_texture":false}`。参考图作为生成输入，界面描述仅用于本地任务命名，不作为 Meshy 图像任务的额外文字约束。
3. 将返回的 `result` 任务 ID 保存在本地数据库，通过对应端点 `GET .../{task_id}` 查询状态。
4. 任务完成后从 `model_urls.glb` 下载文件，验证格式，保存到本地模型库并加载到三维视图。

应用侧 `POST /api/model-generation` 对 Meshy 返回 HTTP 202 和本地任务对象。`GET /api/generation-jobs` 列出记录，`GET /api/generation-jobs/{id}` 查询并刷新任务。
界面约每 5 秒查询一次；服务端对轮询做 3 秒节流，不执行自动重提。刷新页面会恢复最近未完成任务。
任务失败或下载错误显示在任务记录中；点击记录可重新查询已有任务，不会创建新的收费任务。
如果提交超时但未获得任务 ID，请先在 Meshy 后台核对是否已创建任务，再决定是否重新提交，避免重复计费。

任务和资产记录保存在 `.data/projects.sqlite3`。不保存 API 密钥、参考图 data URL 或供应商签名下载地址。
下载仅接受 HTTPS `assets.meshy.ai`，不携带 API 授权头、不跟随重定向；若供应商更改文件域名，需要更新适配器并核对网络策略，不能随意信任任意下载地址。

验证：`python3 tests/ai_smoke.py` 以模拟上游覆盖提交、进度、刷新恢复、结果入库、GLB 加载及历史任务重新打开，确认只有一次提交。
这证明本地适配流程正常，不能替代真实账户授权和真实 Meshy 推理验证。
参考官方文档：[文字转三维](https://docs.meshy.ai/en/api/text-to-3d)、[图片转三维](https://docs.meshy.ai/en/api/image-to-3d)。后续测试轮已成功读取当前官方文档，并完成真实文字生成验证。供应商文档与能力可能变化，版本与模型选项应持续核对。

已有自定义接口仍可使用：设置 `MODEL_GENERATOR_PROVIDER=custom` 并配置原有 `MODEL_GENERATOR_URL`、`MODEL_GENERATOR_KEY`。


## 提交去重与真实验证记录

浏览器为每次 Meshy 生成附带 `client_request_id`，保存在会话存储中；后端 `generation_submissions` 表保留请求记录。
同一请求重试会返回已有任务；若提交结果尚未确认，则停止重提并提示先核对供应商后台。
新按钮“开始新的生成请求”用于明确发起下一次请求，不应在超时后未经核对就使用。
新增额度不足（402）、参数拒绝（400）与频率限制（429）的分类提示。

真实验证时共提交两项任务：计划中的木凳示例，以及测试隔离缺陷导致的一个额外任务；两项都已生成并保留在本地模型库，账户可能扣除两项额度。
已修复：单元测试禁用真实上游 HTTP，模型合同测试显式选择自定义模拟服务，非 AI 浏览器回归清除子进程中的真实 Meshy 配置。
后续回归不再依赖或调用真实生成账户。实际生成记录不是单元测试的重复步骤。

扩展测试发现并修复同一请求编号与不同输入混用的问题：后端保存规范化输入的 SHA-256 摘要，遇到不一致输入明确拒绝。摘要表与提交记录同库保存，不保存额外原图或完整提示词。

### 查询中断恢复

浏览器查询任务状态设有 20 秒超时。网络错误、408、429 和常见临时服务错误会按 2、4、8 秒间隔最多重试 3 次；成功查询后恢复每 5 秒轮询。404 等永久错误立即暂停查询。暂停仅影响浏览器查询，不会取消云端任务；可从任务记录重新打开。刷新页面仍会寻找未完成的任务。

重试只发送状态 GET 请求，不重发付费生成 POST。快速切换任务时，过期查询结果和错误不会覆盖当前查询状态；完成结果加载也会检查任务是否仍被选中。

验证：`tests/ai_smoke.py` 模拟两次 503 后恢复、404 立即暂停、持续 503 达到重试上限，以及刷新后恢复，断言整个流程只提交一次生成请求。测试不调用真实推理服务。
