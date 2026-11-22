# 第三方组件许可说明

本程序（慧眼屏幕助手 / ScreenEye）以 MIT 许可证发布。运行依赖如下第三方组件，
各自遵循其原始许可证。便携版 `runtime/python/` 内已随附相应许可文件。

| 组件 | 版本（参考） | 许可证 | 备注 |
| --- | --- | --- | --- |
| PySide6（Qt 6） | 6.12 | LGPL-3.0（商业许可另售） | 以动态链接方式使用，未修改 Qt 源码；再分发时需附带 LGPL-3.0 文本并保留替换库的可能 |
| opencv-python | 5.0 | Apache-2.0 | 模板匹配、图像处理 |
| numpy | 2.x | BSD-3-Clause | 数值计算 |
| rapidocr-onnxruntime | 1.x | Apache-2.0 | OCR 推理封装 |
| onnxruntime | 1.x | MIT | OCR 模型推理引擎 |
| mss | 9.x | MIT | 屏幕抓取 |
| Pillow | 11.x | MIT-CMU | 图像读写、绘制 |
| Python | 3.13 | PSF License | 便携运行时 |

## 使用约定

1. 若你基于本程序做二次分发（包括商用），请保留本文件与 `LICENSE`。
2. PySide6 采用 LGPL-3.0：不要静态链接、不要修改 Qt 库文件；如需替换 Qt 库，用户应能用自己编译的版本替换 `runtime/python/Lib/site-packages/PySide6` 下的同名文件。
3. OCR 模型文件来自 PP-OCR 系列开源模型，遵循其原始开源许可。
4. 本程序不包含任何闭源商业 SDK，也不会上传用户屏幕内容。
