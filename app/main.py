import base64
import collections
from datetime import datetime, timezone
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.client.haidian_client import HaidianClient, detect_mime_type, format_score_str
from app.grader.ai_grader import (
    AIGrader,
    SUBJECT_TEMPLATES,
    extract_point_keys,
    render_template_prompt,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("rdfz_ops")

app = FastAPI(title="mark.rdfz.net · AI 智能阅卷系统", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory sessions & jobs
sessions: Dict[str, Dict[str, Any]] = {}
jobs: Dict[str, Dict[str, Any]] = {}
diagnostic_events = collections.deque(maxlen=300)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_diagnostic(action: str, username: str, target: str, status: str, details: Any = None):
    event = {
        "time": now_iso(),
        "action": action,
        "username": username or "anonymous",
        "target": target,
        "status": status,
        "details": details or {}
    }
    diagnostic_events.appendleft(event)
    logger.info(f"[{action.upper()}] user={username} target={target} status={status} details={details}")


def get_session(request: Request) -> tuple[Dict[str, Any], str]:
    sid = request.cookies.get("session_id")
    if not sid or sid not in sessions:
        sid = str(uuid.uuid4())
        sessions[sid] = {
            "client": None,
            "base_url": "",
            "username": "",
            "records": [],
            "current_task": None,
            "subjects": [],
            "questions": [],
            "current_subid": "",
            "current_mode": "normal",
            "active_job_id": "",
            "job_ids": [],
        }
    return sessions[sid], sid


# ==============================================================================
# Request Schemas
# ==============================================================================

def _normalize_mode(m: Optional[str]) -> str:
    if m and str(m).lower() in ("arb", "arbitration", "4"):
        return "arb"
    return "normal"


def _normalize_splice(s: Any) -> int:
    if isinstance(s, int):
        return s
    if str(s).lower() in ("horizontal", "1"):
        return 1
    if str(s).lower() in ("vertical", "0", ""):
        return 0
    try:
        return int(s)
    except Exception:
        return 0


class LoginRequest(BaseModel):
    base_url: str
    username: str
    password: str


class SelectSubjectRequest(BaseModel):
    subid: str
    mode: str = "normal"  # 'normal' | 'arb' | 'arbitration'


class PreviewQuestionRequest(BaseModel):
    subid: Optional[str] = None
    queid: str
    mode: Optional[str] = None
    splice: Any = 0
    refresh: bool = False


class RenderTemplateRequest(BaseModel):
    template_key: Optional[str] = None
    template_id: Optional[str] = None
    slots: Optional[Dict[str, str]] = None
    values: Optional[Dict[str, str]] = None
    full_score: Optional[float] = None
    max_score: Optional[float] = None


class GenerateRubricRequest(BaseModel):
    question: str = ""
    question_text: str = ""
    ref_answer: str = ""
    reference_answer: str = ""
    full_score: Optional[float] = None
    max_score: Optional[float] = None
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    api_key: str
    base_url: Optional[str] = None


class CreateJobRequest(BaseModel):
    subid: str = ""
    subname: str = ""
    mode: str = "normal"
    queid: str
    quename: str = ""
    full_score: Optional[float] = None
    max_score: Optional[float] = None
    markdic_list: Optional[List[str]] = None
    sub_questions: Optional[List[Dict[str, Any]]] = None
    rubric: str = ""
    prompt: str = ""
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    thinking: str = "medium"
    thinking_level: Optional[str] = None
    api_keys: str
    api_base_url: Optional[str] = None
    concurrency: int = 2
    dry_run: bool = True  # True = 试评 (Trial), False = 正式评阅 (Formal)
    trial_limit: Optional[int] = None
    formal_limit: Optional[int] = None
    max_papers: Optional[int] = None
    allow_trial_queue_advance: bool = True
    splice: Any = 0


class UpdateJobPromptRequest(BaseModel):
    rubric: str = ""
    prompt: str = ""


class RegradePaperRequest(BaseModel):
    job_id: Optional[str] = None
    task_id: Optional[str] = None
    secid: str = ""
    paper_id: str = ""
    subid: Optional[str] = None
    queid: str = ""
    mode: str = "normal"
    new_score: float
    smallscores: Optional[Dict[str, Any]] = None
    sub_scores: Optional[Dict[str, Any]] = None
    encrypt_code: Optional[str] = None
    reason: str = "教师人工复核改分"
    comment: Optional[str] = None


class SingleAIGradeRequest(BaseModel):
    job_id: Optional[str] = None
    task_id: Optional[str] = None
    paper_id: Optional[str] = None
    subid: Optional[str] = None
    queid: Optional[str] = None
    image_b64: str = ""
    rubric: str = ""
    prompt: str = ""
    full_score: Optional[float] = None
    max_score: Optional[float] = None
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    api_key: str = ""
    thinking: str = "medium"
    thinking_level: Optional[str] = None
    base_url: Optional[str] = None
    markdic_list: Optional[List[str]] = None
    sub_questions: Optional[List[Dict[str, Any]]] = None
    auto_submit: bool = False


class ReviewListRequest(BaseModel):
    subid: Optional[str] = None
    queid: str
    nowpage: int = 1
    fanwei: str = "全部"
    score_filter: Optional[str] = None
    mode: str = "normal"


class ReviewDetailRequest(BaseModel):
    subid: Optional[str] = None
    secid: str = ""
    paper_id: str = ""
    queid: Optional[str] = None
    mode: str = "normal"
    splice: Any = 0


class FullPaperRequest(BaseModel):
    subid: Optional[str] = None
    paper_id: Optional[str] = None
    encrypt_code: Optional[str] = None
    zimgpath: str = ""


class ProgressRequest(BaseModel):
    queid: str
    subid: Optional[str] = None


class AISummaryRequest(BaseModel):
    job_id: Optional[str] = None
    queid: Optional[str] = None
    que_name: str = "当前试题"
    quename: Optional[str] = None
    full_score: Optional[float] = None
    max_score: Optional[float] = None
    prompt: Optional[str] = None
    provider: str = "gemini"
    model: str = "gemini-3.8-flash"
    api_key: Optional[str] = None
    base_url: Optional[str] = None


# ==============================================================================
# Helper Functions for Job Events & Statistics
# ==============================================================================

def append_job_event(job: Dict[str, Any], level: str, message: str, task_id: str = "", data: Any = None):
    job["event_seq"] += 1
    ev = {
        "id": job["event_seq"],
        "ts": datetime.now().strftime("%H:%M:%S"),
        "level": level,  # 'ok' | 'warn' | 'error'
        "message": message,
        "task_id": task_id,
        "data": data or {}
    }
    job["events"].append(ev)
    if len(job["events"]) > 400:
        job["events"] = job["events"][-400:]


def compute_job_live_stats(job: Dict[str, Any], refresh_source: bool = False) -> Dict[str, Any]:
    tasks: List[Dict[str, Any]] = job["tasks"]
    full_score = float(job.get("full_score") or 6.0)

    scored_tasks = [t for t in tasks if t.get("status") in ("submitted", "completed", "trial_scored", "dry_run_done")]
    submitted_tasks = [t for t in tasks if t.get("status") in ("submitted", "completed") or t.get("submitted")]
    trial_tasks = [t for t in tasks if t.get("status") in ("trial_scored", "dry_run_done") and not t.get("submitted")]
    failed_tasks = [t for t in tasks if t.get("status") == "failed"]

    scores = [float(t.get("final_score", 0)) for t in scored_tasks if t.get("final_score") is not None]
    latencies = [int(t.get("ai_latency_ms", 0)) for t in scored_tasks if t.get("ai_latency_ms")]

    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    score_rate_pct = round((avg_score / full_score) * 100, 1) if (scores and full_score > 0) else 0.0
    avg_latency_ms = int(sum(latencies) / len(latencies)) if latencies else 0

    full_count = sum(1 for s in scores if s >= full_score and full_score > 0)
    zero_count = sum(1 for s in scores if s <= 0)
    collect_count = sum(1 for t in scored_tasks if "值得收藏" in (t.get("flags") or []))

    # Score distribution (count & percentage)
    dist_counts: Dict[str, int] = {}
    for s in scores:
        k = format_score_str(s)
        dist_counts[k] = dist_counts.get(k, 0) + 1

    score_distribution = []
    for k in sorted(dist_counts.keys(), key=lambda x: float(x) if x.replace(".", "", 1).isdigit() else 0):
        cnt = dist_counts[k]
        pct = round(cnt / len(scores) * 100, 1) if scores else 0.0
        score_distribution.append({"score": k, "count": cnt, "pct": pct})

    # Point hit rate (得分点命中率)
    point_hit_rate: Dict[str, Dict[str, Any]] = {}
    for t in scored_tasks:
        ps = t.get("point_scores") or {}
        pl = t.get("point_labels") or {}
        for pk, pval in ps.items():
            label = pl.get(pk, pk)
            entry = point_hit_rate.setdefault(label, {"key": pk, "label": label, "hit": 0, "total": 0, "sum_score": 0.0, "rate": 0.0})
            entry["total"] += 1
            if float(pval or 0) > 0:
                entry["hit"] += 1
            entry["sum_score"] += float(pval or 0)

    for label, entry in point_hit_rate.items():
        if entry["total"] > 0:
            entry["rate"] = round(entry["hit"] / entry["total"] * 100, 1)
            entry["avg_point"] = round(entry["sum_score"] / entry["total"], 2)

    # Refresh source progress if requested or stale (> 12s)
    client: Optional[HaidianClient] = job.get("client")
    now_ts = time.time()
    if client and (refresh_source or (now_ts - job.get("last_source_poll_ts", 0) > 12)):
        try:
            prog = client.get_monitor_progress(job["queid"], subid=job.get("subid"))
            if isinstance(prog, dict) and (prog.get("taskcount") is not None or prog.get("wanchengtotal") is not None):
                job["source_progress"] = prog
                job["last_source_poll_ts"] = now_ts
        except Exception:
            pass

    src_prog = job.get("source_progress") or {}
    src_total = int(src_prog.get("taskcount") or 0)
    src_done = int(src_prog.get("wanchengtotal") or src_prog.get("teacount") or 0)
    src_pct = float(src_prog.get("reat") or (round(src_done / src_total * 100, 1) if src_total > 0 else 0.0))

    # Job target & progress pct
    if job["dry_run"]:
        target_count = int(job.get("trial_limit") or 10)
    else:
        fl = int(job.get("formal_limit") or 0)
        target_count = fl if fl > 0 else (src_total if src_total > 0 else max(len(scored_tasks), 1))

    done_count = len(scored_tasks)
    job_progress_pct = round(min(100.0, (done_count / target_count) * 100), 1) if target_count > 0 else 0.0

    # Timing metrics
    start_ts = job.get("start_ts")
    end_ts = job.get("end_ts")
    elapsed_sec = 0
    if start_ts:
        ref_end = end_ts if (end_ts and job["status"] in ("done", "trial_done", "stopped", "paused")) else now_ts
        elapsed_sec = max(1, int(ref_end - start_ts))
    sec_per_sheet = round(elapsed_sec / done_count, 1) if (done_count > 0 and elapsed_sec > 0) else 0.0
    sheets_per_min = round((done_count / elapsed_sec) * 60, 1) if (done_count > 0 and elapsed_sec > 0) else 0.0

    full_rate_pct = round(full_count / done_count * 100, 1) if done_count > 0 else 0.0
    zero_rate_pct = round(zero_count / done_count * 100, 1) if done_count > 0 else 0.0
    point_hits_compat = {
        label: {
            "hit": e["hit"],
            "total": e["total"],
            "hit_rate_pct": e["rate"],
            "avg_score": e.get("avg_point", 0.0),
        }
        for label, e in point_hit_rate.items()
    }
    my_marked_val = int(src_prog.get("teacount") or len(submitted_tasks))
    src_avg_val = src_prog.get("avg") or avg_score

    return {
        "job_id": job["id"],
        "status": job["status"],  # 'created' | 'running' | 'trial_done' | 'paused' | 'done' | 'stopped' | 'failed'
        "dry_run": job["dry_run"],
        "subid": job["subid"],
        "subname": job.get("subname", job["subid"]),
        "mode": job["mode"],
        "queid": job["queid"],
        "quename": job["quename"],
        "full_score": full_score,
        "max_score": full_score,
        "prompt": job.get("rubric", ""),
        "provider": job["provider"],
        "model": job["model"],
        "thinking": job["thinking"],
        "thinking_level": str(job["thinking"]).upper(),
        "concurrency": job["concurrency"],
        "trial_limit": job["trial_limit"],
        "formal_limit": job["formal_limit"],
        "max_papers": target_count,
        "started_at": start_ts,
        "target_count": target_count,
        "done_count": done_count,
        "written_count": len(submitted_tasks),
        "trial_count": len(trial_tasks),
        "failed_count": len(failed_tasks),
        "full_count": full_count,
        "full_rate_pct": full_rate_pct,
        "zero_count": zero_count,
        "zero_rate_pct": zero_rate_pct,
        "collect_count": collect_count,
        "avg_score": avg_score,
        "score_rate_pct": score_rate_pct,
        "avg_latency_ms": avg_latency_ms,
        "job_progress_pct": job_progress_pct,
        "score_distribution": score_distribution,
        "point_hit_rate": point_hit_rate,
        "stats": {
            "graded": done_count,
            "submitted": len(submitted_tasks),
            "dry_run_done": len(trial_tasks),
            "failed": len(failed_tasks),
            "full_score_count": full_count,
            "full_score_pct": full_rate_pct,
            "zero_score_count": zero_count,
            "zero_score_pct": zero_rate_pct,
            "worth_saving_count": collect_count,
            "avg_score": avg_score,
            "scoring_rate_pct": score_rate_pct,
            "avg_latency_ms": avg_latency_ms,
            "speed_per_min": sheets_per_min,
            "elapsed_sec": elapsed_sec,
            "score_distribution": dist_counts,
            "point_hits": point_hits_compat,
        },
        "source_progress": {
            "taskcount": src_total,
            "wanchengtotal": src_done,
            "reat": src_pct,
            "teacount": my_marked_val,
            "teaavg": src_prog.get("teaavg") or avg_score,
            "avg": src_avg_val,
            "flag_mode": src_prog.get("flag_mode") or ("仲裁" if job["mode"] == "arb" else "正评"),
            "total_count": src_total,
            "marked_count": src_done,
            "progress_pct": src_pct,
            "my_marked_count": my_marked_val,
            "avg_score": src_avg_val,
        },
        "timing": {
            "start_time": job.get("start_time_str") or "—",
            "end_time": job.get("end_time_str") or "—",
            "elapsed_sec": elapsed_sec,
            "sec_per_sheet": sec_per_sheet,
            "sheets_per_min": sheets_per_min,
            "ai_ms_per_sheet": avg_latency_ms,
        },
        "last_error": job.get("last_error") or "",
    }


# ==============================================================================
# Background AI Grading Runner (Trial & Formal)
# ==============================================================================

def _execute_single_paper_grading(
    job: Dict[str, Any],
    sess: Dict[str, Any],
    raw_task: Dict[str, Any],
    submit_to_source: bool,
    is_trial_advance: bool = False,
    source_original_score: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    client: HaidianClient = job["client"]
    secid = str(raw_task.get("secid") or "")
    examid = str(raw_task.get("examid") or "")
    imgpath = str(raw_task.get("imgpath") or "")
    zimgpath = str(raw_task.get("zimgpath") or "")
    if not secid or not imgpath:
        return None

    # Update job question metadata if source returned fuller metadata
    if raw_task.get("fullmark"):
        try:
            fm = float(raw_task["fullmark"])
            if fm > 0:
                job["full_score"] = fm
        except Exception:
            pass
    if raw_task.get("markdic_list"):
        job["markdic_list"] = raw_task["markdic_list"]
    if raw_task.get("sub_questions"):
        job["sub_questions"] = raw_task["sub_questions"]
    if raw_task.get("quename"):
        job["quename"] = raw_task["quename"]

    # Update source progress from paper metadata if present
    if raw_task.get("taskcount") is not None or raw_task.get("teamarkcount") is not None:
        tc = int(raw_task.get("taskcount") or job["source_progress"].get("taskcount") or 0)
        tmc = int(raw_task.get("teamarkcount") or job["source_progress"].get("teacount") or 0)
        job["source_progress"]["taskcount"] = tc
        job["source_progress"]["teacount"] = tmc
        if tc > 0 and not job["source_progress"].get("wanchengtotal"):
            job["source_progress"]["wanchengtotal"] = tmc
            job["source_progress"]["reat"] = round(tmc / tc * 100, 1)

    # Download answer sheet image
    img_bytes, mime_type = client.get_image(imgpath, splice=job.get("splice", 0))
    if not img_bytes:
        append_job_event(job, "error", f"拉取答卷图片失败 (secid={secid}, path={imgpath})", task_id=secid)
        return None

    b64_img = base64.b64encode(img_bytes).decode("utf-8")
    data_uri = f"data:{mime_type};base64,{b64_img}"

    # Call AI Vision Grader (with 1x automatic retry on JSON parse failure, matching mark.bdfz.net v1.1.82)
    ai_res = None
    last_ai_err = None
    for attempt in range(2):
        if job["stop_requested"] or job["pause_requested"]:
            break
        try:
            ai_res = AIGrader.grade_image(
                image_bytes=img_bytes,
                rubric=job["rubric"],
                full_score=job["full_score"],
                provider=job["provider"],
                model=job["model"],
                api_key=job["api_keys"],
                thinking=job["thinking"],
                base_url=job.get("api_base_url"),
                markdic_list=job.get("markdic_list"),
                sub_questions=job.get("sub_questions"),
                mime_type=mime_type,
            )
            break
        except Exception as e:
            last_ai_err = e
            if attempt == 0:
                time.sleep(0.5)

    task_id = f"T{len(job['tasks']) + 1:03d}-{secid[-4:] if len(secid) >= 4 else secid}"

    if not ai_res:
        err_msg = str(last_ai_err or "AI 判分失败")
        failed_card = {
            "id": task_id,
            "task_id": task_id,
            "job_id": job["id"],
            "secid": secid,
            "paper_id": secid,
            "subid": job["subid"],
            "examid": examid,
            "queid": job["queid"],
            "quename": job["quename"],
            "mode": job["mode"],
            "status": "failed",
            "submitted": False,
            "worth_saving": False,
            "regraded": False,
            "final_score": None,
            "score": 0,
            "full_score": job["full_score"],
            "max_score": job["full_score"],
            "source_original_score": source_original_score,
            "student_answer": "",
            "student_answer_ocr": "",
            "overall_comment": "",
            "point_scores": {},
            "point_comments": {},
            "point_labels": {},
            "breakdown": [],
            "sub_scores": [],
            "flags": ["识别故障"],
            "ai_provider": job["provider"],
            "ai_model": job["model"],
            "ai_latency_ms": 0,
            "image_data_uri": data_uri,
            "image_base64": data_uri,
            "imgpath": imgpath,
            "zimgpath": zimgpath,
            "raw_task_meta": raw_task,
            "error": err_msg,
            "created_at": datetime.now().strftime("%H:%M:%S"),
        }
        job["tasks"].insert(0, failed_card)
        job["last_error"] = err_msg
        append_job_event(job, "error", f"AI 评阅失败 ({secid}): {err_msg}", task_id=task_id)
        return None

    score_val = float(ai_res["final_score"])
    next_raw_task = None
    submit_status = "trial_scored"
    submit_resp_raw = ""

    if submit_to_source:
        # Build composite sub_scores dict if smallnum > 1
        small_dict = {}
        for sq in ai_res.get("sub_scores") or []:
            small_dict[f"smallscore{sq['index']}"] = sq["score"]

        submit_params = {
            "Flag_Mode": raw_task.get("Flag_Mode", "1"),
            "Flag_Send": raw_task.get("flagsend", "4" if job["mode"] == "arb" else "1"),
            "Sec_ID": secid,
            "secid": secid,
            "Que_ID": job["queid"],
            "queid": job["queid"],
            "Quename": job["quename"],
            "quename": job["quename"],
            "Exam_ID": examid,
            "examid": examid,
            "markmodel": raw_task.get("markmodel", "4" if job["mode"] == "arb" else "1"),
            "subid": raw_task.get("subid", ""),
            "smallnum": str(raw_task.get("smallnum", "0")),
            "biaozhi": "1" if ai_res.get("is_excellence") else "0",
            "pizhu": (ai_res.get("overall_comment") or "")[:120],
            "score": format_score_str(score_val),
            "smallscores": small_dict,
        }
        sub_res = client.submit_score(submit_params, mode=job["mode"])
        submit_resp_raw = str(sub_res)[:300]
        if str(sub_res.get("codeid")) == "0001" and sub_res.get("secid"):
            submit_status = "submitted"
            next_raw_task = sub_res
        elif sub_res.get("status") != "error":
            submit_status = "submitted"
        else:
            submit_status = "failed"
            job["last_error"] = f"源站写分异常: {sub_res.get('message', '')}"

    flags = list(ai_res.get("flags") or [])
    if is_trial_advance and submit_status == "submitted":
        flags.insert(0, "试评已入库(可改分)")
    elif not submit_to_source:
        flags.insert(0, "试评仅预览(未写分)")

    card = {
        "id": task_id,
        "task_id": task_id,
        "job_id": job["id"],
        "secid": secid,
        "paper_id": secid,
        "subid": job["subid"],
        "examid": examid,
        "queid": job["queid"],
        "quename": job["quename"],
        "mode": job["mode"],
        "status": "dry_run_done" if submit_status == "trial_scored" else ("completed" if submit_status == "submitted" else submit_status),
        "raw_status": submit_status,
        "submitted": submit_status == "submitted",
        "worth_saving": "值得收藏" in flags,
        "regraded": "人工已改分" in flags,
        "final_score": score_val,
        "score": score_val,
        "score_str": format_score_str(score_val),
        "full_score": job["full_score"],
        "max_score": job["full_score"],
        "source_original_score": source_original_score,
        "student_answer": ai_res.get("student_answer", ""),
        "student_answer_ocr": ai_res.get("student_answer", ""),
        "overall_comment": ai_res.get("overall_comment", ""),
        "point_scores": ai_res.get("point_scores", {}),
        "point_comments": ai_res.get("point_comments", {}),
        "point_labels": ai_res.get("point_labels", {}),
        "breakdown": ai_res.get("breakdown", []),
        "sub_scores": ai_res.get("sub_scores", []),
        "flags": flags,
        "ai_provider": job["provider"],
        "ai_model": job["model"],
        "ai_latency_ms": ai_res.get("latency_ms", 0),
        "image_data_uri": data_uri,
        "image_base64": data_uri,
        "imgpath": imgpath,
        "zimgpath": zimgpath,
        "raw_task_meta": raw_task,
        "submit_resp_raw": submit_resp_raw,
        "error": "",
        "created_at": datetime.now().strftime("%H:%M:%S"),
    }

    job["tasks"].insert(0, card)
    # Also sync to session records for unified history & report
    sess["records"].insert(0, {
        "task_id": task_id,
        "secid": secid,
        "examid": examid,
        "queid": job["queid"],
        "quename": job["quename"],
        "mode": job["mode"],
        "score": score_val,
        "full_score": job["full_score"],
        "ocr_text": card["student_answer"],
        "comment": card["overall_comment"],
        "breakdown": card["breakdown"],
        "sub_scores": card["sub_scores"],
        "flags": card["flags"],
        "provider": job["provider"],
        "model": job["model"],
        "latency_ms": card["ai_latency_ms"],
        "image_data_uri": data_uri,
        "zimgpath": zimgpath,
        "status": submit_status,
        "time": card["created_at"],
    })

    mode_tag = "试评" if job["dry_run"] else "正评写分"
    append_job_event(
        job,
        "ok",
        f"[{mode_tag}] 试卷 {secid} 判分完成: {format_score_str(score_val)}/{job['full_score']:g}分 ({card['ai_latency_ms']}ms)",
        task_id=task_id,
        data={"score": score_val, "ocr": card["student_answer"][:60]}
    )
    return next_raw_task


def _job_worker_loop(job_id: str, sess: Dict[str, Any]):
    job = jobs.get(job_id)
    if not job:
        return
    client: HaidianClient = job["client"]
    job["status"] = "running"
    if not job.get("start_ts"):
        job["start_ts"] = time.time()
        job["start_time_str"] = datetime.now().strftime("%H:%M:%S")
    job["end_ts"] = None
    job["end_time_str"] = "运行中..."

    is_trial = bool(job["dry_run"])
    target_limit = int(job["trial_limit"] or 10) if is_trial else int(job["formal_limit"] or 0)
    append_job_event(
        job,
        "ok",
        f"启动 {'🧪 AI 试评任务' if is_trial else '🚀 AI 正式评阅任务'} · 题号={job['quename']} · 模型={job['provider']}/{job['model']}"
    )

    try:
        if is_trial:
            # Trial Strategy:
            # 1. First gather already-graded review papers from source (if any) so we can run 100% non-destructive trial comparison
            review_candidates: List[Dict[str, Any]] = []
            if not job.get("allow_trial_queue_advance", True):
                try:
                    rev_res = client.get_review_list(job["queid"], nowpage=1, mode=job["mode"])
                    review_candidates = rev_res.get("items") or []
                except Exception:
                    review_candidates = []

            count_done = len([t for t in job["tasks"] if t.get("status") in ("submitted", "completed", "trial_scored", "dry_run_done")])
            next_chained_task = sess.get("current_task_raw")

            while count_done < target_limit and not job["stop_requested"] and not job["pause_requested"]:
                # Case A: If user chose pure read-only trial and we have review papers
                if not job.get("allow_trial_queue_advance", True) and review_candidates:
                    cand = review_candidates.pop(0)
                    r_detail = client.get_review_paper_info(cand["secid"], mode=job["mode"])
                    if str(r_detail.get("codeid")) == "0001" and r_detail.get("imgpath"):
                        _execute_single_paper_grading(
                            job,
                            sess,
                            r_detail,
                            submit_to_source=False,
                            source_original_score=str(cand.get("score", ""))
                        )
                        count_done += 1
                        continue

                # Case B: Claim from live queue
                raw_task = next_chained_task
                next_chained_task = None
                if not raw_task or str(raw_task.get("queid")) != str(job["queid"]):
                    raw_task = client.claim_task(job["queid"], mode=job["mode"])

                if str(raw_task.get("codeid")) != "0001" or not raw_task.get("secid"):
                    # Live queue is empty! Fallback to review list papers for trial if available
                    try:
                        rev_res = client.get_review_list(job["queid"], nowpage=1, mode=job["mode"])
                        already_secids = {t["secid"] for t in job["tasks"]}
                        avail_revs = [x for x in (rev_res.get("items") or []) if x.get("secid") not in already_secids]
                    except Exception:
                        avail_revs = []

                    if avail_revs:
                        cand = avail_revs[0]
                        r_detail = client.get_review_paper_info(cand["secid"], mode=job["mode"])
                        if str(r_detail.get("codeid")) == "0001" and r_detail.get("imgpath"):
                            _execute_single_paper_grading(
                                job,
                                sess,
                                r_detail,
                                submit_to_source=False,
                                source_original_score=str(cand.get("score", ""))
                            )
                            count_done += 1
                            continue

                    msg = raw_task.get("message") or "当前题号已无更多待评试卷"
                    append_job_event(job, "warn", f"源站提示: {msg}")
                    break

                # If trial_limit == 1 or this is the last paper of trial, we don't even have to advance the queue unless allow_trial_queue_advance is True
                should_advance = bool(job.get("allow_trial_queue_advance", True)) and (target_limit > 1)
                next_chained_task = _execute_single_paper_grading(
                    job,
                    sess,
                    raw_task,
                    submit_to_source=should_advance,
                    is_trial_advance=should_advance
                )
                sess["current_task_raw"] = next_chained_task
                count_done = len([t for t in job["tasks"] if t.get("status") in ("submitted", "completed", "trial_scored", "dry_run_done")])
                if not should_advance:
                    # Without submitting to Haidian/Yuemanfen, get_paperinfo returns the same secid, so stop after 1 or switch to review list
                    try:
                        rev_res = client.get_review_list(job["queid"], nowpage=1, mode=job["mode"])
                        already_secids = {t["secid"] for t in job["tasks"]}
                        review_candidates = [x for x in (rev_res.get("items") or []) if x.get("secid") not in already_secids]
                    except Exception:
                        review_candidates = []
                    if not review_candidates:
                        break

                time.sleep(0.15)

        else:
            # Formal Grading Loop (Continuous auto-claim -> AI Vision Grade -> Submit Score -> Chain Next)
            count_done = len([t for t in job["tasks"] if t.get("status") in ("submitted", "completed") or t.get("submitted")])
            next_chained_task = sess.get("current_task_raw")

            while not job["stop_requested"] and not job["pause_requested"]:
                if target_limit > 0 and count_done >= target_limit:
                    append_job_event(job, "ok", f"已达到设定正式评阅上限 ({target_limit} 份)，任务完成。")
                    break

                raw_task = next_chained_task
                next_chained_task = None
                if not raw_task or str(raw_task.get("queid")) != str(job["queid"]):
                    raw_task = client.claim_task(job["queid"], mode=job["mode"])

                if str(raw_task.get("codeid")) != "0001" or not raw_task.get("secid"):
                    msg = raw_task.get("message") or "源站当前题号已全部评阅完毕"
                    append_job_event(job, "ok", f"源站队列已完成: {msg}")
                    break

                next_chained_task = _execute_single_paper_grading(
                    job,
                    sess,
                    raw_task,
                    submit_to_source=True,
                    is_trial_advance=False
                )
                sess["current_task_raw"] = next_chained_task
                count_done = len([t for t in job["tasks"] if t.get("status") in ("submitted", "completed") or t.get("submitted")])
                time.sleep(0.15)

        job["end_ts"] = time.time()
        job["end_time_str"] = datetime.now().strftime("%H:%M:%S")

        if job["stop_requested"]:
            job["status"] = "stopped"
            append_job_event(job, "warn", "任务已由教师手动停止。")
        elif job["pause_requested"]:
            job["status"] = "paused"
            append_job_event(job, "warn", "任务已暂停，可随时继续或核查试卷。")
        elif is_trial:
            job["status"] = "trial_completed"
            append_job_event(job, "ok", f"🧪 试评完成！共完成 {len(job['tasks'])} 份试评样本，请审阅下方批阅卡片后决定修改指令或开始正式评阅。")
        else:
            job["status"] = "completed"
            append_job_event(job, "ok", f"🎉 正式评阅任务已完成！累计成功评阅 {len(job['tasks'])} 份答卷。")

    except Exception as e:
        logger.error(f"Job runner exception ({job_id}): {e}", exc_info=True)
        job["status"] = "error"
        job["last_error"] = str(e)
        job["end_ts"] = time.time()
        job["end_time_str"] = datetime.now().strftime("%H:%M:%S")
        append_job_event(job, "error", f"任务运行异常中断: {str(e)}")
    finally:
        job["runner_active"] = False
        compute_job_live_stats(job, refresh_source=True)


# ==============================================================================
# API Routes
# ==============================================================================

@app.get("/healthz")
def api_healthz():
    return {"status": "ok", "version": "3.0.0", "service": "mark.rdfz.net"}


@app.get("/api/models")
def api_get_models():
    """Return latest generation & previous 3 generations of vision-capable models."""
    catalog = AIGrader.get_supported_models()
    return {"providers": catalog, **catalog}


@app.get("/api/templates")
def api_get_templates():
    """Return subject grading prompt templates (mark.bdfz.net style)."""
    raw_list = AIGrader.get_templates()
    enriched = []
    for item in raw_list:
        enriched.append({
            "id": item.get("key"),
            **item,
        })
    return {"templates": enriched}


@app.post("/api/templates/render")
def api_render_template(req: RenderTemplateRequest):
    tkey = req.template_key or req.template_id or "generic"
    slot_vals = req.slots if req.slots is not None else (req.values or {})
    fscore = float(req.full_score or req.max_score or 10.0)
    prompt = render_template_prompt(tkey, slot_vals, full_score=fscore)
    return {"prompt": prompt}


@app.post("/api/ai/generate-rubric")
def api_generate_rubric(req: GenerateRubricRequest):
    try:
        q_text = req.question or req.question_text or ""
        a_text = req.ref_answer or req.reference_answer or ""
        fscore = float(req.full_score or req.max_score or 10.0)
        rubric_text = AIGrader.generate_rubric_with_ai(
            question=q_text,
            ref_answer=a_text,
            full_score=fscore,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
            base_url=req.base_url,
        )
        return {"success": True, "rubric": rubric_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/login")
def api_login(req: LoginRequest, response: Response, request: Request):
    sess, sid = get_session(request)
    client = HaidianClient(req.base_url)
    ok, msg = client.login(req.username, req.password)
    if not ok:
        record_diagnostic("login", req.username, req.base_url, "failed", {"reason": msg})
        raise HTTPException(status_code=400, detail=msg)

    subjects: List[Dict[str, Any]] = []
    questions: List[Dict[str, Any]] = []
    active_queid = ""
    current_subid = ""
    current_mode = "normal"

    try:
        sub_res = client.get_subjects()
        subjects = sub_res.get("subjects", [])
        if subjects:
            first_sub = subjects[0]
            if first_sub.get("normal_subid"):
                current_subid = first_sub["normal_subid"]
                current_mode = "normal"
            elif first_sub.get("arb_subid"):
                current_subid = first_sub["arb_subid"]
                current_mode = "arb"
            else:
                current_subid = first_sub.get("subid", "")

            if current_subid:
                paper_res = client.load_subject_paper(current_subid, mode=current_mode)
                questions = paper_res.get("questions", [])
                active_queid = paper_res.get("active_queid", "")
    except Exception as e:
        logger.warning(f"Post-login auto-discovery warning: {e}")

    record_diagnostic("login", req.username, client.base_url, "success", {
        "protocol": msg,
        "subjects_count": len(subjects),
        "questions_count": len(questions)
    })

    sess["client"] = client
    sess["base_url"] = client.base_url
    sess["username"] = req.username
    sess["records"] = []
    sess["current_task"] = None
    sess["current_task_raw"] = None
    sess["subjects"] = subjects
    sess["questions"] = questions
    sess["current_subid"] = current_subid
    sess["current_mode"] = current_mode

    response.set_cookie(
        key="session_id",
        value=sid,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7
    )
    return {
        "success": True,
        "message": msg,
        "base_url": client.base_url,
        "username": req.username,
        "subjects": subjects,
        "current_subid": current_subid,
        "current_mode": current_mode,
        "questions": questions,
        "active_queid": active_queid
    }


@app.get("/api/session")
def api_get_session(request: Request):
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    is_logged_in = client is not None and client.is_logged_in
    active_job_id = sess.get("active_job_id") or ""
    return {
        "logged_in": is_logged_in,
        "base_url": sess.get("base_url", ""),
        "username": sess.get("username", ""),
        "records_count": len(sess.get("records", [])),
        "subjects": sess.get("subjects", []),
        "questions": sess.get("questions", []),
        "current_subid": sess.get("current_subid", ""),
        "current_mode": sess.get("current_mode", "normal"),
        "active_job_id": active_job_id if active_job_id in jobs else "",
    }


@app.post("/api/logout")
def api_logout(request: Request, response: Response):
    sess, sid = get_session(request)
    active_jid = sess.get("active_job_id")
    if active_jid and active_jid in jobs:
        jobs[active_jid]["stop_requested"] = True
    if sid in sessions:
        del sessions[sid]
    response.delete_cookie("session_id")
    return {"success": True}


@app.post("/api/task/select-subject")
def api_select_subject(req: SelectSubjectRequest, request: Request):
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    if not client or not client.is_logged_in:
        raise HTTPException(status_code=401, detail="请先登录阅卷系统")

    norm_mode = _normalize_mode(req.mode)
    res = client.load_subject_paper(req.subid, mode=norm_mode)
    sess["current_subid"] = req.subid
    sess["current_mode"] = norm_mode
    if res.get("questions"):
        sess["questions"] = res["questions"]
    return res


@app.post("/api/task/preview")
def api_preview_question(req: PreviewQuestionRequest, request: Request):
    """
    Step 1 of mark.bdfz.net workflow:
    When teacher selects a question, fetch question metadata (fullmark, markdic, sub_questions),
    source real-time progress, and a real student answer sheet image for visual confirmation.
    """
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    if not client or not client.is_logged_in:
        raise HTTPException(status_code=401, detail="请先登录阅卷系统")

    use_mode = _normalize_mode(req.mode or sess.get("current_mode", "normal"))
    sess["current_mode"] = use_mode
    if req.subid:
        sess["current_subid"] = req.subid
    use_splice = _normalize_splice(req.splice)

    # 1. Try claiming current active paper from queue
    task_res = client.claim_task(req.queid, mode=use_mode)
    preview_source = "待评队列实卷"

    # 2. If queue has no ungraded paper or user clicked refresh to see another sample, check review list
    if (str(task_res.get("codeid")) != "0001" or not task_res.get("imgpath")) or req.refresh:
        try:
            rev_res = client.get_review_list(req.queid, nowpage=1, mode=use_mode)
            rev_items = rev_res.get("items") or []
            if rev_items:
                idx = int(time.time()) % len(rev_items) if req.refresh else 0
                chosen = rev_items[idx]
                rev_detail = client.get_review_paper_info(chosen["secid"], mode=use_mode)
                if str(rev_detail.get("codeid")) == "0001" and rev_detail.get("imgpath"):
                    task_res = rev_detail
                    preview_source = f"源站已评抽样卷 (原分: {chosen.get('score', '-')}分)"
        except Exception:
            pass

    image_b64 = None
    mime_type = "image/jpeg"
    imgpath = task_res.get("imgpath")
    if imgpath:
        img_bytes, mime_type = client.get_image(imgpath, splice=use_splice)
        if img_bytes:
            image_b64 = base64.b64encode(img_bytes).decode("utf-8")

    # Save claimed task in session if it came from live queue so Trial/Formal can reuse it immediately
    if preview_source == "待评队列实卷" and str(task_res.get("codeid")) == "0001":
        sess["current_task_raw"] = task_res

    # Fetch source real-time progress for this question
    source_progress = {}
    try:
        source_progress = client.get_monitor_progress(req.queid, subid=task_res.get("subid") or req.subid)
    except Exception:
        pass

    fullmark_val = float(task_res.get("fullmark") or 10.0)
    markdic = task_res.get("markdic_list") or []
    step_val = 1.0
    if len(markdic) >= 2:
        try:
            step_val = round(abs(float(markdic[1]) - float(markdic[0])), 2) or 1.0
        except Exception:
            step_val = 1.0
    sub_qs = task_res.get("sub_questions") or []

    src_total = int(source_progress.get("taskcount") or task_res.get("taskcount") or 0)
    src_done = int(source_progress.get("wanchengtotal") or source_progress.get("teacount") or task_res.get("teamarkcount") or 0)
    src_my = int(source_progress.get("teacount") or task_res.get("teamarkcount") or 0)
    src_pct = float(source_progress.get("reat") or (round(src_done / src_total * 100, 1) if src_total > 0 else 0.0))
    src_avg = source_progress.get("avg") or source_progress.get("teaavg")

    data_uri = f"data:{mime_type};base64,{image_b64}" if image_b64 else None
    img_count = len([p for p in str(imgpath or "").split(";") if p.strip()]) or 1

    return {
        "status": "ok" if image_b64 else "no_image",
        "preview_source": preview_source,
        "metadata": task_res,
        "image_b64": image_b64,
        "mime_type": mime_type,
        "source_progress": source_progress,
        "question": {
            "queid": req.queid,
            "quename": task_res.get("quename") or f"第 {req.queid} 题",
            "max_score": fullmark_val,
            "step": step_val,
            "is_composite": len(sub_qs) > 0,
            "sub_questions": sub_qs,
            "markdic_list": markdic,
        },
        "progress": {
            "total_count": src_total,
            "marked_count": src_done,
            "my_marked_count": src_my,
            "progress_pct": src_pct,
            "avg_score": src_avg,
        },
        "paper": {
            "paper_id": task_res.get("secid") or "",
            "image_base64": data_uri,
            "image_count": img_count,
            "zimgpath": task_res.get("zimgpath") or "",
            "preview_source": preview_source,
        } if data_uri else None,
        "paper_message": task_res.get("message") or ("已加载预览答卷" if data_uri else "当前队列暂无未评答卷"),
    }


# ==============================================================================
# Job Management Endpoints (Trial & Formal AI Grading)
# ==============================================================================

@app.post("/api/job/create")
def api_create_job(req: CreateJobRequest, request: Request):
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    if not client or not client.is_logged_in:
        raise HTTPException(status_code=401, detail="请先登录阅卷系统")

    keys = AIGrader.parse_api_keys(req.api_keys)
    if not keys:
        raise HTTPException(status_code=400, detail="请填写至少一个有效的个人 API Key")

    rubric_text = (req.rubric or req.prompt or "").strip()
    if not rubric_text:
        raise HTTPException(status_code=400, detail="请填写评分指令 (Prompt)")

    # Stop any currently running job in this session
    old_jid = sess.get("active_job_id")
    if old_jid and old_jid in jobs and jobs[old_jid].get("runner_active"):
        jobs[old_jid]["stop_requested"] = True
        time.sleep(0.2)

    norm_mode = _normalize_mode(req.mode or sess.get("current_mode", "normal"))
    fscore = float(req.full_score or req.max_score or 10.0)
    think_val = str(req.thinking_level or req.thinking or "LOW").lower()
    t_limit = int(req.trial_limit if req.trial_limit is not None else (req.max_papers if req.dry_run and req.max_papers else 10))
    f_limit = int(req.formal_limit if req.formal_limit is not None else (req.max_papers if not req.dry_run and req.max_papers is not None else 0))

    job_id = f"job-{datetime.now().strftime('%m%d-%H%M%S')}-{str(uuid.uuid4())[:4]}"
    job = {
        "id": job_id,
        "owner": sess.get("username", ""),
        "base_url": sess.get("base_url", ""),
        "client": client,
        "subid": req.subid or sess.get("current_subid", ""),
        "subname": req.subname or req.subid or sess.get("current_subid", ""),
        "mode": norm_mode,
        "queid": str(req.queid),
        "quename": req.quename or f"第{req.queid}题",
        "full_score": fscore,
        "markdic_list": req.markdic_list or [],
        "sub_questions": req.sub_questions or [],
        "rubric": rubric_text,
        "provider": req.provider,
        "model": req.model,
        "thinking": think_val,
        "api_keys": req.api_keys,
        "api_base_url": req.api_base_url,
        "concurrency": max(1, min(10, int(req.concurrency or 2))),
        "dry_run": bool(req.dry_run),
        "trial_limit": max(1, t_limit),
        "formal_limit": max(0, f_limit),
        "allow_trial_queue_advance": bool(req.allow_trial_queue_advance),
        "splice": _normalize_splice(req.splice),
        "status": "created",
        "tasks": [],
        "events": [],
        "event_seq": 0,
        "source_progress": {},
        "last_source_poll_ts": 0,
        "start_ts": None,
        "end_ts": None,
        "start_time_str": "—",
        "end_time_str": "—",
        "last_error": "",
        "stop_requested": False,
        "pause_requested": False,
        "runner_active": True,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    jobs[job_id] = job
    sess["active_job_id"] = job_id
    if job_id not in sess["job_ids"]:
        sess["job_ids"].insert(0, job_id)

    record_diagnostic("job_create", sess.get("username", ""), sess.get("base_url", ""), "started", {
        "job_id": job_id,
        "queid": req.queid,
        "dry_run": req.dry_run,
        "provider": req.provider,
        "model": req.model,
    })

    t = threading.Thread(target=_job_worker_loop, args=(job_id, sess), daemon=True)
    t.start()

    live_data = compute_job_live_stats(job, refresh_source=False)
    return {
        "success": True,
        "job_id": job_id,
        "live": live_data,
        "job": live_data,
    }


@app.get("/api/job/{job_id}/live")
def api_job_live(job_id: str, refresh_source: bool = False):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到该阅卷任务")
    return compute_job_live_stats(job, refresh_source=refresh_source)


@app.get("/api/job/{job_id}/tasks")
def api_job_tasks(job_id: str, filter_type: str = "all", limit: int = 500):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到该阅卷任务")
    all_tasks: List[Dict[str, Any]] = job["tasks"]
    full_score = float(job.get("full_score") or 6.0)

    if filter_type in ("submitted", "completed"):
        filtered = [t for t in all_tasks if t.get("status") in ("submitted", "completed") or t.get("submitted")]
    elif filter_type in ("trial", "dry_run_done"):
        filtered = [t for t in all_tasks if t.get("status") in ("trial_scored", "dry_run_done") or "试评" in "".join(t.get("flags") or [])]
    elif filter_type in ("full", "full_score"):
        filtered = [t for t in all_tasks if t.get("final_score") is not None and float(t["final_score"]) >= full_score]
    elif filter_type in ("zero", "zero_score"):
        filtered = [t for t in all_tasks if t.get("final_score") is not None and float(t["final_score"]) <= 0]
    elif filter_type in ("collectible", "worth_saving"):
        filtered = [t for t in all_tasks if "值得收藏" in (t.get("flags") or []) or t.get("worth_saving")]
    elif filter_type == "failed":
        filtered = [t for t in all_tasks if t.get("status") == "failed"]
    else:
        filtered = all_tasks

    return {"tasks": filtered[:limit], "total": len(all_tasks), "filtered_count": len(filtered)}


@app.get("/api/job/{job_id}/events")
def api_job_events(job_id: str, since: int = 0):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到该阅卷任务")
    evs = [e for e in job["events"] if e["id"] > since]
    return {"events": evs}


@app.post("/api/job/{job_id}/pause")
def api_job_pause(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到该阅卷任务")
    job["pause_requested"] = True
    if not job.get("runner_active"):
        job["status"] = "paused"
    append_job_event(job, "warn", "正在暂停任务...")
    return {"success": True, "live": compute_job_live_stats(job)}


@app.post("/api/job/{job_id}/resume")
def api_job_resume(job_id: str, request: Request):
    sess, _ = get_session(request)
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到该阅卷任务")
    if job.get("runner_active"):
        return {"success": True, "live": compute_job_live_stats(job)}

    job["pause_requested"] = False
    job["stop_requested"] = False
    job["runner_active"] = True
    t = threading.Thread(target=_job_worker_loop, args=(job_id, sess), daemon=True)
    t.start()
    return {"success": True, "live": compute_job_live_stats(job)}


@app.post("/api/job/{job_id}/stop")
def api_job_stop(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到该阅卷任务")
    job["stop_requested"] = True
    if not job.get("runner_active"):
        job["status"] = "stopped"
    return {"success": True, "live": compute_job_live_stats(job)}


@app.post("/api/job/{job_id}/promote-formal")
def api_job_promote_formal(job_id: str, request: Request):
    """
    After teacher reviews Trial (试评) results and confirms satisfaction,
    promote the job to Formal (正式评阅) mode and continue grading & writing scores to source!
    """
    sess, _ = get_session(request)
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到该阅卷任务")

    # Wait briefly if runner is finishing
    if job.get("runner_active"):
        job["pause_requested"] = True
        time.sleep(0.3)

    # First, if there is any un-submitted trial task from the live queue, submit its score
    client: HaidianClient = job["client"]
    for t in reversed(job["tasks"]):
        if t.get("status") in ("trial_scored", "dry_run_done") and not t.get("submitted") and not t.get("source_original_score"):
            raw_task = t.get("raw_task_meta") or {}
            secid = t["secid"]
            small_dict = {f"smallscore{sq['index']}": sq["score"] for sq in (t.get("sub_scores") or []) if isinstance(sq, dict) and "index" in sq}
            submit_params = {
                "Flag_Mode": raw_task.get("Flag_Mode", "1"),
                "Flag_Send": raw_task.get("flagsend", "4" if job["mode"] == "arb" else "1"),
                "Sec_ID": secid,
                "secid": secid,
                "Que_ID": job["queid"],
                "queid": job["queid"],
                "Quename": job["quename"],
                "quename": job["quename"],
                "Exam_ID": t.get("examid", ""),
                "examid": t.get("examid", ""),
                "markmodel": raw_task.get("markmodel", "4" if job["mode"] == "arb" else "1"),
                "subid": raw_task.get("subid", ""),
                "smallnum": str(raw_task.get("smallnum", "0")),
                "biaozhi": "0",
                "pizhu": (t.get("overall_comment") or "")[:120],
                "score": format_score_str(t["final_score"]),
                "smallscores": small_dict,
            }
            try:
                sub_res = client.submit_score(submit_params, mode=job["mode"])
                if str(sub_res.get("codeid")) == "0001" or sub_res.get("status") != "error":
                    t["status"] = "completed"
                    t["raw_status"] = "submitted"
                    t["submitted"] = True
                    t["flags"] = [f for f in t.get("flags", []) if "未写分" not in f]
                    t["flags"].insert(0, "试评转正已写分")
                    if sub_res.get("secid"):
                        sess["current_task_raw"] = sub_res
            except Exception as e:
                logger.warning(f"Promote trial paper {secid} warning: {e}")

    job["dry_run"] = False
    job["pause_requested"] = False
    job["stop_requested"] = False
    job["runner_active"] = True
    append_job_event(job, "ok", "✅ 试评审阅通过，已切换为【正式 AI 连续评阅模式】，开始自动判卷并写回源站！")

    t_thread = threading.Thread(target=_job_worker_loop, args=(job_id, sess), daemon=True)
    t_thread.start()

    return {"success": True, "live": compute_job_live_stats(job)}


@app.post("/api/job/{job_id}/update-prompt")
def api_job_update_prompt(job_id: str, req: UpdateJobPromptRequest):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到该阅卷任务")
    new_rubric = (req.rubric or req.prompt or "").strip()
    if not new_rubric:
        raise HTTPException(status_code=400, detail="评分指令不能为空")
    job["rubric"] = new_rubric
    append_job_event(job, "ok", "✏️ 已动态更新评分 Prompt 指令，后续试卷立即按新标准判分。")
    return {"success": True, "message": "评分指令已更新，立即生效"}


@app.get("/api/jobs/history")
def api_jobs_history(request: Request):
    sess, _ = get_session(request)
    out = []
    for jid in sess.get("job_ids", []):
        if jid in jobs:
            j = jobs[jid]
            live = compute_job_live_stats(j, refresh_source=False)
            out.append({
                "job_id": jid,
                "created_at": j.get("created_at", ""),
                "subid": j.get("subid", ""),
                "subname": j.get("subname", j.get("subid", "")),
                "quename": j.get("quename", ""),
                "queid": j.get("queid", ""),
                "mode": j.get("mode", "normal"),
                "dry_run": j.get("dry_run", False),
                "provider": j.get("provider", ""),
                "model": j.get("model", ""),
                "status": live["status"],
                "done_count": live["done_count"],
                "written_count": live["written_count"],
                "avg_score": live["avg_score"],
                "full_score": live["full_score"],
                "stats": live["stats"],
            })
    return {"jobs": out}


# ==============================================================================
# Inspect Any Paper & Modify Score (Regrade / Source Review)
# ==============================================================================

@app.post("/api/paper/regrade")
def api_regrade_paper(req: RegradePaperRequest, request: Request):
    """
    Modify the score of ANY graded paper (either from local AI job or from source review list).
    First loads review context via get_review_paper_info(secid) on the source server,
    then submits the updated score via submit_score(markpaper/Arbmarkpaper), and updates local records.
    """
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    if not client or not client.is_logged_in:
        raise HTTPException(status_code=401, detail="请先登录阅卷系统")

    secid = str(req.secid or req.paper_id).strip()
    if not secid:
        raise HTTPException(status_code=400, detail="缺少试卷流水号 (secid)")

    norm_mode = _normalize_mode(req.mode)
    # Step 1: Load review paper info on source server so session context is bound to this secid
    rev_info = client.get_review_paper_info(secid, mode=norm_mode)
    old_source_score = rev_info.get("score")

    small_scores_payload = req.smallscores if req.smallscores is not None else (req.sub_scores or {})

    # Step 2: Prepare submit payload using rev_info metadata
    submit_params = {
        "Flag_Mode": rev_info.get("Flag_Mode", "1"),
        "Flag_Send": rev_info.get("flagsend", "4" if norm_mode == "arb" else "1"),
        "Sec_ID": secid,
        "secid": secid,
        "Que_ID": req.queid or rev_info.get("queid", "1"),
        "queid": req.queid or rev_info.get("queid", "1"),
        "Quename": rev_info.get("quename", ""),
        "quename": rev_info.get("quename", ""),
        "Exam_ID": rev_info.get("examid", ""),
        "examid": rev_info.get("examid", ""),
        "markmodel": rev_info.get("markmodel", "4" if norm_mode == "arb" else "1"),
        "subid": rev_info.get("subid") or req.subid or "",
        "smallnum": str(rev_info.get("smallnum", "0")),
        "biaozhi": "0",
        "pizhu": (req.comment or req.reason or "")[:120],
        "score": format_score_str(req.new_score),
        "smallscores": small_scores_payload,
    }

    res = client.submit_score(submit_params, mode=norm_mode)
    if res.get("status") == "error":
        raise HTTPException(status_code=500, detail=res.get("message", "源站改分提交失败"))

    # Step 3: Readback verification from source review info
    readback_score = format_score_str(req.new_score)
    readback_verified = False
    try:
        verify_info = client.get_review_paper_info(secid, mode=norm_mode)
        if verify_info.get("score") is not None and str(verify_info.get("score")).strip() != "":
            readback_score = format_score_str(verify_info["score"])
            readback_verified = True
    except Exception:
        pass

    # Step 4: Update local job task card & session records if present
    updated_task = None
    target_job = jobs.get(req.job_id) if req.job_id else jobs.get(sess.get("active_job_id", ""))
    if target_job:
        for t in target_job["tasks"]:
            if (req.task_id and t["id"] == req.task_id) or str(t.get("secid")) == secid:
                prev_score = t.get("final_score")
                t["final_score"] = float(req.new_score)
                t["score"] = float(req.new_score)
                t["score_str"] = format_score_str(req.new_score)
                t["status"] = "completed"
                t["raw_status"] = "submitted"
                t["submitted"] = True
                t["regraded"] = True
                if req.comment:
                    t["overall_comment"] = req.comment
                    t["review_note"] = req.comment
                flags = [f for f in (t.get("flags") or []) if f not in ("满分卷", "零分卷", "试评仅预览(未写分)")]
                if float(req.new_score) >= float(target_job.get("full_score") or 6.0):
                    flags.append("满分卷")
                elif float(req.new_score) <= 0:
                    flags.append("零分卷")
                if "人工已改分" not in flags:
                    flags.insert(0, "人工已改分")
                t["flags"] = flags
                t["regrade_history"] = t.get("regrade_history") or []
                t["regrade_history"].append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "old_score": prev_score,
                    "new_score": float(req.new_score),
                    "reason": req.reason,
                })
                updated_task = t
                append_job_event(
                    target_job,
                    "ok",
                    f"✍️ 人工核查改分成功: 试卷 {secid} 分数由 {prev_score} 改为 {format_score_str(req.new_score)} 分 (原因: {req.reason})",
                    task_id=t["id"]
                )
                break

    for rec in sess.get("records", []):
        if str(rec.get("secid")) == secid:
            rec["score"] = float(req.new_score)
            rec["status"] = "submitted"

    record_diagnostic("regrade", sess.get("username", ""), sess.get("base_url", ""), "success", {
        "secid": secid,
        "old_score": old_source_score,
        "new_score": req.new_score,
        "readback_score": readback_score,
        "reason": req.reason,
    })

    return {
        "success": True,
        "secid": secid,
        "paper_id": secid,
        "old_score": old_source_score,
        "new_score": req.new_score,
        "readback_score": readback_score,
        "readback_verified": readback_verified,
        "updated_task": updated_task,
        "message": f"改分成功！源站分数已更新为 {readback_score} 分"
    }


@app.post("/api/paper/ai-regrade")
def api_paper_ai_regrade(req: SingleAIGradeRequest, request: Request):
    """Re-run AI vision grading on a single open paper inside the review modal."""
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    target_job = jobs.get(req.job_id) if req.job_id else jobs.get(sess.get("active_job_id", ""))

    try:
        raw_b64 = req.image_b64 or ""
        if not raw_b64 and target_job and (req.task_id or req.paper_id):
            for t in target_job["tasks"]:
                if (req.task_id and t.get("id") == req.task_id) or (req.paper_id and str(t.get("secid")) == str(req.paper_id)):
                    raw_b64 = t.get("image_data_uri") or t.get("image_base64") or ""
                    break

        if not raw_b64 and client and req.paper_id:
            rev_info = client.get_review_paper_info(str(req.paper_id))
            if rev_info.get("imgpath"):
                ibytes, mtype = client.get_image(rev_info["imgpath"])
                if ibytes:
                    raw_b64 = base64.b64encode(ibytes).decode("utf-8")

        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        if not raw_b64:
            raise ValueError("未能获取到该试卷的作答图像")

        image_bytes = base64.b64decode(raw_b64)
        mime_type = detect_mime_type(image_bytes)
        use_rubric = req.rubric or req.prompt or (target_job.get("rubric") if target_job else "")
        use_fscore = float(req.full_score or req.max_score or (target_job.get("full_score") if target_job else 10.0))
        use_api_key = req.api_key or (target_job.get("api_keys") if target_job else "")
        use_thinking = str(req.thinking_level or req.thinking or "LOW").lower()

        res = AIGrader.grade_image(
            image_bytes=image_bytes,
            rubric=use_rubric,
            full_score=use_fscore,
            provider=req.provider or (target_job.get("provider") if target_job else "gemini"),
            model=req.model or (target_job.get("model") if target_job else "gemini-3.8-flash"),
            api_key=use_api_key,
            thinking=use_thinking,
            base_url=req.base_url,
            markdic_list=req.markdic_list or (target_job.get("markdic_list") if target_job else None),
            sub_questions=req.sub_questions or (target_job.get("sub_questions") if target_job else None),
            mime_type=mime_type,
        )
        return {
            "success": True,
            "ai_result": {
                "total_score": res.get("final_score"),
                "breakdown": res.get("breakdown", []),
                "overall_comment": res.get("overall_comment", ""),
                "student_answer_ocr": res.get("student_answer", ""),
                "sub_scores": res.get("sub_scores", []),
            },
            **res,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/source/review-list")
def api_source_review_list(req: ReviewListRequest, request: Request):
    """Fetch source server's graded paper review list (回评试卷列表) so teacher can inspect/modify ANY paper."""
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    if not client or not client.is_logged_in:
        raise HTTPException(status_code=401, detail="请先登录阅卷系统")
    use_fanwei = req.score_filter if (req.score_filter is not None and str(req.score_filter).strip() != "") else req.fanwei
    res = client.get_review_list(req.queid, nowpage=req.nowpage, fanwei=use_fanwei, mode=_normalize_mode(req.mode))
    items = res.get("items") or []
    reviews = [
        {
            "paper_id": it.get("secid"),
            "secid": it.get("secid"),
            "score": float(it["score"]) if str(it.get("score", "")).replace(".", "", 1).isdigit() else 0,
            "mark_time": it.get("time", ""),
            "paper_type": it.get("type", "正评卷"),
        }
        for it in items
    ]
    return {"reviews": reviews, **res}


@app.post("/api/source/review-detail")
def api_source_review_detail(req: ReviewDetailRequest, request: Request):
    """Load any graded paper from the source server's review list into the inspection & score-modification modal."""
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    if not client or not client.is_logged_in:
        raise HTTPException(status_code=401, detail="请先登录阅卷系统")

    secid = str(req.secid or req.paper_id).strip()
    norm_mode = _normalize_mode(req.mode)
    task_res = client.get_review_paper_info(secid, mode=norm_mode)
    imgpath = task_res.get("imgpath")
    data_uri = ""
    if imgpath:
        img_bytes, mime_type = client.get_image(imgpath, splice=_normalize_splice(req.splice))
        if img_bytes:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            data_uri = f"data:{mime_type};base64,{b64}"

    # Check if we also have local AI grading details for this secid
    local_match = next((r for r in sess.get("records", []) if str(r.get("secid")) == secid), None)

    card = {
        "id": local_match["task_id"] if local_match else f"SRC-{secid}",
        "task_id": local_match["task_id"] if local_match else f"SRC-{secid}",
        "secid": secid,
        "paper_id": secid,
        "examid": task_res.get("examid", ""),
        "queid": task_res.get("queid") or req.queid or "1",
        "quename": task_res.get("quename") or f"题号 {req.queid or ''}",
        "mode": norm_mode,
        "status": "completed",
        "submitted": True,
        "final_score": float(task_res["score"]) if (task_res.get("score") not in (None, "")) else (local_match["score"] if local_match else 0.0),
        "score": float(task_res["score"]) if (task_res.get("score") not in (None, "")) else (local_match["score"] if local_match else 0.0),
        "score_str": format_score_str(task_res.get("score") if task_res.get("score") not in (None, "") else (local_match["score"] if local_match else 0)),
        "full_score": float(task_res.get("fullmark") or (local_match["full_score"] if local_match else 6.0)),
        "max_score": float(task_res.get("fullmark") or (local_match["full_score"] if local_match else 6.0)),
        "student_answer": local_match.get("ocr_text", "（源站历史已评试卷 · 点击右侧『🤖 AI 单卷重评』可即时生成 OCR 与逐点解析）") if local_match else "（源站历史已评试卷 · 点击右侧『🤖 AI 单卷重评』可即时生成 OCR 与逐点解析）",
        "student_answer_ocr": local_match.get("ocr_text", "（源站历史已评试卷 · 点击右侧『🤖 AI 单卷重评』可即时生成 OCR 与逐点解析）") if local_match else "（源站历史已评试卷 · 点击右侧『🤖 AI 单卷重评』可即时生成 OCR 与逐点解析）",
        "overall_comment": local_match.get("comment", "来自源站回评记录，可直接核查原图并修改分数。") if local_match else "来自源站回评记录，可直接核查原图并修改分数。",
        "point_scores": {},
        "point_comments": {},
        "breakdown": local_match.get("breakdown", []) if local_match else [],
        "sub_scores": local_match.get("sub_scores", []) if local_match else [],
        "flags": ["源站回评卷"],
        "ai_provider": local_match.get("provider", "source") if local_match else "source",
        "ai_model": local_match.get("model", "源站记录") if local_match else "源站记录",
        "ai_latency_ms": local_match.get("latency_ms", 0) if local_match else 0,
        "image_data_uri": data_uri,
        "image_base64": data_uri,
        "imgpath": imgpath or "",
        "zimgpath": task_res.get("zimgpath", ""),
        "raw_task_meta": task_res,
        "created_at": local_match.get("time", "源站历史") if local_match else "源站历史",
    }
    return {
        "card": card,
        "detail": {
            "paper_id": secid,
            "image_base64": data_uri,
            "zimgpath": task_res.get("zimgpath", ""),
        },
        "metadata": task_res,
    }


@app.post("/api/paper/whole-paper")
def api_whole_paper(req: FullPaperRequest, request: Request):
    """Fetch all physical pages in zimgpath (semicolon-separated) for '查看整卷'."""
    sess, _ = get_session(request)
    client: Optional[HaidianClient] = sess.get("client")
    if not client or not client.is_logged_in:
        raise HTTPException(status_code=401, detail="请先登录阅卷系统")

    zpath = (req.zimgpath or "").strip()
    if not zpath and req.paper_id:
        for r in sess.get("records", []):
            if str(r.get("secid")) == str(req.paper_id) and r.get("zimgpath"):
                zpath = r["zimgpath"]
                break
        if not zpath:
            rev_info = client.get_review_paper_info(str(req.paper_id))
            zpath = rev_info.get("zimgpath") or ""

    paths = [p.strip() for p in zpath.split(";") if p.strip()]
    pages = []
    sheets = []
    for idx, p in enumerate(paths[:12]):
        img_bytes, mime_type = client.get_image(p, is_full_paper=True)
        if img_bytes:
            b64_str = base64.b64encode(img_bytes).decode("utf-8")
            pages.append({
                "page": idx + 1,
                "path": p,
                "mime_type": mime_type,
                "image_b64": b64_str,
            })
            sheets.append({
                "label": f"整卷第 {idx + 1} 面",
                "image_base64": f"data:{mime_type};base64,{b64_str}",
            })
    return {"pages": pages, "sheets": sheets}


@app.post("/api/report/summary")
def api_generate_summary(req: AISummaryRequest, request: Request):
    sess, _ = get_session(request)
    job = jobs.get(req.job_id) if req.job_id else jobs.get(sess.get("active_job_id", ""))

    records = sess.get("records", [])
    if req.queid:
        filtered = [r for r in records if str(r.get("queid")) == str(req.queid)]
        if filtered:
            records = filtered

    api_key = req.api_key or (job.get("api_keys") if job else "")
    provider = req.provider or (job.get("provider") if job else "gemini")
    model = req.model or (job.get("model") if job else "gemini-3.8-flash")
    base_url = req.base_url or (job.get("api_base_url") if job else None)
    src_prog = job.get("source_progress") if job else None
    q_name = req.quename or req.que_name or (job.get("quename") if job else "当前试题")
    f_score = float(req.full_score or req.max_score or (job.get("full_score") if job else 10.0))

    try:
        report_md = AIGrader.generate_summary_report(
            records=records,
            que_name=q_name,
            full_score=f_score,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            source_progress=src_prog,
        )
        return {"report": report_md, "report_markdown": report_md, "sample_count": len(records)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/debug/diagnostics")
def api_get_diagnostics():
    return {
        "total_events": len(diagnostic_events),
        "events": list(diagnostic_events)[:80]
    }


# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
if os.path.exists(os.path.join(static_dir, "data")):
    app.mount("/data", StaticFiles(directory=os.path.join(static_dir, "data")), name="data")


@app.get("/")
def index_page():
    return FileResponse(os.path.join(static_dir, "index.html"))
