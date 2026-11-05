# mark.rdfz.net · AI 智能阅卷工作台 (v3.0)

`mark.rdfz.net` 是面向海淀网上阅卷系统（`haidianyj.com` / 各次考试动态临时 IP）及阅满分平台（`yuemanfen.cn`）打造的 **AI 视觉大模型自动阅卷、试评校准、进程比例监控、任意试卷核查改分与教学诊断报告系统**。

本项目参考 `mark.bdfz.net`（`yuek12media`）的工作流与界面设计，移除与外部教务同步无关的模块，专注于 **「人类教师选题与写指令 + 个人 API Key 驱动多模态视觉大模型自动批阅与写分」**。

---

## 1. 核心特性概览

1. **动态源站连接与双协议登录适配 (`app/client/haidian_client.py`)**
   - 因每次联合阅卷服务器 IP 或域名可能变化（如 `http://47.94.92.141`、`http://123.56.103.75`、`www.haidianyj.com`、`www.yuemanfen.cn`），首页由教师输入本次具体地址、用户名与密码。
   - 自动探测上下文路径（`/mark/exam`、`/exam` 或根路径），优先尝试现代 **K12Media AES-128-ECB (`ajaxkeydao`) + `checkuser` 桥接协议**，并自动回退兼容 **传统 JSP (`login_ok.jsp`)** 登录。

2. **四大厂商最新一代及前三代多模态视觉模型 (`app/grader/ai_grader.py`)**
   - 严格筛选并仅保留具备 **图文识别（Vision）** 能力的 **2026 最新一代及前三代模型**：
     - **Google Gemini**：`gemini-3.8-flash`（Gen 3.8 默认）、`gemini-4-argon`（Gen 4 旗舰）、`gemini-3.7-flash`（Gen 3.7）、`gemini-3.6-flash`（Gen 3.6）、`gemini-3.5-flash`（Gen 3.5）。
     - **OpenAI**：`gpt-6.1-terra`（GPT-6.1 默认）、`gpt-6.1-sol`（GPT-6.1 旗舰）、`gpt-6-astra`（GPT-6.0）、`gpt-5.6`、`gpt-5.5`、`gpt-5.4`、`gpt-5.4-mini`。
     - **Anthropic Claude**：`claude-sonnet-5-5`（Claude 5.5 默认）、`claude-opus-5-5`、`claude-fable-5-1`、`claude-haiku-5-5`、`claude-sonnet-5`、`claude-fable-5`、`claude-opus-4-8`、`claude-sonnet-4-6`。
     - **DeepSeek**：`deepseek-flash`（V4.1-Flash 原生多模态默认）、`deepseek-v4-flash-vision-exp`、`janus-pro-7b`、`deepseek-vl2`。
   - 支持 **Thinking / Reasoning Effort** 四档调节（`MINIMAL` / `LOW` / `MEDIUM` / `HIGH`），并支持 **多 API Key 轮询与 429/5xx 指数退避重试**。

3. **三步向导式 AI 阅卷工作流 (`app/static/index.html` & `app/static/app.js`)**
   - **第 1 步（选择目标题目并预览真实答卷）**：自动拉取当前账号分配的考试科目（正评 `normal` / 仲裁 `arb`）、题号列表、题目满分、给分步长（`markdic`）、复合小题结构（`smallnum` / `smallname` / `smallmark`）、**源站同题实时进度与比例**，并抽取真实学生答卷切图供教师视觉确认（支持多图纵向/横向拼接 `splice` 与点击全屏滚轮缩放）。
   - **第 2 步（编写评分指令 Prompt）**：内置 6 类学科结构化评分模板（语文现代文阅读、古诗文默写/文言翻译、数理化分步给分、英语书面表达、政史地材料分析、通用自定义），支持 **AI 自动拆分 `point_1`/`point_2` 采分点**，教师可自由编辑最终 Prompt。
   - **第 3 步（选择视觉模型、填入 API Key、启动试评或正式评阅）**：API Key 按厂商保存在教师浏览器本地 `localStorage` 并随任务传入。

4. **先试评（Trial）后正式连续写分（Formal）闭环 (`app/main.py`)**
   - **🧪 试评模式 (`dry_run=True`)**：按设定份数（默认 10 份）调用视觉模型批阅，展示逐点得分、评语与手写 OCR，供教师核查评分标准是否过严或过松。
   - **🚀 试评转正 (`/api/job/{job_id}/promote-formal`) 或直接正式评阅 (`dry_run=False`)**：教师确认试评满意后，可一键将试评卷提交写分并无缝转入后台连续拉卷、识图、判分、写分循环；运行中支持暂停（`pause`）、继续（`resume`）、停止（`stop`）以及 **不重启任务动态热更新 Prompt（`/api/job/{job_id}/update-prompt`）**。

