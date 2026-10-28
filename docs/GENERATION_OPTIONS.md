# Meshy 生成策略与目标面数

入口：三维模型库 → 文字 / 图片生成。已有密钥配置后可提交任务；实际调用消耗供应商账户额度，模式和面数可能影响耗时与费用，具体以供应商为准。

| 策略 | API 参数 | 目标三角面数 |
| --- | --- | --- |
| 标准几何 | 无目标时保留原有预览/图片参数；有目标时 `model_type=standard`、`should_remesh=true`、`topology=triangle` | 可留空使用供应商默认；指定时 100–300000 |
| T2 · 分件优先 | `model_type=smart-topology`、`ai_model=meshy-t2`、`topology=triangle` | 100–15000，留空显式使用 4000 |
| T2.5 · 拓扑细节 | `model_type=smart-topology`、`ai_model=meshy-t2.5`、`topology=triangle` | 100–30000，留空显式使用 15000 |

当前范围按本轮读取的 Meshy 官方文字/图片 API 文档实现，不发送已退役/即将退役的 lowpoly 选项或不受支持的四边面组合。
新策略的真实生成尚未验证。本轮通过模拟上游验证参数和结果流程，没有新增付费推理。此前已完成的标准文字生成验证不代表 T2、T2.5 或图片生成同样已验证。

## 输入与结果

- Meshy 文字生成描述上限 800 字符，前后端都做校验；不符合时在本地拒绝，不提交供应商。
- 图片模式的描述作为本地任务名称，不作为供应商图像任务的额外文字约束，上限仍为 4000 字符。图片本地限制仍为 5MB。
- 目标面数是近似目标，供应商结果可能偏离；不是严格面数承诺，也不等于工程精度。
- T2 的分件能力由供应商模型提供。本项目显示 GLB 的实际网格节点，不自动推断机械零件、连接或配合。
- AI 网格不获得 STEP B-rep 检查资格；没有原始实体几何时该功能仍禁用。
- 生成完成后显示请求策略、目标面数、实际节点和三角面数。不会将当前表单设置当作历史任务的真实设置。
- 历史旧任务没有参数记录时显示“历史任务未记录生成选项”，不会猜测它使用的供应商模型版本。

## API 与持久化

应用接口 `POST /api/model-generation` 增加可选字段：

```json
{
  "prompt": "一个包含底座和顶盖的支架",
  "generation_options": {
    "mesh_mode": "parts",
    "target_polycount": 6000
  },
  "client_request_id": "32位十六进制请求编号"
}
```

`mesh_mode` 可为 `standard`、`parts`、`detail`。`target_polycount` 可为 null 或范围内的整数；布尔、浮点、字符串、未知字段或超限组合都会拒绝。
旧客户端不传该字段时保持原来的标准预览行为，不会默认打开重建、Smart Topology 或精修任务。

任务记录在 `generation_job_options` 表中保存规范化策略与目标面数，不保存原图、完整提示词或密钥。读取任务时返回 `generation_options`，刷新和历史查看会恢复记录。
去重摘要包含实际发往上游的模式、模型和目标面数。重用同一请求编号却更换生成设置会被拒绝；核对原任务后需要主动开始新请求。
自定义 form-glb-v1 服务不接收这些 Meshy 专用参数，相关选项在界面隐藏。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -p test_mesh_options.py -v
.venv/bin/python tests/mesh_options_smoke.py
```

覆盖：标准目标触发重建、T2 默认、T2.5 参数、图片转发、非法范围与字段、800 字符限制、参数去重、记录不可变、页面刷新及历史恢复、默认向后兼容。
测试结果只证明本地合同、存储和界面流程正常，不证明真实供应商账户开放相应模型，也不衡量新模式质量或费用。

官方资料：[文字 API](https://docs.meshy.ai/en/api/text-to-3d)、[图片 API](https://docs.meshy.ai/en/api/image-to-3d)。
