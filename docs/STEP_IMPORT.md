# STEP / STP 接入

在“三维模型库 → 上传三维模型 / STEP”中选择 `.step` 或 `.stp`（不区分大小写）。
无需 AI 服务、密钥或外部转换服务；转换在当前机器执行，不将文件发给第三方。

## 转换和保留

- 原始 STEP 按上传字节保存，可随时“下载原文件”。
- Open Cascade 读取 B-rep、文件提供的名称、颜色和装配实例位置，生成单独 GLB 预览。
- 文件提供层级时，零件树保留该层级；若源文件只有一个实体，不会凭空拆成装配。
- 可下载预览 GLB，并在模型库中重新打开，无需每次重新转换。
- STEP 单位由内核转换到毫米，再输出为以米为单位的 GLB；界面标注预览单位。向上轴默认 Z，可切换。
- 35 项当前测试包括真实 AP203 / AP214 / AP242 示例、嵌套装配、实例位移、曲面、颜色、毫米/厘米换算；这不保证所有软件导出的 STEP 都能完整转换。

另可执行 [原始 STEP 实体检查](CAD_INSPECTION.md)，读取体积/有效性并计算两个实体的最短距离和相交体积。

支持零件树搜索、爆炸展示和两点网格测距，详见 [模型工程查看说明](MODEL_INSPECTION.md)。这些操作不修改原始 STEP。

## 软件和格式

Creo、SolidWorks、UG/NX、CATIA 请导出单个、包含完整几何的 STEP 文件后上传。
本功能不直接读取 `.sldprt`、`.sldasm`、Creo/NX `.prt` 或 `.CATPart` 等原生文件。
暂不支持多文件外部引用装配、压缩 STEP 或 XML 形式的 STEP。

## 准确性和限制

GLB 是显示网格，不是可编辑的 CAD 特征树，也不恢复装配配合、公差、加工要求或设计历史。
原 STEP 中的精确几何保留在原文件中；预览采用约 0.1mm 线性偏差和 0.3 弧度角度参数进行网格化，不能作为尺寸检验或制造认证结果。

单文件上限 50MB，预览上限 50MB / 100 万三角面。无可网格化曲面的线框 STEP 会拒绝。
转换在独立子进程中执行，最多同时转换一个文件；60 秒超时，CPU 上限 50 秒（硬上限 55 秒），不生成进程 core dump。
错误、超限或超时不会替换当前视图，也不会将未完成转换加入模型库。原有模型、项目和生成任务不受影响。

`.data/models/<id>.step`（或 `.stp`）保存源文件；`<id>.preview.glb` 保存预览。
备份时需要同时保留 `.data/projects.sqlite3` 和整个 `.data/models/`。

## 安装与启动

当前使用 Python 3.12、`cadquery-ocp==7.8.1.1.post1` 和 `vtk==9.3.1`。转换不需要安装或启动 CAD 图形界面。

```sh
cd /workspace/TONY-MUSIC
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-cad.txt
npm ci --ignore-scripts --no-audit --no-fund
.venv/bin/python server.py --port 8000
```

系统已有匹配 CAD 依赖时虚拟环境会复用；否则 pip 从配置的可信软件源安装，保留 TLS 和包验证。
请使用同一虚拟环境启动服务，转换子进程自动使用服务的 Python 解释器。

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/step_smoke.py
.venv/bin/python tests/viewer_smoke.py
```

浏览器测试使用隔离临时模型库，不修改用户项目，需预装 Playwright 与 `/usr/bin/chromium`。
