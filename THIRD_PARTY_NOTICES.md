# 第三方组件与许可证

本项目采用 MIT 许可证（见 `LICENSE`）。运行时依赖的第三方组件遵循其各自许可证，分发时请保留对应的许可证与版权声明。

| 组件 | 版本 | 许可证 | 说明 |
| --- | --- | --- | --- |
| PySide6 / Qt 6 | 6.12.0 | LGPL-3.0（部分模块 GPL-3.0） | 动态链接使用；不修改 Qt 本身；分发时附 LGPL 文本，并保证可替换 Qt 库 |
| opencv-python | 5.0.0.93 | Apache-2.0 | 图像处理与模板匹配 |
| numpy | 2.5.5 | BSD-3-Clause | 数值计算 |
| rapidocr-onnxruntime | 1.2.3 | Apache-2.0 | 中文 OCR，模型随包离线分发 |
| onnxruntime | 1.32.0 | MIT | OCR 模型推理 |
| mss | 10.2.0 | MIT | 高速截屏 |
| Pillow | 13.0.0 | MIT-CMU | 图像读写 |
| Python | 3.13.x | PSF License | 便携运行时；源码仓库不包含，见 Release 附件 |

## 说明

- 仓库只包含本项目源码，不包含 `runtime/` 便携 Python、`dist/` 可执行文件和第三方二进制。
- 若二次分发便携版，请一并保留 `runtime/python/LICENSE.txt` 以及各 site-packages 内的 LICENSE 文件。
- PySide6 采用 LGPLv3：以动态链接方式使用，用户可用自己的 Qt 库替换；本项目未修改 Qt 源码。
