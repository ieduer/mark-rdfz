# PROJECT_STATE.md — mark.rdfz.net (AI 智能阅卷工作台)

- **当前版本**：`v3.0.0` (2026-11-04)
- **生产状态**：已上线运行（`https://mark.rdfz.net` -> `23.19.231.173:8880`）
- **本地权威路径**：`/Users/ylsuen/CF/platforms/projects/mark-rdfz`
- **参考基线项目**：`/Users/ylsuen/CF/platforms/projects/yuek12media` (`mark.bdfz.net`)

## 已验收能力清单

1. **动态源站连接页（纯净登录，已移除测试/Demo提示信息）**
   - 支持教师自定义输入当次阅卷服务器 IP 或域名（附常用源站快捷胶囊 `47.94.92.141`、`123.56.103.75`、`www.haidianyj.com`、`www.yuemanfen.cn`）。
   - 自动适配现代 K12Media AES (`ajaxkeydao` + `checkuser`) 与传统 JSP (`login_ok.jsp`) 双登录协议。

2. **四大厂商最新一代及前三代多模态视觉（Vision）模型目录**
   - Google Gemini：`gemini-3.8-flash` (默认)、`gemini-4-argon`、`gemini-3.7-flash`、`gemini-3.6-flash`、`gemini-3.5-flash`。
   - OpenAI：`gpt-6.1-terra` (默认)、`gpt-6.1-sol`、`gpt-6-astra`、`gpt-5.6`、`gpt-5.5`、`gpt-5.4`、`gpt-5.4-mini`。
   - Anthropic Claude：`claude-sonnet-5-5` (默认)、`claude-opus-5-5`、`claude-fable-5-1`、`claude-haiku-5-5`、`claude-sonnet-5`、`claude-fable-5`、`claude-opus-4-8`、`claude-sonnet-4-6`。
   - DeepSeek：`deepseek-flash` (V4.1-Flash 默认)、`deepseek-v4-flash-vision-exp`、`janus-pro-7b`、`deepseek-vl2`。

3. **三步向导式 AI 阅卷、试评与正式连续写分**
   - Step 1：选科目/模式（正评/仲裁）/题号 + 源站实时进度比例预览 + 随机学生真实答卷切图预览与确认。
   - Step 2：学科评分模板合成、AI 辅助生成 `point_*` 采分点、自由编辑评分指令 Prompt。
   - Step 3：选择视觉模型、Thinking 深度、填入个人 API Keys（支持多 Key 轮询），启动 **🧪 试评 (`dry_run=True`)** 或 **🚀 正式连续写分 (`dry_run=False`)**，支持试评审阅后一键转正（`promote-formal`）。

4. **双轨阅卷进程与比例监控**
   - 同时展示 **本任务评阅进度与比例**、**源站同题总进度与比例**、**实时分数分布比例柱状图**、**满分率/零分率/得分率** 与 **各采分点 (`point_*`) 命中率**。

5. **任意试卷点开核查与修改分数 (`#taskReviewModal`)**
   - 支持从实时监控卡片墙、本机已评/试评卷库、源站历史已评卷回评库点开任意试卷，查看高清原图、查看考生整张试卷正反面、修改总分或复合小题分并同步写回源站（含源站读回校验 `readback_verified`），以及 AI 单卷重评。
