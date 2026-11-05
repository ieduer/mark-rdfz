# mark.rdfz.net 运维与技术手册 (OPERATIONS.md)

## 1. 服务拓扑与生产环境信息

- **访问域名**：`https://mark.rdfz.net`
- **目标主机**：`23.19.231.173`（SSH 别名：`hostdzire`）
- **部署路径**：`/opt/mark-rdfz`
- **容器名称**：`mark-rdfz`（基于 `docker-compose.yml` 管理，宿主机监听 `127.0.0.1:8880`）
- **反向代理**：`/etc/nginx/sites-available/mark.rdfz.net`（SSL 证书位于 `/etc/ssl/certs/mark.rdfz.net.crt` 与 `/etc/ssl/private/mark.rdfz.net.key`）

---

## 2. 日常运维指令

### 2.1 一键发布与更新
在本地工作区执行：
```bash
bash /Users/ylsuen/CF/platforms/projects/mark-rdfz/deploy.sh
```
该脚本自动完成：
1. `rsync` 同步代码与静态资源至 `hostdzire:/opt/mark-rdfz`
2. 校验并重载 Nginx 配置
3. 重新构建并启动 `mark-rdfz` Docker 容器
4. 执行本机健康检查

### 2.2 查看实时运行日志与诊断事件
- **查看容器日志**：
  ```bash
  ssh hostdzire "docker logs -f --tail 100 mark-rdfz"
  ```
- **查看后台诊断事件接口**：
  ```bash
  ssh hostdzire "curl -s http://127.0.0.1:8880/api/debug/diagnostics | jq ."
  ```
  注：日志与诊断台账仅脱敏记录操作动作、用户名、目标源站地址、协议状态与耗时，不落盘记录教师明文密码或个人 API Key。

---

## 3. 核心架构与故障排查指南

### 3.1 源站登录与上下文桥接排查
- 海淀/阅满分平台存在两种主要部署形态：
  1. **现代 K12Media 形态（如 `yuemanfen.cn` 及新版海淀主机）**：
     - 登录时需先请求 `/base/ajaxkeydao` 获取密钥信息，密码经 `AES-128-ECB` 加密后提交，成功后必须提取页面中的 `/mark/exam/checkuser?roleid=...&userid=...` 链接并访问一次，方可在 `/mark/exam/` 路径下激活阅卷 Session。
  2. **传统 JSP 形态（如部分区县临时 IP 主机）**：
     - 直接向 `/exam/login_ok.jsp` 提交 `logname` 与 `logpass`。
- `HaidianClient.login()` 已内置上述双协议自动探测与回退。若遇到新形态源站报错，可通过 `docker logs mark-rdfz` 查看 `[LOGIN]` 诊断输出。

### 3.2 视觉大模型调用与限流容错
- `AIGrader`（`app/grader/ai_grader.py`）支持填入多个 API Key（逗号或换行分隔）。
- 当单个 Key 触发 `HTTP 429`（Rate Limit）或瞬时网络异常时，自动切换至下一个 Key 并执行指数退避重试。
- 判分结果经 `_normalize_result()` 强制对齐题目满分与合法给分步长（`markdic_list`），防止产生源站拒收的非法小数分值。

### 3.3 任意试卷改分写回源站校验机制
- 在 `/api/paper/regrade` 中，系统严格执行三步操作：
  1. 调用 `client.get_review_paper_info(secid)`（源站 `reviewpaper` 接口），在源站 Session 中锁定目标已评试卷；
  2. 调用 `client.submit_score(...)`（源站 `markpaper` / `Arbmarkpaper` 接口）提交新分数（含复合题各小题分 `smallscore1..N`）；
  3. 再次调用 `client.get_review_paper_info(secid)` 读回源站实际存储的分数，返回 `readback_verified: true` 与 `readback_score` 供前端核验。