5. **双重阅卷进程与比例监控 (`Geek HUD` & `stats-grid`)**
   - **进度条 ① 本次 AI 任务进程与比例**：`本任务已评 / 目标份数 (X%)`、已写回源站数、试评样本数、实时速率（份/分）。
   - **进度条 ② 源站同题总进程与比例**：`源站已评 / 源站总卷数 (Y%)`、本教师账号累计已评份数、源站实时均分。
   - **实时分数分布比例柱状图 & 采分点命中率**：各分值档位人数与占比（点击柱条可按分值筛选试卷）、满分卷及比例、零分卷及比例、平均分及得分率、各 `point_*` 采分点命中率与均分。

6. **任意试卷点开核查与修改分数 (`#taskReviewModal` & `/api/paper/regrade`)**
   - 无论在「实时监控卡片墙」、「本机 AI 已评/试评卷库」还是「源站历史已评卷回评库（`/api/source/review-list`）」，**点击任意试卷卡片**均可弹出双栏核查弹窗：
     - 左侧：高清作答切图（点击全屏滚轮缩放）、**查看该考生整张试卷正反面大图（`/api/paper/whole-paper`）**、对照评分指令 Prompt。
     - 右侧：支持 `◀ 上一份 / 下一份 ▶`（或键盘左右方向键）翻页、直接修改总分或复合题各小题分并点击 **「💾 确认修改并写回源站」**（自动调用源站回评加载接口 `get_review_paper_info` + 提交写分 `submit_score` + **源站读回校验 `readback_verified`**），或点击 **「🤖 AI 单卷重评」**。

---

## 2. 仓库目录与代码结构（供代码审查参考）

```text
mark-rdfz/
├── app/
│   ├── main.py                  # FastAPI 主入口、Job 后台线程调度引擎、统计聚合与全部 REST API 路由
│   ├── client/
│   │   └── haidian_client.py    # 海淀阅卷 / 阅满分源站客户端（登录、选题、拉卷、多图拼接、提交分数、回评改分、整卷拉取、源站进度查询）
│   ├── grader/
│   │   └── ai_grader.py         # 多模态视觉大模型调用层（Gemini/OpenAI/Claude/DeepSeek、多Key轮询、学科模板、JSON解析与分数步长对齐）
│   └── static/
│       ├── index.html           # 前端单页工作台视图（登录页 + 4 大功能 Tab + #taskReviewModal 核查改分弹窗 + Lightbox）
│       ├── app.js               # 前端状态管理、向导交互、双进度比例轮询、直方图渲染、核查改分与报告导出逻辑
│       ├── style.css            # 莫奈暖纸风格样式表（与 mark.bdfz.net 同款设计语言，支持深色/浅色主题切换）
│       └── data/                # 字体 (HuWenMingChaoTi.woff2) 与背景图 (bg.webp)
├── nginx/
│   └── mark.rdfz.net.conf       # Nginx 反向代理与 HTTPS 配置（监听 80/443 -> 127.0.0.1:8880）
├── docs/
│   └── OPERATIONS.md            # 运维与故障排查手册
├── Dockerfile                   # Python 3.12-slim 容器镜像构建定义
├── docker-compose.yml           # 容器编排配置（绑定 127.0.0.1:8880:8880）
├── requirements.txt             # Python 依赖清单（FastAPI, Uvicorn, Requests, BeautifulSoup4, Pillow, PyCryptodome）
├── deploy.sh                    # 一键同步与容器重建部署脚本
└── PROJECT_STATE.md             # 项目当前状态与架构台账
```

---

## 3. 核心模块实现细节与审查要点

### 3.1 源站协议层 (`app/client/haidian_client.py`)
- **登录与会话桥接 (`login`)**：
  - 现代 K12Media 平台通过 `/base/ajaxkeydao` 获取动态 RSA/AES 参数，使用 `AES-128-ECB`（Key 为 `k12mediahdyj2018` 或动态下发 Key）加密凭证后提交表单，随后解析并访问 `/mark/exam/checkuser?roleid=...&userid=...` 完成阅卷子系统 Cookie 绑定。
- **拉取待评试卷 (`claim_task`)**：
  - 正评模式调用 `mark/get_paperinfo`，仲裁模式调用 `mark/Arbget_paperinfo`。
  - 自动解析返回的 `fullmark`（满分）、`markdic`（合法给分枚举序列，如 `0,0.5,1,...,10`）、以及复合题字段 `smallnum`、`smallname`、`smallmark`、`smallmarkdic`。
- **切块图像下载与拼接 (`get_image`)**：
  - 当一道题跨越多个答题卡切块（`imgpath` 以分号 `;` 分隔多张图片路径）时，自动下载全部切块并通过 `Pillow` 按纵向（`splice=0`）或横向（`splice=1`）无损拼接为单张高清 JPEG 供 AI 识图与前端展示。
- **任意已评试卷核查与改分 (`get_review_list` / `get_review_paper_info` / `submit_score`)**：
  - 源站要求改分前必须先请求 `get_review_paper_info(secid)`（对应源站 `reviewpaper` 接口）将服务端 Session 游标定位到该 `secid`，再调用 `submit_score`（`markpaper` / `Arbmarkpaper`）提交新分数。
  - 本系统在 `/api/paper/regrade` 中严格遵循「先定位回评上下文 → 提交新分数 → 再次调用 `get_review_paper_info` 读回校验分值」的三步事务。

