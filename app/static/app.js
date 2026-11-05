/* ================================================================
 * mark.rdfz.net — AI 智能阅卷工作台前端核心逻辑 (v3.0)
 * 对标 mark.bdfz.net 架构：
 *   1. 四大厂商（Gemini / OpenAI / Claude / DeepSeek）最新一代与前三代视觉模型
 *   2. 三步向导（选题与真卷预览 → 编写评分指令 Prompt → 选模型填 Key 试评/正式执行）
 *   3. 双重进度与比例监控（本任务进度比例 + 源站同题总进度比例 + 分数分布比例 + 得分点命中率）
 *   4. 任意试卷点开核查与修改分数（本机已评/试评卷 + 源站历史回评卷，支持查看整卷、改分写回源站读回校验、AI单卷重评）
 * ============================================================== */

(function () {
  "use strict";

  // ==================== 内置最新一代与前三代视觉模型兜底目录 ====================
  const FALLBACK_MODELS = {
    gemini: {
      name: "Google Gemini (原生多模态视觉)",
      key_placeholder: "AIzaSy... (支持多个 Key 换行或逗号分隔轮询)",
      models: [
        { id: "gemini-3.8-flash", name: "Gemini 3.8 Flash (最新主力高速视觉)", generation: "最新一代 (Gen 3.8)", default: true, recommended: true, desc: "2026最新一代高速多模态主力，识图极快、性价比最高（强烈推荐）" },
        { id: "gemini-4-argon", name: "Gemini 4 Argon (最新一代旗舰视觉推理)", generation: "最新一代 (Gen 4)", recommended: true, desc: "Google最新一代旗舰多模态大模型，适合复杂主观题、压轴题与作文深度批阅" },
        { id: "gemini-3.7-flash", name: "Gemini 3.7 Flash (前一代高速视觉)", generation: "前一代 (Gen 3.7)", desc: "前一代成熟稳定多模态视觉模型，兼顾手写字迹识别率与低延迟" },
        { id: "gemini-3.6-flash", name: "Gemini 3.6 Flash (前两代多模态视觉)", generation: "前两代 (Gen 3.6)", desc: "前两代稳定多模态模型，适合常规填空、默写与简答题批阅" },
        { id: "gemini-3.5-flash", name: "Gemini 3.5 Flash (前三代多模态视觉)", generation: "前三代 (Gen 3.5)", desc: "前三代高兼容多模态模型，适合作为高并发备选回退" }
      ]
    },
    openai: {
      name: "OpenAI (GPT-6 / GPT-5 视觉系列)",
      key_placeholder: "sk-proj-... (支持多个 Key 换行或逗号分隔轮询)",
      models: [
        { id: "gpt-6.1-terra", name: "GPT-6.1 Terra (最新一代高速全模态视觉)", generation: "最新一代 (GPT-6.1)", default: true, recommended: true, desc: "OpenAI最新一代高效视觉推理主力，支持高分辨率手写答卷精准识别（推荐）" },
        { id: "gpt-6.1-sol", name: "GPT-6.1 Sol (最新一代高阶视觉旗舰)", generation: "最新一代 (GPT-6.1)", recommended: true, desc: "GPT-6.1高阶多模态版本，适合复杂数理化分步推导与高难度主观题" },
        { id: "gpt-6-astra", name: "GPT-6 Astra (最新一代全模态旗舰)", generation: "最新一代 (GPT-6.0)", desc: "GPT-6初代全模态旗舰，具备极强的图文联合推理与跨学科分析能力" },
        { id: "gpt-5.6", name: "GPT-5.6 Vision (前一代旗舰多模态)", generation: "前一代 (GPT-5.6)", desc: "GPT-5系列收官旗舰视觉模型，指令遵循度高、判分尺度稳定" },
        { id: "gpt-5.5", name: "GPT-5.5 Vision (前两代主力多模态)", generation: "前两代 (GPT-5.5)", desc: "前两代均衡型视觉推理模型，适合常规学科主观题批量评阅" },
        { id: "gpt-5.4", name: "GPT-5.4 Vision (前三代原生高清视觉)", generation: "前三代 (GPT-5.4)", desc: "支持原生高清全分辨率识图，适合细节密集的几何图形与实验题" },
        { id: "gpt-5.4-mini", name: "GPT-5.4 Mini (前三代轻量高速视觉)", generation: "前三代 (GPT-5.4)", desc: "前三代高吞吐轻量多模态模型，适合大批量快速初评与试评" }
      ]
    },
    claude: {
      name: "Anthropic Claude (Claude 5 / 4 视觉系列)",
      key_placeholder: "sk-ant-api03-... (支持多个 Key 换行或逗号分隔轮询)",
      models: [
        { id: "claude-sonnet-5-5", name: "Claude Sonnet 5.5 (最新一代均衡视觉主力)", generation: "最新一代 (Claude 5.5)", default: true, recommended: true, desc: "Anthropic最新一代主力视觉模型，手写中文/英文辨识与采分点拆解极佳（推荐）" },
        { id: "claude-opus-5-5", name: "Claude Opus 5.5 (最新一代旗舰视觉推理)", generation: "最新一代 (Claude 5.5)", recommended: true, desc: "Claude 5.5顶级旗舰，适合语文/英语大作文、文言文翻译及深度主观论述" },
        { id: "claude-fable-5-1", name: "Claude Fable 5.1 (最新一代高阶深度视觉)", generation: "最新一代 (Claude 5.1)", desc: "专为深度多步推理与长篇复杂图文解析打造的高阶多模态模型" },
        { id: "claude-haiku-5-5", name: "Claude Haiku 5.5 (最新一代极速轻量视觉)", generation: "最新一代 (Claude 5.5)", desc: "最新一代极速多模态模型，响应最快，适合客观填空与短简答题" },
        { id: "claude-sonnet-5", name: "Claude Sonnet 5.0 (前一代均衡多模态)", generation: "前一代 (Claude 5.0)", desc: "Claude 5.0标准多模态视觉模型，兼顾批阅质量与速度" },
        { id: "claude-fable-5", name: "Claude Fable 5.0 (前一代深度推理多模态)", generation: "前一代 (Claude 5.0)", desc: "前一代高阶多模态模型，适合严谨逻辑推理题" },
        { id: "claude-opus-4-8", name: "Claude Opus 4.8 (前两代旗舰多模态)", generation: "前两代 (Claude 4.8)", desc: "Claude 4系列后期旗舰视觉模型，评语细腻、扣分依据详实" },
        { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6 (前三代经典多模态)", generation: "前三代 (Claude 4.6)", desc: "前三代成熟稳定视觉模型，广泛验证于各类学科图文批阅" }
      ]
    },
    deepseek: {
      name: "DeepSeek (官方多模态视觉系列)",
      key_placeholder: "sk-... (支持多个 Key 换行或逗号分隔轮询)",
      models: [
        { id: "deepseek-flash", name: "DeepSeek V4.1-Flash Vision (最新一代原生多模态)", generation: "最新一代 (V4.1-Flash)", default: true, recommended: true, desc: "DeepSeek最新官方原生多模态视觉模型，支持手写答卷识图与高性价比批阅（推荐）" },
        { id: "deepseek-v4-flash-vision-exp", name: "DeepSeek V4-Flash Vision Exp (前一代多模态视觉)", generation: "前一代 (V4-Flash)", desc: "DeepSeek V4早期多模态视觉实验版，支持图文联合输入与结构化打分" },
        { id: "janus-pro-7b", name: "DeepSeek Janus-Pro-7B (前两代统一多模态理解)", generation: "前两代 (Janus-Pro)", desc: "DeepSeek解耦视觉编码多模态模型（需服务端网关支持该模型ID）" },
        { id: "deepseek-vl2", name: "DeepSeek-VL2 (前三代 MoE 视觉语言模型)", generation: "前三代 (VL2)", desc: "DeepSeek动态高分辨率MoE视觉模型，擅长文档、图表与公式手写识别" }
      ]
    }
  };

  // ==================== 全局状态 ====================
  const state = {
    session: { logged_in: false, base_url: "", username: "", subjects: [] },
    modelsCatalog: FALLBACK_MODELS,
    templatesCatalog: [],
    currentSubject: null,
    currentMode: "normal",
    currentQuestion: null,
    currentQuestionMeta: null,
    currentPreviewPaper: null,
    activeJobId: "",
    activeJob: null,
    monitorTasks: [],
    monitorFilter: "all",
    monitorScoreFilter: null,
    monitorPollTimer: null,
    regradeMode: "local", // 'local' | 'source'
    regradeLocalTasks: [],
    regradeSourceTasks: [],
    modalList: [],
    modalIndex: -1,
    modalCurrentItem: null,
    lbScale: 1
  };

  // ==================== 工具函数 ====================
  const $ = (id) => document.getElementById(id);

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("zh-CN", { hour12: false });
  }

  function fmtDuration(sec) {
    if (!sec || sec < 0) return "0秒";
    const s = Math.floor(sec);
    if (s < 60) return `${s}秒`;
    const m = Math.floor(s / 60);
    const rem = s % 60;
    if (m < 60) return `${m}分${rem}秒`;
    const h = Math.floor(m / 60);
    return `${h}小时${m % 60}分`;
  }

  async function api(path, options = {}) {
    const opts = {
      method: options.method || "GET",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    };
    if (options.body !== undefined) {
      opts.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
    }
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const msg = data.detail || data.error || data.message || `请求失败 (${res.status})`;
      throw new Error(msg);
    }
    return data;
  }

  function extractPointKeysClient(text) {
    const matches = String(text || "").match(/point_[a-zA-Z0-9_]+/g) || [];
    const seen = new Set();
    const out = [];
    for (const m of matches) {
      if (!seen.has(m)) {
        seen.add(m);
        out.push(m);
      }
    }
    return out.length ? out : ["point_1"];
  }

  // ==================== 主题与导航 ====================
  function initThemeAndNav() {
    const savedTheme = localStorage.getItem("mark_rdfz_theme") || "midnight";
    document.documentElement.setAttribute("data-theme", savedTheme);

    const themeBtn = $("themeToggleBtn");
    if (themeBtn) {
      themeBtn.addEventListener("click", () => {
        const cur = document.documentElement.getAttribute("data-theme") || "midnight";
        const next = cur === "dark" ? "midnight" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("mark_rdfz_theme", next);
      });
    }

    // 侧边栏 Tab 切换
    document.querySelectorAll("#sideNav .side-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchTab(btn.dataset.tab);
      });
    });

    // 移动端抽屉菜单
    const ham = $("hamburgerBtn");
    const sidebar = $("sidebar");
    const overlay = $("sidebarOverlay");
    if (ham && sidebar && overlay) {
      ham.addEventListener("click", () => {
        sidebar.classList.toggle("open");
        overlay.hidden = !sidebar.classList.contains("open");
      });
      overlay.addEventListener("click", () => {
        sidebar.classList.remove("open");
        overlay.hidden = true;
      });
    }
  }

  function switchTab(tabId) {
    document.querySelectorAll("#sideNav .side-tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tabId);
    });
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.classList.toggle("active", p.id === `tab-${tabId}`);
    });
    const sidebar = $("sidebar");
    const overlay = $("sidebarOverlay");
    if (sidebar) sidebar.classList.remove("open");
    if (overlay) overlay.hidden = true;

    if (tabId === "monitor") {
      refreshMonitorNow();
    } else if (tabId === "regrade") {
      loadRegradeTab();
    } else if (tabId === "report") {
      loadHistoryJobsAndReport();
    }
  }

  // ==================== 模型目录与 API Key 本地存储 ====================
  async function loadModelsAndTemplates() {
    try {
      const mRes = await api("/api/models");
      if (mRes.providers) {
        state.modelsCatalog = mRes.providers;
      }
    } catch (_) {
      state.modelsCatalog = FALLBACK_MODELS;
    }

    try {
      const tRes = await api("/api/templates");
      if (Array.isArray(tRes.templates)) {
        state.templatesCatalog = tRes.templates;
      }
    } catch (_) {
      state.templatesCatalog = [];
    }

    renderProviderAndModels();
    renderTemplatesDropdown();
  }

  function renderProviderAndModels() {
    const providerSel = $("providerSelect");
    const modelSel = $("modelSelect");
    if (!providerSel || !modelSel) return;

    const savedProvider = localStorage.getItem("mark_rdfz_provider") || "gemini";
    if (state.modelsCatalog[savedProvider]) {
      providerSel.value = savedProvider;
    }

    function updateModelsForProvider() {
      const provKey = providerSel.value;
      localStorage.setItem("mark_rdfz_provider", provKey);
      const provInfo = state.modelsCatalog[provKey] || FALLBACK_MODELS.gemini;
      const models = provInfo.models || [];

      const savedModel = localStorage.getItem(`mark_rdfz_model_${provKey}`) || "";
      modelSel.innerHTML = models
        .map((m) => {
          const genTag = m.generation ? `[${m.generation}] ` : "";
          const recTag = m.recommended ? " ★推荐" : "";
          return `<option value="${esc(m.id)}">${esc(genTag + m.name + recTag)}</option>`;
        })
        .join("");

      const defaultModel = models.find((m) => m.id === savedModel) || models.find((m) => m.default) || models[0];
      if (defaultModel) {
        modelSel.value = defaultModel.id;
      }

      updateModelDesc();

      // 恢复该厂商保存在本地的 API Keys
      const keyInput = $("apiKeysInput");
      if (keyInput) {
        keyInput.placeholder = provInfo.key_placeholder || "粘贴您的 API Key（支持多 Key 换行或逗号分隔轮询）";
        keyInput.value = localStorage.getItem(`mark_rdfz_keys_${provKey}`) || "";
      }
    }

    function updateModelDesc() {
      const provKey = providerSel.value;
      const provInfo = state.modelsCatalog[provKey] || FALLBACK_MODELS.gemini;
      const curModel = (provInfo.models || []).find((m) => m.id === modelSel.value);
      localStorage.setItem(`mark_rdfz_model_${provKey}`, modelSel.value);
      const hint = $("modelDescHint");
      if (hint && curModel) {
        hint.textContent = `👁️ 图文识别视觉模型 · ${curModel.generation || ""}：${curModel.desc || ""}`;
      }
      const repReadonly = $("reportModelReadonly");
      if (repReadonly && curModel) {
        repReadonly.value = `${provInfo.name} · ${curModel.name}`;
      }
    }

    providerSel.onchange = updateModelsForProvider;
    modelSel.onchange = updateModelDesc;

    const keyInput = $("apiKeysInput");
    if (keyInput) {
      keyInput.addEventListener("input", () => {
        localStorage.setItem(`mark_rdfz_keys_${providerSel.value}`, keyInput.value);
      });
    }

    updateModelsForProvider();
  }

  // ==================== 学科评分模板与 Prompt 组装 ====================
  function renderTemplatesDropdown() {
    const sel = $("templateSelect");
    const container = $("templateSlotsContainer");
    if (!sel || !container) return;

    if (!state.templatesCatalog.length) {
      sel.innerHTML = `<option value="generic">通用主观题 / 自定义评分细则</option>`;
      return;
    }

    sel.innerHTML = state.templatesCatalog
      .map((t) => `<option value="${esc(t.id)}">${esc(t.name)} (${esc(t.subject)})</option>`)
      .join("");

    function renderSlots() {
      const tpl = state.templatesCatalog.find((t) => t.id === sel.value) || state.templatesCatalog[0];
      if (!tpl) return;
      container.innerHTML = (tpl.slots || [])
        .map(
          (s) => `
          <div class="field">
            <label>${esc(s.label)}${s.required ? ' <span style="color:var(--danger)">*</span>' : ""}</label>
            <textarea data-slot-key="${esc(s.key)}" rows="3" placeholder="${esc(s.placeholder || "")}"></textarea>
          </div>`
        )
        .join("");

      if ($("promptPreview") && !$("promptPreview").value.trim()) {
        $("promptPreview").value = tpl.default_prompt || "";
        updateDetectedPointsHint();
      }
    }

    sel.onchange = () => {
      const tpl = state.templatesCatalog.find((t) => t.id === sel.value);
      renderSlots();
      if (tpl && $("promptPreview")) {
        $("promptPreview").value = tpl.default_prompt || "";
        updateDetectedPointsHint();
      }
    };

    renderSlots();
  }

  async function applyTemplateSlotsToPrompt() {
    const sel = $("templateSelect");
    if (!sel) return;
    const values = {};
    document.querySelectorAll("#templateSlotsContainer textarea[data-slot-key]").forEach((el) => {
      values[el.dataset.slotKey] = el.value;
    });
    const maxScore = parseFloat($("maxScoreInput")?.value || "10") || 10;
    try {
      const res = await api("/api/templates/render", {
        method: "POST",
        body: { template_id: sel.value, values, max_score: maxScore }
      });
      if (res.prompt) {
        $("promptPreview").value = res.prompt;
        updateDetectedPointsHint();
      }
    } catch (e) {
      alert("合成模板指令失败：" + e.message);
    }
  }

  async function generateRubricWithAi() {
    const btn = $("btnAiGenRubric");
    const provider = $("providerSelect")?.value || "gemini";
    const model = $("modelSelect")?.value || "";
    const apiKeys = $("apiKeysInput")?.value.trim() || "";
    if (!apiKeys) {
      alert("请先在第 3 步填入您的 API Key，再使用 AI 自动拆分评分细则。");
      $("apiKeysInput")?.focus();
      return;
    }

    const slots = {};
    document.querySelectorAll("#templateSlotsContainer textarea[data-slot-key]").forEach((el) => {
      slots[el.dataset.slotKey] = el.value.trim();
    });
    const questionText = slots.question || $("promptPreview")?.value.trim() || "";
    const answerText = slots.reference_answer || slots.answer || "";
    const maxScore = parseFloat($("maxScoreInput")?.value || "10") || 10;

    try {
      btn.classList.add("loading");
      btn.disabled = true;
      const res = await api("/api/ai/generate-rubric", {
        method: "POST",
        body: {
          provider,
          model,
          api_key: apiKeys,
          question_text: questionText,
          reference_answer: answerText,
          max_score: maxScore
        }
      });
      if (res.rubric) {
        const rubricArea = document.querySelector('#templateSlotsContainer textarea[data-slot-key="rubric_points"]');
        if (rubricArea) {
          rubricArea.value = res.rubric;
          $("templateSlotsDetails").open = true;
          await applyTemplateSlotsToPrompt();
        } else {
          $("promptPreview").value = res.rubric;
          updateDetectedPointsHint();
        }
      }
    } catch (e) {
      alert("AI 生成评分细则失败：" + e.message);
    } finally {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }

  function updateDetectedPointsHint() {
    const text = $("promptPreview")?.value || "";
    const pts = extractPointKeysClient(text);
    const hint = $("detectedPointsHint");
    if (hint) {
      hint.textContent = `自动识别采分点 (${pts.length}个)：${pts.join(", ")}`;
    }
  }

  // ==================== 登录、退出与会话恢复 ====================
  function initLoginEvents() {
    // 恢复上次填写的源站地址与用户名
    const savedUrl = localStorage.getItem("mark_rdfz_base_url") || "http://47.94.92.141";
    const savedUser = localStorage.getItem("mark_rdfz_username") || "";
    if ($("loginBaseUrl")) $("loginBaseUrl").value = savedUrl;
    if ($("loginUsername")) $("loginUsername").value = savedUser;

    // 快捷服务器地址胶囊
    document.querySelectorAll("#serverPills .server-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        $("loginBaseUrl").value = pill.dataset.url;
        $("loginUsername").focus();
      });
    });

    // 登录表单提交
    const form = $("loginForm");
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const base_url = $("loginBaseUrl").value.trim();
        const username = $("loginUsername").value.trim();
        const password = $("loginPassword").value;
        const errBox = $("loginErrorBox");
        const btn = $("loginBtn");
        errBox.hidden = true;

        if (!base_url || !username || !password) {
          errBox.textContent = "请完整填写本次阅卷服务器地址、用户名与密码";
          errBox.hidden = false;
          return;
        }

        try {
          btn.classList.add("loading");
          btn.disabled = true;
          const res = await api("/api/login", {
            method: "POST",
            body: { base_url, username, password }
          });
          localStorage.setItem("mark_rdfz_base_url", base_url);
          localStorage.setItem("mark_rdfz_username", username);
          enterWorkspace(res);
        } catch (err) {
          errBox.textContent = err.message || "登录失败，请检查服务器地址与账号密码";
          errBox.hidden = false;
        } finally {
          btn.classList.remove("loading");
          btn.disabled = false;
        }
      });
    }

    // 退出登录
    const logoutBtn = $("logoutBtn");
    if (logoutBtn) {
      logoutBtn.addEventListener("click", async () => {
        try {
          await api("/api/logout", { method: "POST" });
        } catch (_) {}
        if (state.monitorPollTimer) clearInterval(state.monitorPollTimer);
        $("appShell").hidden = true;
        $("hamburgerBtn").hidden = true;
        $("loginHero").hidden = false;
      });
    }
  }

  async function checkExistingSession() {
    try {
      const res = await api("/api/session");
      if (res.logged_in) {
        enterWorkspace(res);
      }
    } catch (_) {}
  }

  function enterWorkspace(sessionData) {
    state.session = {
      logged_in: true,
      base_url: sessionData.base_url || "",
      username: sessionData.username || "",
      subjects: sessionData.subjects || []
    };

    $("loginHero").hidden = true;
    $("appShell").hidden = false;
    $("hamburgerBtn").hidden = false;
    $("profileName").textContent = state.session.username;
    $("profileSite").textContent = state.session.base_url.replace(/^https?:\/\//, "");

    populateSubjects(state.session.subjects);

    if (sessionData.active_job_id) {
      state.activeJobId = sessionData.active_job_id;
      startMonitorPolling();
    }
  }

  // ==================== 第 1 步：科目、题号、源站进度与真实答卷预览 ====================
  function populateSubjects(subjects) {
    const subSel = $("subjectSelect");
    const srcSubSel = $("sourceRegradeSubSelect");
    if (!subSel) return;

    if (!subjects || !subjects.length) {
      subSel.innerHTML = `<option value="">未检测到分配给当前账号的阅卷科目</option>`;
      if (srcSubSel) srcSubSel.innerHTML = subSel.innerHTML;
      return;
    }

    const html = subjects
      .map((s) => `<option value="${esc(s.subid)}">${esc(s.subname || s.subid)}</option>`)
      .join("");
    subSel.innerHTML = html;
    if (srcSubSel) srcSubSel.innerHTML = html;

    onSubjectOrModeChange();
    if (srcSubSel) syncSourceRegradeQuestions();
  }

  async function onSubjectOrModeChange() {
    const subid = $("subjectSelect")?.value || "";
    const mode = $("modeSelect")?.value || "normal";
    const queSel = $("questionSelect");
    if (!subid || !queSel) return;

    state.currentSubject = subid;
    state.currentMode = mode;
    queSel.innerHTML = `<option value="">正在从源站同步题号列表...</option>`;

    try {
      const res = await api("/api/task/select-subject", {
        method: "POST",
        body: { subid, mode }
      });
      const questions = res.questions || [];
      if (!questions.length) {
        queSel.innerHTML = `<option value="">当前模式下暂无待评题目</option>`;
        $("previewPaperMeta").textContent = "该科目/模式下暂无分配题目";
        $("previewImgWrap").innerHTML = `<span class="hint">暂无可预览的题目</span>`;
        return;
      }

      queSel.innerHTML = questions
        .map((q) => `<option value="${esc(q.queid)}">${esc(q.quename || `第 ${q.queid} 题`)}</option>`)
        .join("");

      // 同步源站回评页的题号下拉框
      const srcQueSel = $("sourceRegradeQueSelect");
      if (srcQueSel && ($("sourceRegradeSubSelect")?.value === subid || !$("sourceRegradeSubSelect")?.value)) {
        srcQueSel.innerHTML = queSel.innerHTML;
      }

      await loadQuestionPreview();
    } catch (e) {
      queSel.innerHTML = `<option value="">读取题号失败：${esc(e.message)}</option>`;
    }
  }

  async function loadQuestionPreview() {
    const subid = $("subjectSelect")?.value || "";
    const mode = $("modeSelect")?.value || "normal";
    const queid = $("questionSelect")?.value || "";
    const splice = $("spliceSelect")?.value || "vertical";
    if (!subid || !queid) return;

    state.currentQuestion = queid;
    $("previewPaperMeta").textContent = "正在从源站抽取真实学生答卷与实时进度...";
    $("previewImgWrap").innerHTML = `<span class="hint">⏳ 正在拉取真实答卷切图...</span>`;

    try {
      const res = await api("/api/task/preview", {
        method: "POST",
        body: { subid, queid, mode, splice }
      });

      state.currentQuestionMeta = res.question || {};
      state.currentPreviewPaper = res.paper || null;

      // 满分与给分步长
      const q = res.question || {};
      if (q.max_score !== undefined && $("maxScoreInput")) {
        $("maxScoreInput").value = q.max_score;
      }
      const compText = q.is_composite
        ? `复合分步题（含 ${(q.sub_questions || []).length} 个子分步）`
        : "单题直接赋分";
      if ($("questionMetaText")) {
        $("questionMetaText").value = `满分 ${q.max_score ?? 10} 分 · 步长 ${q.step ?? 1} 分 · ${compText}`;
      }

      // 更新源站本题实时进度条与比例
      renderSourceProgressWidget(res.progress || {}, "create");

      // 渲染随机学生答卷预览图
      if (res.paper && res.paper.image_base64) {
        const pid = res.paper.paper_id || "未知卷号";
        $("previewPaperMeta").textContent = `样本卷号：${pid}（共 ${res.paper.image_count || 1} 张切块 · 点击图片可全屏滚轮缩放）`;
        $("previewImgWrap").innerHTML = `
          <img src="${res.paper.image_base64}" alt="学生答卷预览"
               style="max-height:380px;max-width:100%;border-radius:6px;cursor:zoom-in;box-shadow:var(--shadow-sm)"
               id="previewSampleImg" />
        `;
        const imgEl = $("previewSampleImg");
        if (imgEl) {
          imgEl.addEventListener("click", () => openLightbox(res.paper.image_base64));
        }
      } else {
        $("previewPaperMeta").textContent = res.paper_message || "当前队列暂无未评答卷";
        $("previewImgWrap").innerHTML = `<span class="hint">${esc(res.paper_message || "当前题目队列中暂无待评答卷（可能已全部评完），您仍可前往「任意试卷核查与改分」查看或修改已评试卷。")}</span>`;
      }
    } catch (e) {
      $("previewPaperMeta").textContent = "加载预览失败：" + e.message;
      $("previewImgWrap").innerHTML = `<span class="hint error">加载失败：${esc(e.message)}</span>`;
    }
  }

  function renderSourceProgressWidget(prog, targetPrefix) {
    const total = Number(prog.total_count || 0);
    const marked = Number(prog.marked_count || 0);
    const myMarked = Number(prog.my_marked_count || 0);
    const avg = prog.avg_score !== undefined && prog.avg_score !== null ? prog.avg_score : "—";
    const pct = total > 0 ? Math.min(100, Math.round((marked / total) * 1000) / 10) : (prog.progress_pct || 0);

    if (targetPrefix === "create") {
      if ($("createSourceProgressText")) {
        $("createSourceProgressText").textContent = total > 0
          ? `已评 ${marked} / 总计 ${total} 份 (${pct}%)`
          : `本教师已评 ${myMarked} 份`;
      }
      if ($("createSourceProgressBar")) {
        $("createSourceProgressBar").style.width = `${Math.min(100, pct)}%`;
      }
      if ($("createSourceSubHint")) {
        $("createSourceSubHint").textContent = `👤 本教师账号累计已评：${myMarked} 份 · 📈 源站当前均分：${avg}`;
      }
    }

    // 同步更新监控页 HUD 的源站进度条
    if ($("hudSourceProgressLabel")) {
      $("hudSourceProgressLabel").textContent = total > 0
        ? `${marked} / ${total} (${pct}%)`
        : `本号已评 ${myMarked} 份`;
    }
    if ($("hudSourceProgressBar")) {
      $("hudSourceProgressBar").style.width = `${Math.min(100, pct)}%`;
    }
    if ($("hudSourceSubLabel")) {
      $("hudSourceSubLabel").textContent = `本教师账号累计已评 ${myMarked} 份 · 源站均分 ${avg}`;
    }
  }

  // ==================== 创建并启动 AI 试评 / 正式评阅任务 ====================
  async function startGradingJob(dryRun) {
    const errBox = $("createJobError");
    if (errBox) errBox.hidden = true;

    const subid = $("subjectSelect")?.value || "";
    const subname = $("subjectSelect")?.selectedOptions?.[0]?.textContent || subid;
    const mode = $("modeSelect")?.value || "normal";
    const queid = $("questionSelect")?.value || "";
    const quename = $("questionSelect")?.selectedOptions?.[0]?.textContent || queid;
    const max_score = parseFloat($("maxScoreInput")?.value || "10") || 10;
    const prompt = $("promptPreview")?.value.trim() || "";
    const provider = $("providerSelect")?.value || "gemini";
    const model = $("modelSelect")?.value || "";
    const thinking_level = $("thinkingSelect")?.value || "LOW";
    const api_keys = $("apiKeysInput")?.value.trim() || "";
    const concurrency = parseInt($("concurrencyInput")?.value || "2", 10) || 2;
    const splice = $("spliceSelect")?.value || "vertical";

    const trialCount = parseInt($("trialCountInput")?.value || "10", 10) || 10;
    const formalMax = parseInt($("maxPapersInput")?.value || "0", 10) || 0;
    const max_papers = dryRun ? trialCount : formalMax;

    if (!subid || !queid) {
      showCreateError("请先在第 1 步选择考试科目与题目编号");
      return;
    }
    if (!prompt) {
      showCreateError("请先在第 2 步填写或确认评分指令 (Prompt)");
      $("promptPreview")?.focus();
      return;
    }
    if (!api_keys) {
      showCreateError("请先在第 3 步填入您的个人 API Key");
      $("apiKeysInput")?.focus();
      return;
    }

    const btn = dryRun ? $("btnStartTrial") : $("btnStartFormal");
    try {
      btn.classList.add("loading");
      btn.disabled = true;

      const res = await api("/api/job/create", {
        method: "POST",
        body: {
          subid,
          subname,
          queid,
          quename,
          mode,
          max_score,
          prompt,
          provider,
          model,
          thinking_level,
          api_keys,
          dry_run: dryRun,
          max_papers,
          concurrency,
          splice
        }
      });

      state.activeJobId = res.job_id;
      state.activeJob = res.job;
      switchTab("monitor");
      startMonitorPolling();
    } catch (e) {
      showCreateError(e.message);
    } finally {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }

  function showCreateError(msg) {
    const errBox = $("createJobError");
    if (errBox) {
      errBox.textContent = "⚠️ " + msg;
      errBox.hidden = false;
    } else {
      alert(msg);
    }
  }

  // ==================== 实时监控 & 阅卷进程比例 ====================
  function startMonitorPolling() {
    if (state.monitorPollTimer) clearInterval(state.monitorPollTimer);
    refreshMonitorNow();
    state.monitorPollTimer = setInterval(() => {
      refreshMonitorNow();
    }, 2200);
  }

  async function refreshMonitorNow() {
    if (!state.activeJobId) {
      // 尝试拉取最近一个任务
      try {
        const h = await api("/api/jobs/history");
        if (h.jobs && h.jobs.length > 0) {
          state.activeJobId = h.jobs[0].job_id;
        }
      } catch (_) {}
    }
    if (!state.activeJobId) return;

    try {
      const [liveRes, tasksRes] = await Promise.all([
        api(`/api/job/${state.activeJobId}/live`),
        api(`/api/job/${state.activeJobId}/tasks?limit=300`)
      ]);

      state.activeJob = liveRes;
      state.monitorTasks = tasksRes.tasks || [];
      renderMonitorView(liveRes, state.monitorTasks);

      // 若任务已结束，放缓轮询
      if (["completed", "trial_completed", "stopped", "error"].includes(liveRes.status)) {
        if (state.monitorPollTimer) {
          clearInterval(state.monitorPollTimer);
          state.monitorPollTimer = null;
        }
      }
    } catch (_) {}
  }

  function renderMonitorView(job, tasks) {
    if (!job) return;
    const stats = job.stats || {};
    const statusMap = {
      running: "🟢 正在批阅中",
      paused: "⏸ 已暂停",
      trial_completed: "🧪 试评已完成（待教师审阅确认）",
      completed: "✅ 评阅任务已完成",
      stopped: "⏹ 已人工停止",
      error: "❌ 任务异常中断"
    };

    // 侧边栏状态徽章
    if ($("sidebarJobText")) {
      $("sidebarJobText").textContent = statusMap[job.status] || job.status;
    }

    // 顶部控制按钮显隐
    const isRunning = job.status === "running";
    const isPaused = job.status === "paused";
    if ($("btnPauseJob")) $("btnPauseJob").hidden = !isRunning;
    if ($("btnResumeJob")) $("btnResumeJob").hidden = !isPaused;
    if ($("btnStopJob")) $("btnStopJob").hidden = !(isRunning || isPaused);

    // HUD 顶部信息
    if ($("hudStatusBadge")) $("hudStatusBadge").textContent = statusMap[job.status] || job.status;
    if ($("hudModeBadge")) {
      $("hudModeBadge").textContent = job.dry_run ? "🧪 试评模式 (Dry Run)" : "🚀 正式写分模式";
      $("hudModeBadge").style.background = job.dry_run ? "var(--accent-bg)" : "var(--success-bg)";
    }
    if ($("hudJobMeta")) {
      $("hudJobMeta").textContent = `${job.subname || job.subid} · ${job.quename || `第${job.queid}题`} · 模型: ${job.model} (${job.thinking_level || "LOW"})`;
    }
    if ($("hudSpeedText")) {
      $("hudSpeedText").textContent = `${stats.speed_per_min || 0} 份/分`;
    }

    // 进度条 ①：本任务进度与比例
    const graded = Number(stats.graded || 0);
    const submitted = Number(stats.submitted || 0);
    const dryDone = Number(stats.dry_run_done || 0);
    const targetMax = Number(job.max_papers || 0);
    const srcProg = job.source_progress || {};
    const srcRemaining = Math.max(0, Number(srcProg.total_count || 0) - Number(srcProg.marked_count || 0));
    const effectiveTotal = targetMax > 0 ? targetMax : (graded + srcRemaining || graded || 1);
    const taskPct = effectiveTotal > 0 ? Math.min(100, Math.round((graded / effectiveTotal) * 1000) / 10) : 0;

    if ($("hudTaskProgressLabel")) {
      $("hudTaskProgressLabel").textContent = targetMax > 0
        ? `${graded} / ${targetMax} (${taskPct}%)`
        : `已评 ${graded} 份 (${taskPct}%)`;
    }
    if ($("hudTaskProgressBar")) {
      $("hudTaskProgressBar").style.width = `${taskPct}%`;
    }
    if ($("hudTaskSubLabel")) {
      $("hudTaskSubLabel").textContent = `本次已评 ${graded} 份 · 已写回源站 ${submitted} 份 · 试评样本 ${dryDone} 份 · 失败 ${stats.failed || 0} 份`;
    }

    // 进度条 ②：源站同题总进程与比例
    renderSourceProgressWidget(srcProg, "monitor");

    // 试评审阅决策横幅
    const trialFlow = $("monitorTrialFlow");
    if (trialFlow) {
      const showTrialBanner = Boolean(job.dry_run || dryDone > 0);
      trialFlow.hidden = !showTrialBanner;
      if (showTrialBanner) {
        $("trialBannerTitle").textContent = job.status === "trial_completed"
          ? `🧪 试评已完成（共完成 ${dryDone} 份试评样本，尚未写回源站）`
          : `🧪 试评进行中（已评 ${dryDone} 份试评样本，仅保存在本机供核查）`;
      }
    }

    // 同步动态 Prompt 编辑器内容（仅当未聚焦时同步）
    const livePromptEl = $("livePromptTextarea");
    if (livePromptEl && document.activeElement !== livePromptEl && !livePromptEl.value) {
      livePromptEl.value = job.prompt || "";
    }

    // 核心统计与比例卡片
    if ($("statGraded")) $("statGraded").textContent = graded;
    if ($("statSubmitted")) $("statSubmitted").textContent = submitted;
    if ($("statDryRun")) $("statDryRun").textContent = dryDone;
    if ($("statFullScore")) {
      $("statFullScore").innerHTML = `${stats.full_score_count || 0} <small style="font-size:13px;font-weight:normal">(${stats.full_score_pct || 0}%)</small>`;
    }
    if ($("statZeroScore")) {
      $("statZeroScore").innerHTML = `${stats.zero_score_count || 0} <small style="font-size:13px;font-weight:normal">(${stats.zero_score_pct || 0}%)</small>`;
    }
    if ($("statWorthSaving")) $("statWorthSaving").textContent = stats.worth_saving_count || 0;
    if ($("statFailed")) $("statFailed").textContent = stats.failed || 0;
    if ($("statAvgScore")) {
      $("statAvgScore").innerHTML = graded > 0
        ? `${stats.avg_score ?? 0} <small style="font-size:12.5px;font-weight:normal">(${stats.scoring_rate_pct || 0}%)</small>`
        : "—";
    }

    // 耗时统计
    if ($("timingStatsText")) {
      const avgSecPerPaper = graded > 0 && stats.elapsed_sec ? (stats.elapsed_sec / graded).toFixed(1) : "—";
      $("timingStatsText").textContent =
        `开始时间：${fmtTime(job.started_at)} · 已运行时长：${fmtDuration(stats.elapsed_sec)} · 平均每份总耗时：${avgSecPerPaper}秒 · AI 平均识图延迟：${stats.avg_latency_ms || 0} ms`;
    }

    // 实时分数分布比例柱状图
    renderScoreHistogram(stats.score_distribution || {}, graded);

    // 各得分点命中率与比例
    renderPointHits(stats.point_hits || {});

    // 渲染批阅试卷卡片墙
    renderTaskCards(tasks, $("monitorTaskCards"), "monitor");
  }

  function renderScoreHistogram(dist, totalGraded) {
    const box = $("hudChartBars");
    const sumEl = $("hudScoreDistSummary");
    if (!box) return;

    const entries = Object.entries(dist || {}).sort((a, b) => parseFloat(a[0]) - parseFloat(b[0]));
    if (!entries.length || !totalGraded) {
      box.innerHTML = `<div class="hint" style="margin:auto;font-size:12px">暂无批阅分值数据</div>`;
      if (sumEl) sumEl.textContent = "—";
      return;
    }

    const maxCnt = Math.max(...entries.map(([, c]) => Number(c)), 1);
    if (sumEl) {
      sumEl.textContent = state.monitorScoreFilter !== null
        ? `当前筛选：${state.monitorScoreFilter} 分（再次点击柱条取消筛选）`
        : `共 ${entries.length} 个分值档位`;
    }

    box.innerHTML = entries
      .map(([scoreKey, cnt]) => {
        const pct = totalGraded > 0 ? Math.round((Number(cnt) / totalGraded) * 1000) / 10 : 0;
        const heightPx = Math.max(12, Math.round((Number(cnt) / maxCnt) * 52));
        const active = state.monitorScoreFilter === String(scoreKey);
        return `
          <div class="hist-bar-col" data-score="${esc(scoreKey)}"
               style="display:flex;flex-direction:column;align-items:center;min-width:44px;cursor:pointer;padding:2px 4px;border-radius:6px;background:${active ? "var(--primary-bg)" : "transparent"}"
               title="${esc(scoreKey)}分：${cnt}份 (${pct}%) · 点击按此分值筛选">
            <span style="font-size:10.5px;color:var(--ink-soft);font-family:var(--font-mono)">${cnt} (${pct}%)</span>
            <div style="width:22px;height:${heightPx}px;background:${active ? "var(--accent)" : "var(--primary)"};border-radius:4px 4px 0 0;margin:3px 0"></div>
            <strong style="font-size:11.5px;color:var(--primary-deep)">${esc(scoreKey)}分</strong>
          </div>
        `;
      })
      .join("");

    box.querySelectorAll(".hist-bar-col").forEach((col) => {
      col.addEventListener("click", () => {
        const sc = col.dataset.score;
        state.monitorScoreFilter = state.monitorScoreFilter === sc ? null : sc;
        renderMonitorView(state.activeJob, state.monitorTasks);
      });
    });
  }

  function renderPointHits(pointHits) {
    const box = $("pointHitsList");
    if (!box) return;
    const keys = Object.keys(pointHits || {});
    if (!keys.length) {
      box.innerHTML = `<span class="hint" style="font-size:12px">待产生批阅数据后自动统计各采分点命中率</span>`;
      return;
    }
    box.innerHTML = keys
      .map((k) => {
        const p = pointHits[k];
        return `
          <div style="padding:6px 10px;border:1px solid var(--line);border-radius:var(--radius-sm);background:rgba(255,255,255,0.65);font-size:12px">
            <strong style="color:var(--primary-deep)">${esc(k)}</strong>：
            命中率 <b>${p.hit_rate_pct ?? 0}%</b> (${p.hit}/${p.total}) · 均分 ${p.avg_score ?? 0}
          </div>
        `;
      })
      .join("");
  }

  // ==================== 渲染试卷卡片墙（任意试卷点开核查与改分） ====================
  function renderTaskCards(tasks, container, contextType) {
    if (!container) return;

    let filtered = Array.isArray(tasks) ? [...tasks] : [];

    if (contextType === "monitor") {
      const f = $("monitorFilterSelect")?.value || "all";
      const q = ($("monitorSearchInput")?.value || "").trim().toLowerCase();
      filtered = filterTaskItems(filtered, f, q, state.monitorScoreFilter);
      if ($("taskCardsCountHint")) {
        $("taskCardsCountHint").textContent = `显示 ${filtered.length} / 共 ${tasks.length} 份（点击任意卡片打开核查与改分）`;
      }
    } else if (contextType === "regrade-local") {
      const f = $("regradeStatusSelect")?.value || "all";
      const q = ($("regradeLocalSearch")?.value || "").trim().toLowerCase();
      filtered = filterTaskItems(filtered, f, q, null);
    }

    if (!filtered.length) {
      container.innerHTML = `<div class="hint" style="padding:28px;text-align:center">当前筛选条件下暂无试卷记录</div>`;
      return;
    }

    container.innerHTML = filtered
      .map((t, idx) => {
        const score = t.score ?? 0;
        const maxScore = t.max_score ?? 10;
        const pct = maxScore > 0 ? Math.round((score / maxScore) * 100) : 0;
        const statusBadge = getTaskStatusBadge(t);
        const bdPills = (t.breakdown || [])
          .slice(0, 4)
          .map((b) => `<span style="padding:1px 6px;border-radius:999px;background:var(--primary-bg);font-size:11px;color:var(--primary-deep)">${esc(b.label)}: ${b.score}</span>`)
          .join(" ");

        return `
          <article class="task-card is-reviewable" data-idx="${idx}" style="cursor:pointer;border:1px solid var(--line);border-radius:var(--radius);padding:12px;background:var(--panel-bg-soft);display:flex;flex-direction:column;gap:8px;transition:0.18s">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
              <strong style="font-family:var(--font-mono);font-size:12.5px;color:var(--ink)" title="试卷流水号">#${esc(t.paper_id)}</strong>
              ${statusBadge}
            </div>

            ${
              t.image_base64
                ? `<div style="height:110px;background:#fff;border:1px solid var(--line);border-radius:6px;overflow:hidden;display:flex;align-items:center;justify-content:center">
                     <img src="${t.image_base64}" alt="答卷缩略图" style="max-height:100%;max-width:100%;object-fit:contain" loading="lazy" />
                   </div>`
                : ""
            }

            <div style="display:flex;justify-content:space-between;align-items:baseline">
              <div>
                <span style="font-family:var(--font-serif);font-size:22px;font-weight:700;color:var(--primary-deep)">${score}</span>
                <small style="color:var(--ink-soft)"> / ${maxScore} 分 (${pct}%)</small>
              </div>
              <span style="font-size:11px;color:var(--primary-deep);font-weight:600">🔍 点开核查/改分 →</span>
            </div>

            ${bdPills ? `<div style="display:flex;flex-wrap:wrap;gap:4px">${bdPills}</div>` : ""}

            <p style="font-size:12px;color:var(--ink-soft);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.45">
              ${esc(t.overall_comment || t.error || "点击查看详细批阅依据与原图")}
            </p>
          </article>
        `;
      })
      .join("");

    container.querySelectorAll(".task-card").forEach((card) => {
      card.addEventListener("click", () => {
        const i = parseInt(card.dataset.idx, 10);
        openReviewModal(filtered, i);
      });
    });
  }

  function filterTaskItems(list, filterType, query, exactScore) {
    return list.filter((t) => {
      if (exactScore !== null && exactScore !== undefined) {
        const sc = Math.round(Number(t.score || 0) * 10) / 10;
        const key = sc === Math.floor(sc) ? String(Math.floor(sc)) : String(sc);
        if (key !== String(exactScore)) return false;
      }
      if (filterType === "completed" && !t.submitted) return false;
      if (filterType === "dry_run_done" && t.status !== "dry_run_done") return false;
      if (filterType === "full_score" && Number(t.score || 0) < Number(t.max_score || 10)) return false;
      if (filterType === "zero_score" && Number(t.score || 0) > 0) return false;
      if (filterType === "worth_saving" && !t.worth_saving) return false;
      if (filterType === "regraded" && !t.regraded) return false;
      if (filterType === "failed" && t.status !== "failed") return false;

      if (query) {
        const hay = `${t.paper_id || ""} ${t.score ?? ""} ${t.overall_comment || ""} ${t.student_answer_ocr || ""}`.toLowerCase();
        if (!hay.includes(query)) return false;
      }
      return true;
    });
  }

  function getTaskStatusBadge(t) {
    if (t.regraded) {
      return `<span class="status-badge" style="background:var(--primary-bg);color:var(--primary-deep)">✏️ 已人工核查改分</span>`;
    }
    if (t.status === "completed" || t.submitted) {
      return `<span class="status-badge" style="background:var(--success-bg);color:var(--success)">✅ 已写分</span>`;
    }
    if (t.status === "dry_run_done") {
      return `<span class="status-badge" style="background:var(--accent-bg);color:var(--primary-deep)">🧪 试评样本</span>`;
    }
    if (t.status === "failed") {
      return `<span class="status-badge" style="background:var(--danger-bg);color:var(--danger)">❌ 失败</span>`;
    }
    return `<span class="status-badge">${esc(t.status || "已评")}</span>`;
  }

  // ==================== TAB 3: 任意试卷核查与改分（本机库 + 源站历史回评库） ====================
  async function loadRegradeTab() {
    if (state.regradeMode === "local") {
      await loadLocalRegradeList();
    } else {
      await syncSourceRegradeQuestions();
    }
  }

  async function loadLocalRegradeList() {
    try {
      const hRes = await api("/api/jobs/history");
      const jobs = hRes.jobs || [];
      const jobSel = $("regradeJobSelect");
      if (jobSel) {
        const curVal = jobSel.value;
        jobSel.innerHTML =
          `<option value="">全部任务 (${jobs.length}个)</option>` +
          jobs
            .map((j) => `<option value="${esc(j.job_id)}">[${esc(j.job_id)}] ${esc(j.subname || j.subid)} ${esc(j.quename || j.queid)} (${j.stats?.graded || 0}份)</option>`)
            .join("");
        if (curVal) jobSel.value = curVal;
      }

      const selectedJobId = jobSel?.value || state.activeJobId || (jobs[0]?.job_id || "");
      if (!selectedJobId) {
        $("regradeLocalCards").innerHTML = `<div class="hint" style="padding:28px;text-align:center">暂无本机批阅记录，您可切换至右上角「🌐 源站历史已评卷回评库」直接调取源站任意试卷改分。</div>`;
        return;
      }

      const tRes = await api(`/api/job/${selectedJobId}/tasks?limit=500`);
      state.regradeLocalTasks = tRes.tasks || [];
      renderTaskCards(state.regradeLocalTasks, $("regradeLocalCards"), "regrade-local");
    } catch (e) {
      $("regradeLocalCards").innerHTML = `<div class="hint error" style="padding:20px">${esc(e.message)}</div>`;
    }
  }

  async function syncSourceRegradeQuestions() {
    const subid = $("sourceRegradeSubSelect")?.value || $("subjectSelect")?.value || "";
    const queSel = $("sourceRegradeQueSelect");
    if (!subid || !queSel) return;
    try {
      const res = await api("/api/task/select-subject", {
        method: "POST",
        body: { subid, mode: "normal" }
      });
      const qs = res.questions || [];
      queSel.innerHTML = qs
        .map((q) => `<option value="${esc(q.queid)}">${esc(q.quename || `第 ${q.queid} 题`)}</option>`)
        .join("");
    } catch (_) {}
  }

  async function fetchSourceReviewPapers() {
    const subid = $("sourceRegradeSubSelect")?.value || "";
    const queid = $("sourceRegradeQueSelect")?.value || "";
    const scoreFilter = $("sourceRegradeScoreFilter")?.value.trim() || "";
    const box = $("regradeSourceCards");
    const btn = $("btnFetchSourceReviews");
    if (!subid || !queid) {
      alert("请先选择科目与题号");
      return;
    }

    try {
      btn.classList.add("loading");
      btn.disabled = true;
      box.innerHTML = `<div class="hint" style="padding:28px;text-align:center">⏳ 正在从源站拉取已评试卷列表...</div>`;

      const res = await api("/api/source/review-list", {
        method: "POST",
        body: { subid, queid, score_filter: scoreFilter || null }
      });

      const items = (res.reviews || []).map((r) => ({
        task_id: `src_${r.paper_id}`,
        paper_id: r.paper_id,
        encrypt_code: r.encrypt_code || "",
        subid,
        queid,
        score: r.score,
        max_score: r.max_score || parseFloat($("maxScoreInput")?.value || "10") || 10,
        status: "completed",
        submitted: true,
        is_source_review: true,
        overall_comment: `源站已评试卷 · 评阅时间：${r.mark_time || "—"} · 类型：${r.paper_type || "正评卷"}`
      }));

      state.regradeSourceTasks = items;
      if (!items.length) {
        box.innerHTML = `<div class="hint" style="padding:28px;text-align:center">源站未返回符合条件的已评试卷</div>`;
        return;
      }
      renderTaskCards(items, box, "regrade-source");
    } catch (e) {
      box.innerHTML = `<div class="hint error" style="padding:24px">拉取源站回评卷失败：${esc(e.message)}</div>`;
    } finally {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }

  // ==================== 批阅详情 · 任意试卷核查与修改分数弹窗 (#taskReviewModal) ====================
  async function openReviewModal(list, index) {
    if (!Array.isArray(list) || index < 0 || index >= list.length) return;
    state.modalList = list;
    state.modalIndex = index;
    const item = list[index];
    state.modalCurrentItem = item;

    const modal = $("taskReviewModal");
    modal.hidden = false;
    $("modalWholePaperBox").hidden = true;
    $("modalRegradeMsg").hidden = true;

    $("modalTitle").textContent = `🔍 试卷核查与修改分数 · #${item.paper_id || "—"}`;
    $("modalSubTitle").textContent = `第 ${index + 1} / ${list.length} 份 · 题号 ${item.queid || state.currentQuestion || "—"}`;
    $("btnModalPrev").disabled = index <= 0;
    $("btnModalNext").disabled = index >= list.length - 1;

    const maxScore = Number(item.max_score || $("maxScoreInput")?.value || 10);
    $("modalScoreLabel").textContent = `核定总分（满分 ${maxScore} 分）`;
    $("modalScoreInput").max = maxScore;
    $("modalScoreInput").value = item.score ?? 0;
    $("modalReviewNote").value = item.review_note || "";
    $("modalStatusBadge").textContent = item.regraded
      ? "✏️ 已人工改分"
      : item.submitted
      ? "✅ 已写回源站"
      : "🧪 试评未写分";

    // Prompt 展示
    $("modalPromptText").textContent = state.activeJob?.prompt || $("promptPreview")?.value || "—";

    // 复合题分步得分输入框
    renderModalSubScores(item);

    // AI 批阅明细
    renderModalAiDetails(item, maxScore);

    // 答卷原图加载（若为源站历史回评卷且尚无 base64，实时向源站拉取高清原图）
    const imgEl = $("modalAnswerImg");
    if (item.image_base64) {
      imgEl.src = item.image_base64;
    } else if (item.paper_id) {
      imgEl.src = "";
      imgEl.alt = "正在从源站拉取该卷高清作答切图...";
      try {
        const dRes = await api("/api/source/review-detail", {
          method: "POST",
          body: {
            subid: item.subid || state.currentSubject || $("subjectSelect")?.value,
            queid: item.queid || state.currentQuestion || $("questionSelect")?.value,
            paper_id: item.paper_id,
            splice: $("spliceSelect")?.value || "vertical"
          }
        });
        if (dRes.detail && dRes.detail.image_base64) {
          item.image_base64 = dRes.detail.image_base64;
          item.encrypt_code = dRes.detail.encrypt_code || item.encrypt_code;
          imgEl.src = item.image_base64;
        }
      } catch (e) {
        imgEl.alt = "拉取原图失败：" + e.message;
      }
    }
  }

  function renderModalSubScores(item) {
    const wrap = $("modalSubScoresWrap");
    const grid = $("modalSubScoresGrid");
    if (!wrap || !grid) return;

    const subScores = item.sub_scores && typeof item.sub_scores === "object" ? item.sub_scores : {};
    const keys = Object.keys(subScores);
    if (!keys.length) {
      wrap.hidden = true;
      grid.innerHTML = "";
      return;
    }

    wrap.hidden = false;
    grid.innerHTML = keys
      .map(
        (k) => `
        <div class="field">
          <label style="font-size:11px">小题 ${esc(k)}</label>
          <input type="number" step="0.5" min="0" data-sub-queid="${esc(k)}" value="${esc(subScores[k])}"
                 style="padding:6px 8px;font-weight:600" />
        </div>`
      )
      .join("");

    grid.querySelectorAll("input[data-sub-queid]").forEach((inp) => {
      inp.addEventListener("input", () => {
        let sum = 0;
        grid.querySelectorAll("input[data-sub-queid]").forEach((el) => {
          sum += parseFloat(el.value || "0") || 0;
        });
        $("modalScoreInput").value = Math.round(sum * 10) / 10;
      });
    });
  }

  function renderModalAiDetails(item, maxScore) {
    const score = item.score ?? 0;
    const pct = maxScore > 0 ? Math.round((score / maxScore) * 100) : 0;
    $("modalAiScoreSummary").textContent = `${score} / ${maxScore} 分 (${pct}%)`;
    $("modalOverallComment").textContent = item.overall_comment || "—";
    $("modalOcrText").textContent = item.student_answer_ocr || "（未记录文字识别文本）";

    const bdBox = $("modalBreakdownList");
    const bd = item.breakdown || [];
    if (!bd.length) {
      bdBox.innerHTML = `<div class="hint" style="font-size:12px">暂无分项采分点明细</div>`;
      return;
    }
    bdBox.innerHTML = bd
      .map(
        (b) => `
        <div style="padding:8px 10px;border:1px solid var(--line);border-radius:var(--radius-sm);background:rgba(255,255,255,0.6)">
          <div style="display:flex;justify-content:space-between;font-size:12.5px">
            <strong style="color:var(--primary-deep)">${esc(b.label)}</strong>
            <b style="color:var(--ink)">得分：${b.score}${b.max ? ` / ${b.max}` : ""}</b>
          </div>
          ${b.reason ? `<div style="font-size:12px;color:var(--ink-soft);margin-top:3px">${esc(b.reason)}</div>` : ""}
        </div>`
      )
      .join("");
  }

  async function saveModalRegradeScore() {
    const item = state.modalCurrentItem;
    if (!item) return;

    const newScore = parseFloat($("modalScoreInput").value);
    const maxScore = Number(item.max_score || $("maxScoreInput")?.value || 10);
    if (Number.isNaN(newScore) || newScore < 0 || newScore > maxScore) {
      alert(`请输入 0 ~ ${maxScore} 之间的合法分数`);
      return;
    }

    const subScores = {};
    document.querySelectorAll("#modalSubScoresGrid input[data-sub-queid]").forEach((el) => {
      subScores[el.dataset.subQueid] = parseFloat(el.value || "0") || 0;
    });

    const btn = $("btnModalSaveScore");
    const msgEl = $("modalRegradeMsg");
    msgEl.hidden = true;

    try {
      btn.classList.add("loading");
      btn.disabled = true;

      const res = await api("/api/paper/regrade", {
        method: "POST",
        body: {
          job_id: item.job_id || state.activeJobId || null,
          task_id: item.task_id || null,
          paper_id: item.paper_id,
          subid: item.subid || state.currentSubject || $("subjectSelect")?.value,
          queid: item.queid || state.currentQuestion || $("questionSelect")?.value,
          new_score: newScore,
          sub_scores: Object.keys(subScores).length ? subScores : null,
          encrypt_code: item.encrypt_code || null,
          comment: $("modalReviewNote").value.trim() || null
        }
      });

      item.score = res.new_score;
      item.submitted = true;
      item.regraded = true;
      item.status = "completed";
      if (Object.keys(subScores).length) item.sub_scores = subScores;

      $("modalStatusBadge").textContent = "✅ 已写回源站";
      renderModalAiDetails(item, maxScore);

      const verifyText = res.readback_verified
        ? `（源站读回校验通过：${res.readback_score} 分）`
        : "（已提交至源站）";
      msgEl.className = "hint success";
      msgEl.textContent = `✅ 分数已成功修改为 ${res.new_score} 分并同步写回源站 ${verifyText}`;
      msgEl.hidden = false;

      // 刷新监控与列表卡片
      refreshMonitorNow();
    } catch (e) {
      msgEl.className = "hint error";
      msgEl.textContent = "❌ 改分写回失败：" + e.message;
      msgEl.hidden = false;
    } finally {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }

  async function runModalAiRegrade() {
    const item = state.modalCurrentItem;
    if (!item) return;

    const apiKeys = $("apiKeysInput")?.value.trim() || "";
    if (!apiKeys && !state.activeJobId) {
      alert("请先在「创建任务」第 3 步填入您的 API Key");
      return;
    }

    const btn = $("btnModalAiRegrade");
    const msgEl = $("modalRegradeMsg");
    msgEl.hidden = true;

    try {
      btn.classList.add("loading");
      btn.disabled = true;

      const res = await api("/api/paper/ai-regrade", {
        method: "POST",
        body: {
          job_id: item.job_id || state.activeJobId || null,
          task_id: item.task_id || null,
          paper_id: item.paper_id,
          subid: item.subid || state.currentSubject || $("subjectSelect")?.value,
          queid: item.queid || state.currentQuestion || $("questionSelect")?.value,
          provider: $("providerSelect")?.value || "gemini",
          model: $("modelSelect")?.value || "",
          thinking_level: $("thinkingSelect")?.value || "LOW",
          api_key: apiKeys,
          prompt: state.activeJob?.prompt || $("promptPreview")?.value || "",
          max_score: Number(item.max_score || $("maxScoreInput")?.value || 10),
          auto_submit: false
        }
      });

      const r = res.ai_result || {};
      item.score = r.total_score ?? item.score;
      item.breakdown = r.breakdown || item.breakdown;
      item.overall_comment = r.overall_comment || item.overall_comment;
      item.student_answer_ocr = r.student_answer_ocr || item.student_answer_ocr;
      if (r.sub_scores) item.sub_scores = r.sub_scores;

      $("modalScoreInput").value = item.score;
      renderModalSubScores(item);
      renderModalAiDetails(item, Number(item.max_score || 10));

      msgEl.className = "hint success";
      msgEl.textContent = `🤖 AI 重评完成，建议得分：${item.score} 分。如需写入源站，请点击左侧「💾 确认修改并写回源站」。`;
      msgEl.hidden = false;
    } catch (e) {
      msgEl.className = "hint error";
      msgEl.textContent = "❌ AI 重评失败：" + e.message;
      msgEl.hidden = false;
    } finally {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }

  async function viewModalWholePaper() {
    const item = state.modalCurrentItem;
    if (!item || !item.paper_id) return;

    const btn = $("btnModalWholePaper");
    const box = $("modalWholePaperBox");
    const grid = $("modalWholePaperGrid");

    try {
      btn.classList.add("loading");
      btn.disabled = true;
      const res = await api("/api/paper/whole-paper", {
        method: "POST",
        body: {
          subid: item.subid || state.currentSubject || $("subjectSelect")?.value,
          paper_id: item.paper_id,
          encrypt_code: item.encrypt_code || null
        }
      });

      const sheets = res.sheets || [];
      box.hidden = false;
      if (!sheets.length) {
        grid.innerHTML = `<div class="hint">源站未返回该考生的整卷原图</div>`;
        return;
      }
      grid.innerHTML = sheets
        .map(
          (s) => `
          <div class="whole-paper-card">
            <strong style="font-size:12px;color:var(--primary-deep)">${esc(s.label)}（点击可全屏缩放）</strong>
            <img src="${s.image_base64}" alt="${esc(s.label)}" data-full-src="${s.image_base64}" />
          </div>`
        )
        .join("");

      grid.querySelectorAll("img[data-full-src]").forEach((im) => {
        im.addEventListener("click", () => openLightbox(im.dataset.fullSrc));
      });
    } catch (e) {
      alert("获取考生整张试卷失败：" + e.message);
    } finally {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }

  // ==================== TAB 4: AI 教学分析报告与历史任务 ====================
  async function loadHistoryJobsAndReport() {
    try {
      const res = await api("/api/jobs/history");
      const jobs = res.jobs || [];

      const repSel = $("reportJobSelect");
      if (repSel) {
        repSel.innerHTML =
          `<option value="">当前活动任务 / 全部已评样本</option>` +
          jobs
            .map((j) => `<option value="${esc(j.job_id)}">[${esc(j.job_id)}] ${esc(j.subname || j.subid)} ${esc(j.quename || j.queid)} (${j.stats?.graded || 0}份)</option>`)
            .join("");
      }

      const listEl = $("historyJobsList");
      if (listEl) {
        if (!jobs.length) {
          listEl.innerHTML = `<div class="hint">暂无历史任务记录</div>`;
        } else {
          listEl.innerHTML = jobs
            .map((j) => {
              const st = j.stats || {};
              return `
                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;padding:10px 14px;border:1px solid var(--line);border-radius:var(--radius-sm);background:var(--panel-bg-soft)">
                  <div>
                    <strong style="color:var(--primary-deep)">[${esc(j.job_id)}] ${esc(j.subname || j.subid)} · ${esc(j.quename || j.queid)}</strong>
                    <div class="hint" style="font-size:12px;margin-top:2px">
                      模型: ${esc(j.model)} · 已评 ${st.graded || 0} 份 (已写分 ${st.submitted || 0} / 试评 ${st.dry_run_done || 0}) · 均分 ${st.avg_score ?? "—"} (${st.scoring_rate_pct || 0}%)
                    </div>
                  </div>
                  <button type="button" class="btn btn-mini btn-primary" data-load-job="${esc(j.job_id)}">📊 载入此任务监控与核查</button>
                </div>
              `;
            })
            .join("");

          listEl.querySelectorAll("button[data-load-job]").forEach((b) => {
            b.addEventListener("click", () => {
              state.activeJobId = b.dataset.loadJob;
              switchTab("monitor");
            });
          });
        }
      }
    } catch (_) {}
  }

  async function generateTeachingReport() {
    const btn = $("btnGenerateReport");
    const box = $("reportOutputBox");
    const jobId = $("reportJobSelect")?.value || state.activeJobId || "";
    const provider = $("providerSelect")?.value || "gemini";
    const model = $("modelSelect")?.value || "";
    const apiKey = $("apiKeysInput")?.value.trim() || "";

    if (!apiKey && !jobId) {
      alert("请先在「创建任务」第 3 步填入您的 API Key");
      return;
    }

    try {
      btn.classList.add("loading");
      btn.disabled = true;
      box.textContent = "⏳ 正在汇总本题得分分布、各采分点命中率与典型作答样本，调用大模型生成教学分析报告...";

      const res = await api("/api/report/summary", {
        method: "POST",
        body: {
          job_id: jobId || null,
          provider,
          model,
          api_key: apiKey,
          queid: state.currentQuestion || $("questionSelect")?.value || "",
          quename: $("questionSelect")?.selectedOptions?.[0]?.textContent || "",
          max_score: parseFloat($("maxScoreInput")?.value || "10") || 10,
          prompt: state.activeJob?.prompt || $("promptPreview")?.value || ""
        }
      });

      box.textContent = res.report_markdown || "未生成内容";
    } catch (e) {
      box.textContent = "❌ 生成教学分析报告失败：" + e.message;
    } finally {
      btn.classList.remove("loading");
      btn.disabled = false;
    }
  }

  // ==================== 全屏滚轮缩放 Lightbox ====================
  function openLightbox(src) {
    if (!src) return;
    const lb = $("lightbox");
    const img = $("lbImg");
    state.lbScale = 1;
    img.src = src;
    img.style.transform = "scale(1)";
    lb.hidden = false;
  }

  function initLightboxEvents() {
    const lb = $("lightbox");
    const img = $("lbImg");
    if (!lb || !img) return;

    const applyScale = () => {
      img.style.transform = `scale(${state.lbScale})`;
    };

    $("lbZoomIn")?.addEventListener("click", () => {
      state.lbScale = Math.min(5, +(state.lbScale + 0.25).toFixed(2));
      applyScale();
    });
    $("lbZoomOut")?.addEventListener("click", () => {
      state.lbScale = Math.max(0.3, +(state.lbScale - 0.25).toFixed(2));
      applyScale();
    });
    $("lbReset")?.addEventListener("click", () => {
      state.lbScale = 1;
      applyScale();
    });
    $("lbClose")?.addEventListener("click", () => {
      lb.hidden = true;
    });
    $("lbStage")?.addEventListener("wheel", (e) => {
      e.preventDefault();
      const delta = e.deltaY < 0 ? 0.15 : -0.15;
      state.lbScale = Math.min(5, Math.max(0.3, +(state.lbScale + delta).toFixed(2)));
      applyScale();
    });
  }

  // ==================== 事件绑定汇总 ====================
  function bindWorkspaceEvents() {
    // Step 1
    $("subjectSelect")?.addEventListener("change", onSubjectOrModeChange);
    $("modeSelect")?.addEventListener("change", onSubjectOrModeChange);
    $("questionSelect")?.addEventListener("change", loadQuestionPreview);
    $("spliceSelect")?.addEventListener("change", loadQuestionPreview);
    $("btnReloadSubjects")?.addEventListener("click", onSubjectOrModeChange);
    $("btnRefreshPreview")?.addEventListener("click", loadQuestionPreview);

    $("btnConfirmStep1")?.addEventListener("click", () => {
      $("stepCard1")?.classList.remove("is-current");
      $("stepCard1")?.classList.add("is-done");
      $("step1StateBadge").textContent = "✅ 已确认题目";
      $("stepCard2")?.classList.add("is-current");
      $("stepCard2")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    // Step 2
    $("promptPreview")?.addEventListener("input", updateDetectedPointsHint);
    $("btnApplyTemplate")?.addEventListener("click", applyTemplateSlotsToPrompt);
    $("btnAiGenRubric")?.addEventListener("click", generateRubricWithAi);
    $("btnConfirmStep2")?.addEventListener("click", () => {
      if (!$("promptPreview")?.value.trim()) {
        alert("请先填写评分指令 (Prompt)");
        return;
      }
      $("stepCard2")?.classList.remove("is-current");
      $("stepCard2")?.classList.add("is-done");
      $("step2StateBadge").textContent = "✅ 已确认指令";
      $("stepCard3")?.classList.add("is-current");
      $("stepCard3")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    // Step 3 启动试评 / 正式评阅
    $("btnStartTrial")?.addEventListener("click", () => startGradingJob(true));
    $("btnStartFormal")?.addEventListener("click", () => startGradingJob(false));

    // Monitor 控制栏
    $("btnRefreshMonitor")?.addEventListener("click", refreshMonitorNow);
    $("btnJumpReport")?.addEventListener("click", () => switchTab("report"));
    $("btnPauseJob")?.addEventListener("click", async () => {
      if (!state.activeJobId) return;
      await api(`/api/job/${state.activeJobId}/pause`, { method: "POST" });
      refreshMonitorNow();
    });
    $("btnResumeJob")?.addEventListener("click", async () => {
      if (!state.activeJobId) return;
      await api(`/api/job/${state.activeJobId}/resume`, { method: "POST" });
      startMonitorPolling();
    });
    $("btnStopJob")?.addEventListener("click", async () => {
      if (!state.activeJobId) return;
      if (!confirm("确定要停止当前阅卷任务吗？")) return;
      await api(`/api/job/${state.activeJobId}/stop`, { method: "POST" });
      refreshMonitorNow();
    });

    // 试评审阅闭环：修改指令 或 转入正式连续写分
    $("btnTrialEditPrompt")?.addEventListener("click", () => {
      const details = $("livePromptDetails");
      if (details) {
        details.open = true;
        $("livePromptTextarea")?.focus();
        details.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
    $("btnPromoteFormal")?.addEventListener("click", async () => {
      if (!state.activeJobId) return;
      const formalMax = parseInt($("maxPapersInput")?.value || "0", 10) || 0;
      const btn = $("btnPromoteFormal");
      try {
        btn.classList.add("loading");
        btn.disabled = true;
        await api(`/api/job/${state.activeJobId}/promote-formal`, {
          method: "POST",
          body: {
            submit_existing_trial: true,
            max_papers: formalMax
          }
        });
        startMonitorPolling();
      } catch (e) {
        alert("转入正式评阅失败：" + e.message);
      } finally {
        btn.classList.remove("loading");
        btn.disabled = false;
      }
    });

    // 动态修改运行中 Prompt
    $("btnSaveLivePrompt")?.addEventListener("click", async () => {
      if (!state.activeJobId) return;
      const newPrompt = $("livePromptTextarea")?.value.trim() || "";
      if (!newPrompt) return;
      try {
        await api(`/api/job/${state.activeJobId}/update-prompt`, {
          method: "POST",
          body: { prompt: newPrompt }
        });
        if ($("promptPreview")) $("promptPreview").value = newPrompt;
        alert("✅ 新评分指令已保存并立即对后续试卷生效！");
      } catch (e) {
        alert("保存指令失败：" + e.message);
      }
    });

    // 监控页统计卡片点击筛选
    document.querySelectorAll("#tab-monitor .stat-card[data-filter]").forEach((card) => {
      card.addEventListener("click", () => {
        const f = card.dataset.filter || "all";
        if ($("monitorFilterSelect")) $("monitorFilterSelect").value = f;
        renderTaskCards(state.monitorTasks, $("monitorTaskCards"), "monitor");
      });
    });
    $("monitorFilterSelect")?.addEventListener("change", () => {
      renderTaskCards(state.monitorTasks, $("monitorTaskCards"), "monitor");
    });
    $("monitorSearchInput")?.addEventListener("input", () => {
      renderTaskCards(state.monitorTasks, $("monitorTaskCards"), "monitor");
    });

    // Tab 3: 核查与改分子视图切换
    $("btnSwitchRegradeLocal")?.addEventListener("click", () => {
      state.regradeMode = "local";
      $("btnSwitchRegradeLocal").classList.add("btn-primary");
      $("btnSwitchRegradeSource").classList.remove("btn-primary");
      $("regradeLocalPane").hidden = false;
      $("regradeSourcePane").hidden = true;
      loadLocalRegradeList();
    });
    $("btnSwitchRegradeSource")?.addEventListener("click", () => {
      state.regradeMode = "source";
      $("btnSwitchRegradeSource").classList.add("btn-primary");
      $("btnSwitchRegradeLocal").classList.remove("btn-primary");
      $("regradeLocalPane").hidden = true;
      $("regradeSourcePane").hidden = false;
      syncSourceRegradeQuestions();
    });
    $("regradeJobSelect")?.addEventListener("change", loadLocalRegradeList);
    $("regradeStatusSelect")?.addEventListener("change", () => {
      renderTaskCards(state.regradeLocalTasks, $("regradeLocalCards"), "regrade-local");
    });
    $("regradeLocalSearch")?.addEventListener("input", () => {
      renderTaskCards(state.regradeLocalTasks, $("regradeLocalCards"), "regrade-local");
    });
    $("btnRefreshLocalRegrade")?.addEventListener("click", loadLocalRegradeList);
    $("sourceRegradeSubSelect")?.addEventListener("change", syncSourceRegradeQuestions);
    $("btnFetchSourceReviews")?.addEventListener("click", fetchSourceReviewPapers);

    // Tab 4: 报告生成、复制与下载
    $("btnGenerateReport")?.addEventListener("click", generateTeachingReport);
    $("btnRefreshHistoryJobs")?.addEventListener("click", loadHistoryJobsAndReport);
    $("btnCopyReport")?.addEventListener("click", async () => {
      const txt = $("reportOutputBox")?.textContent || "";
      await navigator.clipboard.writeText(txt);
      alert("✅ 报告 Markdown 已复制到剪贴板");
    });
    $("btnDownloadReport")?.addEventListener("click", () => {
      const txt = $("reportOutputBox")?.textContent || "";
      const blob = new Blob([txt], { type: "text/markdown;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `mark-rdfz-阅卷教学报告-${new Date().toISOString().slice(0, 10)}.md`;
      a.click();
    });

    // 核查与修改分数弹窗事件 (#taskReviewModal)
    $("btnModalClose")?.addEventListener("click", () => {
      $("taskReviewModal").hidden = true;
    });
    $("modalBackdrop")?.addEventListener("click", () => {
      $("taskReviewModal").hidden = true;
    });
    $("btnModalPrev")?.addEventListener("click", () => {
      if (state.modalIndex > 0) openReviewModal(state.modalList, state.modalIndex - 1);
    });
    $("btnModalNext")?.addEventListener("click", () => {
      if (state.modalIndex < state.modalList.length - 1) openReviewModal(state.modalList, state.modalIndex + 1);
    });
    $("modalAnswerImg")?.addEventListener("click", () => {
      openLightbox($("modalAnswerImg").src);
    });
    $("btnModalZoom")?.addEventListener("click", () => {
      openLightbox($("modalAnswerImg").src);
    });
    $("btnModalWholePaper")?.addEventListener("click", viewModalWholePaper);
    $("btnCloseWholePaper")?.addEventListener("click", () => {
      $("modalWholePaperBox").hidden = true;
    });

    // 快捷赋分按钮
    $("btnModalFullScore")?.addEventListener("click", () => {
      $("modalScoreInput").value = $("modalScoreInput").max || 10;
    });
    $("btnModalZeroScore")?.addEventListener("click", () => {
      $("modalScoreInput").value = 0;
    });
    $("btnModalMinus1")?.addEventListener("click", () => {
      const cur = parseFloat($("modalScoreInput").value || "0") || 0;
      $("modalScoreInput").value = Math.max(0, cur - 1);
    });
    $("btnModalPlus1")?.addEventListener("click", () => {
      const cur = parseFloat($("modalScoreInput").value || "0") || 0;
      const max = parseFloat($("modalScoreInput").max || "10") || 10;
      $("modalScoreInput").value = Math.min(max, cur + 1);
    });

    $("btnModalSaveScore")?.addEventListener("click", saveModalRegradeScore);
    $("btnModalAiRegrade")?.addEventListener("click", runModalAiRegrade);

    // 键盘快捷键（ESC 关闭弹窗，左右方向键在核查弹窗内切换上一份/下一份）
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        if (!$("lightbox").hidden) {
          $("lightbox").hidden = true;
          return;
        }
        if (!$("taskReviewModal").hidden) {
          $("taskReviewModal").hidden = true;
        }
      } else if (!$("taskReviewModal").hidden && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
        if (e.key === "ArrowLeft" && state.modalIndex > 0) {
          openReviewModal(state.modalList, state.modalIndex - 1);
        } else if (e.key === "ArrowRight" && state.modalIndex < state.modalList.length - 1) {
          openReviewModal(state.modalList, state.modalIndex + 1);
        }
      }
    });
  }

  // ==================== 启动入口 ====================
  document.addEventListener("DOMContentLoaded", async () => {
    initThemeAndNav();
    initLoginEvents();
    bindWorkspaceEvents();
    initLightboxEvents();
    await loadModelsAndTemplates();
    await checkExistingSession();
  });
})();
