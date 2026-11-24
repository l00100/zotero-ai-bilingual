# 来源、致谢与修改说明

本项目是现有 Zotero 插件的衍生改进，不主张原创上游的分屏阅读器、HJFY 接入或插件模板。

本分支的 AI 增强、安装脚本和公开发布整理由 l00100 于 2026-11-24 完成；具体修改与本地阶段版本见 CHANGELOG.md。原有作者标注和许可证均予以保留。

## 继承关系

1. **直接基线：[leisongju/zotero-hjfy-split-reader-cn](https://github.com/leisongju/zotero-hjfy-split-reader-cn)**，版本 [v0.1.4](https://github.com/leisongju/zotero-hjfy-split-reader-cn/releases/tag/v0.1.4)，提交 [be96c218b1a220010c215b6b3c6a8354302b2d25](https://github.com/leisongju/zotero-hjfy-split-reader-cn/commit/be96c218b1a220010c215b6b3c6a8354302b2d25)。本仓库保留此版本及其之前的 Git 历史、原作者标注和许可证，并保存其 README 快照。
2. **更早的直接上游：[Infinity4B/zotero-hjfy-split-reader](https://github.com/Infinity4B/zotero-hjfy-split-reader)**。HJFY 分屏集成的上游来源。
3. **分屏阅读器：[zerolfl/zotero-split-view-reader](https://github.com/zerolfl/zotero-split-view-reader)**。双阅读器布局、同步和相关 UI 的核心来源。
4. **HJFY 接入参考：[ANGJustinl/zotero-plugin-hjfy](https://github.com/ANGJustinl/zotero-plugin-hjfy)**。查询与导入 HJFY 译文的上游参考。
5. **模板与工具：[windingwind/zotero-plugin-template](https://github.com/windingwind/zotero-plugin-template)、[zotero-plugin-toolkit](https://github.com/windingwind/zotero-plugin-toolkit)**。插件生命周期、界面工具和工程结构的来源。
6. **元数据检索：[zotero/translators](https://github.com/zotero/translators)** 的 arXiv / OpenAlex translators，以及 [AllanChain/zotero-arxiv-workflow](https://github.com/AllanChain/zotero-arxiv-workflow)。上游对识别与检索流程的来源和参考。

以上关系沿用直接基线项目的来源说明，并非声称本改进版重新实现了这些功能。

## 此分支新增的 AI 流程

- [PDFMathTranslate/PDFMathTranslate-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next)：提供翻译配置和通用模型调用适配。
- [funstory-ai/BabelDOC](https://github.com/funstory-ai/BabelDOC)：提供 PDF 版面分析、公式/样式处理和译文排版。
- [guaguastandup/zotero-pdf2zh](https://github.com/guaguastandup/zotero-pdf2zh)：本地服务与 Zotero 集成方式的调研参考；本分支的服务运行依赖是 PDF2zh-next / BabelDOC，不要求同时安装此 Zotero 插件。

上述排版与模型库作为独立依赖安装。其作者、版权与许可不因本项目的集成而改变。

本分支由 l00100 维护的主要新增内容包括：`src/modules/aiCore.ts`、`src/modules/aiTranslation.ts`、`service/`、平台安装脚本、参考文献区域保留、配置与测试、公开文档及打包流程。原代码文件内的版权和致谢保持保留。

## 许可证

根目录 `LICENSE` 保留上游 GNU Affero General Public License Version 3 全文；项目声明继续为 AGPL-3.0-or-later。请阅读各依赖自己的许可证。此说明仅用于准确标明来源，不替代许可证文本。