### 3.2 视觉大模型判分层 (`app/grader/ai_grader.py`)
- **统一输出结构与步长对齐 (`_normalize_result`)**：
  - 强制要求模型返回结构化 JSON（包含 `student_answer`、`point_scores`、`point_comments`、`sub_scores`、`final_score`、`overall_comment`、`flags`）。
  - 若模型输出包含 Markdown 代码块或尾部逗号，通过正则与容错提取器解析。
  - 若题目为复合题（`sub_questions` 非空），逐一校验每个子题得分不超过子题满分并自动对齐子题 `markdic` 步长，最后汇总为总分；若为单题，则根据各 `point_*` 采分点得分汇总并对齐题目合法 `markdic_list` 或 `[0, full_score]` 区间。

### 3.3 任务调度与并发控制 (`app/main.py`)
- **后台工作线程 (`_job_worker_loop`)**：
  - 试评模式（`dry_run=True`）：支持从待评队列或已评回评列表中抽取样本进行 AI 批阅，达到 `trial_limit` 后状态置为 `trial_completed`，等待教师审阅。
  - 正式模式（`dry_run=False`）：利用源站 `submit_score` 返回的下一份试卷元数据（`codeid == "0001"` 且含新 `secid`）实现零额外请求链式拉卷批阅，直至队列清空或达到 `formal_limit`。

---

## 4. REST API 路由一览

| 方法 | 路径 | 功能说明 |
| :--- | :--- | :--- |
| `GET` | `/healthz` | 容器健康检查，返回 `{"status": "ok", "version": "3.0.0"}` |
| `GET` | `/api/models` | 获取四大厂商最新一代及前三代具备图文识别能力的模型目录 |
| `GET` | `/api/templates` | 获取内置学科评分指令模板及槽位定义 |
| `POST` | `/api/templates/render` | 将模板槽位合成为完整评分指令 Prompt |
| `POST` | `/api/ai/generate-rubric` | 调用 AI 根据题干与参考答案自动拆分 `point_*` 采分细则 |
| `POST` | `/api/login` | 登录目标阅卷服务器并自动发现可用考试科目与题号 |
| `GET` | `/api/session` | 查询当前登录会话状态与活动任务 ID |
| `POST` | `/api/logout` | 停止当前任务并销毁登录会话 |
| `POST` | `/api/task/select-subject` | 切换考试科目与评卷模式（正评 `normal` / 仲裁 `arb`），返回题号列表 |
| `POST` | `/api/task/preview` | 第 1 步预览：获取题目配置、源站实时进度比例及随机真实学生答卷图 |
| `POST` | `/api/job/create` | 创建并启动 AI 试评（`dry_run=True`）或正式评阅（`dry_run=False`）任务 |
| `GET` | `/api/job/{job_id}/live` | 获取任务实时双进度比例、分数分布直方图、采分点命中率与耗时统计 |
| `GET` | `/api/job/{job_id}/tasks` | 获取任务已批阅试卷卡片列表（支持按状态/满分/零分/收藏/失败筛选） |
| `POST` | `/api/job/{job_id}/pause` | 暂停正在运行的批阅任务 |
| `POST` | `/api/job/{job_id}/resume` | 继续已暂停的批阅任务 |
| `POST` | `/api/job/{job_id}/stop` | 停止批阅任务 |
| `POST` | `/api/job/{job_id}/promote-formal` | 试评审阅通过后一键转入正式连续写分（自动提交未写分试评卷并继续批阅） |
| `POST` | `/api/job/{job_id}/update-prompt` | 运行中动态修改评分指令 Prompt，对后续新抽取试卷立即生效 |
| `GET` | `/api/jobs/history` | 获取当前会话的历史批阅任务列表 |
| `POST` | `/api/paper/regrade` | **修改任意试卷分数并同步写回源站**（含源站 `get_review_paper_info` 读回校验） |
| `POST` | `/api/paper/ai-regrade` | 在核查弹窗内对单张试卷重新运行 AI 视觉批阅 |
| `POST` | `/api/source/review-list` | 拉取源站历史已评试卷回评列表（支持按分值筛选） |
| `POST` | `/api/source/review-detail` | 拉取源站单张历史已评试卷的高清作答切图与原分详情 |
| `POST` | `/api/paper/whole-paper` | 根据 `zimgpath` 拉取该考生的整张试卷正反面大图 |
| `POST` | `/api/report/summary` | 汇总得分分布、采分点命中率与作答样本，生成 Markdown 教学分析报告 |

---

## 5. 本地运行与生产部署

### 本地启动调试
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8880 --reload
```

### 生产环境部署 (`23.19.231.173` / `mark.rdfz.net`)
```bash
bash deploy.sh
```
- 容器服务监听：`127.0.0.1:8880`
- Nginx 反向代理：`/etc/nginx/sites-available/mark.rdfz.net`（HTTPS 443 -> `http://127.0.0.1:8880`）
