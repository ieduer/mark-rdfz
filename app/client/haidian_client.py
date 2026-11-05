import base64
from datetime import datetime
import json
import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger("haidian_client")

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None


def zero_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = (block_size - (len(data) % block_size)) % block_size
    if pad_len == 0:
        return data
    return data + b"\x00" * pad_len


def aes_encrypt(key_str: str, plain_text: str, iv_str: str = "NHIIwsyjnhiiWSYJ") -> str:
    if not AES:
        raise RuntimeError("pycryptodome is required for AES encryption")
    key = key_str.encode("latin1")[:16]
    iv = iv_str.encode("latin1")[:16]
    padded = zero_pad(plain_text.encode("utf-8"), 16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(padded)
    return base64.b64encode(encrypted).decode("utf-8")


def detect_mime_type(data: bytes) -> str:
    """Detect image MIME type from magic header bytes."""
    if not data:
        return "image/jpeg"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def format_score_str(val: Any) -> str:
    """Format numeric score cleanly (e.g. 5.0 -> '5', 4.5 -> '4.5') to match markdic tokens."""
    if val is None or val == "":
        return "0"
    try:
        f = float(val)
        if abs(f - round(f)) < 1e-6:
            return str(int(round(f)))
        return f"{f:g}"
    except Exception:
        return str(val).strip()


class HaidianClient:
    """Client for Haidian / Yuemanfen online marking platforms (Modern AES + Legacy JSP)."""

    def __init__(self, base_url: str):
        url = base_url.strip().rstrip("/")
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "http://" + url
        self.base_url = url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self.is_logged_in = False
        self.username = ""
        self.role_id = "2"
        self.current_user_id = ""
        self.context_path = ""
        self.current_subid_hex = ""
        self.current_subid_num = ""
        self.current_mode = "normal"  # 'normal' | 'arb'
        self.cached_questions: List[Dict[str, Any]] = []
        self.last_task_meta: Dict[str, Any] = {}
        self._detect_context_path()

    def _detect_context_path(self):
        parsed = urllib.parse.urlparse(self.base_url)
        path = parsed.path.strip("/")
        if path:
            self.context_path = "/" + path
            if path.lower() == "exam":
                self.root_url = f"{parsed.scheme}://{parsed.netloc}"
            else:
                self.root_url = self.base_url
        else:
            self.context_path = ""
            self.root_url = self.base_url

    def get_url(self, endpoint: str) -> str:
        """Build URL relative to base_url or root_url."""
        ep = endpoint.lstrip("/")
        if ep.startswith("http://") or ep.startswith("https://"):
            return ep
        base = self.base_url
        if base.endswith("/exam") and ep.startswith("exam/"):
            ep = ep[5:]
        return f"{base}/{ep}"

    def get_exam_url(self, endpoint: str) -> str:
        """Build URL guaranteed to be under /exam/... unless context_path already has /exam."""
        ep = endpoint.lstrip("/")
        if ep.startswith("http://") or ep.startswith("https://"):
            return ep
        if ep.startswith("exam/"):
            ep = ep[5:]
        if self.base_url.endswith("/exam"):
            return f"{self.base_url}/{ep}"
        return f"{self.root_url}/exam/{ep}"

    def _decode_response(self, resp: requests.Response) -> str:
        """Decode HTTP response supporting both UTF-8 and GBK/GB2312."""
        content = resp.content
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content.decode("gbk", errors="ignore")

    def _bridge_exam_checkuser(self, html_or_text: str) -> bool:
        """Extract and visit /exam/mark/exam/checkuser?roleid=...&userid=... to initialize /exam session."""
        matches = re.findall(r'((?:exam/)?mark/exam/checkuser\?[^"\'\s<>]+)', html_or_text)
        if matches:
            check_path = matches[0].replace("&amp;", "&")
            check_url = self.get_exam_url(check_path)
            try:
                r = self.session.get(check_url, timeout=10)
                logger.info(f"Visited /exam checkuser bridge: {check_url} -> HTTP {r.status_code}")
                return r.status_code == 200
            except Exception as e:
                logger.warning(f"Failed visiting checkuser bridge ({check_url}): {e}")
        return False

    def login(self, username: str, password: str) -> Tuple[bool, str]:
        self.username = username

        # Strategy 1: Modern Yuemanfen AES flow (GET / -> /ajaxkeydao -> /logindao -> /changepwd -> homepage.jsp -> /exam/mark/exam/checkuser)
        try:
            # Step 1a: Visit root page first to initialize JSESSIONID and extract hidden form defaults (token, shenfen, order)
            token_val = datetime.now().strftime("%Y-%m-%d")
            shenfen_val = "3"
            order_val = "123456"
            try:
                root_resp = self.session.get(f"{self.root_url}/", timeout=6)
                if root_resp.status_code == 200:
                    root_html = self._decode_response(root_resp)
                    m_tok = re.search(r'name=["\']token["\']\s+value=["\']([^"\']+)["\']', root_html)
                    m_sf = re.search(r'name=["\']shenfen["\'][^>]*value=["\']([^"\']+)["\']', root_html)
                    m_ord = re.search(r'name=["\']order["\']\s+value=["\']([^"\']+)["\']', root_html)
                    if m_tok:
                        token_val = m_tok.group(1)
                    if m_sf:
                        shenfen_val = m_sf.group(1)
                    if m_ord:
                        order_val = m_ord.group(1)
            except Exception:
                pass

            ajax_url = f"{self.root_url}/ajaxkeydao"
            key_resp = self.session.post(ajax_url, timeout=6)
            if key_resp.status_code == 200 and len(key_resp.text.strip()) == 16:
                aes_key = key_resp.text.strip()
                logger.info(f"Detected modern Yuemanfen platform, AES key={aes_key}")
                enc_name = aes_encrypt(aes_key, username)
                enc_pwd = aes_encrypt(aes_key, password)
                login_payload = {
                    "user_name": enc_name,
                    "user_pwd": enc_pwd,
                    "token": token_val,
                    "shenfen": shenfen_val,
                    "order": order_val
                }
                lresp = self.session.post(f"{self.root_url}/logindao", data=login_payload, timeout=10)
                ltext = self._decode_response(lresp).strip()

                # Check explicit error responses from logindao
                if (
                    ltext in ("0", "false", "error")
                    or "密码错误" in ltext
                    or "账号或密码" in ltext
                    or 'id="serverTip" value="1"' in ltext
                    or 'id="serverTip" value="2"' in ltext
                ):
                    return False, "用户名或密码错误"

                if lresp.status_code in (200, 302):
                    # Execute changepwd skip step used by modern Yuemanfen portal
                    try:
                        cp_resp = self.session.post(f"{self.root_url}/changepwd", data={
                            "account": username,
                            "remark": "0",
                            "index_": "0"
                        }, timeout=8)
                        cp_html = self._decode_response(cp_resp)
                    except Exception:
                        cp_html = ""

                    # Bridge to /exam context via checkuser link
                    bridged = self._bridge_exam_checkuser(ltext) or self._bridge_exam_checkuser(cp_html)
                    if not bridged:
                        for hp_path in ("base/newuiteacher/homepage.jsp", "homepage.jsp"):
                            try:
                                hp_resp = self.session.get(f"{self.root_url}/{hp_path}", timeout=8)
                                if hp_resp.status_code == 200:
                                    hp_html = self._decode_response(hp_resp)
                                    if self._bridge_exam_checkuser(hp_html):
                                        bridged = True
                                        break
                            except Exception:
                                pass

                    if not bridged and ("login-container" in ltext and "form1" in ltext):
                        return False, "登录未通过校验，请核对账号或密码"

                    self.is_logged_in = True
                    bridge_note = "已建立阅卷会话" if bridged else "现代接口"
                    return True, f"登录成功 ({bridge_note})"
        except Exception as e:
            logger.debug(f"ajaxkeydao modern login check skipped: {e}")

        # Strategy 2: Legacy JSP login (/exam/login.jsp -> /exam/login_ok.jsp -> /exam/teacher/index.jsp)
        try:
            login_jsp_url = self.get_exam_url("login.jsp")
            self.session.get(login_jsp_url, timeout=8)

            post_login_url = self.get_exam_url("login_ok.jsp")
            form_data = {
                "logname": username,
                "logpass": password
            }
            resp = self.session.post(post_login_url, data=form_data, timeout=10)
            text_decoded = self._decode_response(resp)

            if (
                "账号或密码不正确" in text_decoded
                or "密码错误" in text_decoded
                or "用户不存在" in text_decoded
                or ("alert" in text_decoded and "login.jsp" in text_decoded)
            ):
                return False, "用户名或密码错误"

            self._bridge_exam_checkuser(text_decoded)
            try:
                t_resp = self.session.get(self.get_exam_url("teacher/index.jsp"), timeout=8)
                if t_resp.status_code == 200:
                    self._bridge_exam_checkuser(self._decode_response(t_resp))
            except Exception:
                pass

            self.is_logged_in = True
            return True, "登录成功 (JSP传统接口)"
        except Exception as e:
            logger.error(f"Legacy login failed: {e}", exc_info=True)
            return False, f"连接目标源站失败: {str(e)}"

    def get_subjects(self) -> Dict[str, Any]:
        """Fetch active exam subjects and tasks from Mtaskinfo / taskinfo."""
        subjects: List[Dict[str, Any]] = []
        raw_snippets: List[str] = []

        for ep in ("mark/task/Mtaskinfo", "mark/task/taskinfo"):
            url = self.get_exam_url(ep)
            try:
                r = self.session.get(url, timeout=10)
                if r.headers.get("sessionstatus") == "TIMEOUT":
                    continue
                html = self._decode_response(r)
                raw_snippets.append(html[:1500])
                parsed = self._parse_taskinfo_html(html)
                if parsed:
                    subjects = parsed
                    break
            except Exception as e:
                logger.warning(f"Fetch {url} error: {e}")

        if subjects and not self.current_subid_hex:
            self.current_subid_hex = subjects[0].get("subid") or subjects[0].get("arb_subid") or ""

        return {
            "status": "ok",
            "subjects": subjects,
            "current_subid": self.current_subid_hex,
            "raw_preview": raw_snippets[0] if raw_snippets else ""
        }

    def _parse_taskinfo_html(self, html: str) -> List[Dict[str, Any]]:
        """Parse div.paper-box entries from Mtaskinfo / taskinfo HTML."""
        results: List[Dict[str, Any]] = []
        blocks = re.split(r'<div\s+class=["\']paper-box["\']\s*>', html)
        for blk in blocks[1:]:
            title_m = re.search(r"<h5>(.*?)</h5>", blk, re.S)
            date_m = re.search(r'class=["\']t-time["\'][^>]*>.*?<span>(.*?)</span>', blk, re.S)
            course_m = re.search(r'class=["\']t-course["\'][^>]*>.*?<span>(.*?)</span>', blk, re.S)
            prog_m = re.search(r'class=["\']jding["\'][^>]*>(.*?)</div>', blk, re.S)

            subid_m = re.search(r'mark/task/taskpaper\?subid=([0-9A-Za-z_-]+)', blk)
            arb_m = re.search(r'mark/task/arbitratepaper\?subid=([0-9A-Za-z_-]+)', blk)

            subid = subid_m.group(1) if subid_m else ""
            arb_subid = arb_m.group(1) if arb_m else ""
            if not subid and not arb_subid:
                continue

            exam_name = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else "当前考试"
            exam_date = re.sub(r"<[^>]+>", "", date_m.group(1)).strip() if date_m else ""
            subject_name = re.sub(r"<[^>]+>", "", course_m.group(1)).strip() if course_m else "默认科目"
            progress_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", prog_m.group(1))).strip() if prog_m else ""

            results.append({
                "subid": subid or arb_subid,
                "normal_subid": subid,
                "arb_subid": arb_subid,
                "exam_name": exam_name,
                "exam_date": exam_date,
                "subject_name": subject_name,
                "progress": progress_text,
                "has_normal": bool(subid),
                "has_arb": bool(arb_subid),
            })

        if not results:
            normal_ids = re.findall(r'taskpaper\?subid=([0-9A-Za-z_-]+)', html)
            arb_ids = re.findall(r'arbitratepaper\?subid=([0-9A-Za-z_-]+)', html)
            seen = set()
            for sid in normal_ids + arb_ids:
                if sid in seen:
                    continue
                seen.add(sid)
                results.append({
                    "subid": sid,
                    "normal_subid": sid if sid in normal_ids else "",
                    "arb_subid": sid if sid in arb_ids else "",
                    "exam_name": "当前考试任务",
                    "exam_date": "",
                    "subject_name": f"科目 ({sid[:8]})",
                    "progress": "",
                    "has_normal": sid in normal_ids,
                    "has_arb": sid in arb_ids,
                })

        return results

    def load_subject_paper(self, subid: str, mode: str = "normal") -> Dict[str, Any]:
        """
        Visit taskpaper?subid=... (normal) or arbitratepaper?subid=... (arb).
        Extracts question list (.marking-tit span), hidden #taskmark inputs, and initial task state.
        """
        self.current_subid_hex = subid
        self.current_mode = mode
        endpoint = f"mark/task/arbitratepaper?subid={subid}" if mode == "arb" else f"mark/task/taskpaper?subid={subid}"
        url = self.get_exam_url(endpoint)

        try:
            r = self.session.get(url, timeout=12)
            html = self._decode_response(r)

            # 1. Extract questions from <div class="marking-tit">
            questions: List[Dict[str, Any]] = []
            tit_m = re.search(r'<div\s+class=["\']marking-tit["\'][^>]*>(.*?)</div>', html, re.S)
            if tit_m:
                span_matches = re.findall(r'<span([^>]*)>(.*?)</span>', tit_m.group(1), re.S)
                for attrs, qname in span_matches:
                    id_m = re.search(r'id=["\']([^"\']+)["\']', attrs)
                    if id_m:
                        qid = id_m.group(1).strip()
                        clean_name = re.sub(r"<[^>]+>", "", qname).strip()
                        is_on = "on" in attrs
                        questions.append({
                            "queid": qid,
                            "name": clean_name,
                            "active": is_on
                        })

            self.cached_questions = questions

            # 2. Extract hidden #taskmark inputs
            form_fields: Dict[str, str] = {}
            for inp in re.findall(r"<input[^>]+>", html):
                id_m = re.search(r'(?:id|name)=["\']([^"\']+)["\']', inp)
                val_m = re.search(r'value=["\']([^"\']*)["\']', inp)
                if id_m and val_m:
                    form_fields[id_m.group(1)] = val_m.group(1)

            if form_fields.get("subid"):
                self.current_subid_num = form_fields["subid"]

            # 3. Extract teamarkcount & taskcount
            teamark_m = re.search(r'id=["\']teamarkcount["\'][^>]*>(\d+)<', html)
            taskcnt_m = re.search(r'id=["\']taskcount["\'][^>]*>(\d+)<', html)
            teamarkcount = teamark_m.group(1) if teamark_m else "0"
            taskcount = taskcnt_m.group(1) if taskcnt_m else "0"

            # 4. Extract initial #taskimg src if present
            img_m = re.search(r'<img[^>]+id=["\']taskimg["\'][^>]*src=["\']([^"\']*)["\']', html)
            if not img_m:
                img_m = re.search(r'<img[^>]+src=["\']([^"\']*showimage[^"\']*)["\'][^>]*id=["\']taskimg["\']', html)
            initial_img_src = img_m.group(1).replace("&amp;", "&") if img_m else ""

            # 5. Extract initial markdic and fullmark from HTML if initial task is active
            num_spans = re.findall(r'<div\s+class=["\']num-list["\'][^>]*>(.*?)</div>', html, re.S)
            initial_markdic = ""
            if num_spans:
                vals = re.findall(r"<span[^>]*>([^<]+)</span>", num_spans[0])
                initial_markdic = ",".join(v.strip() for v in vals if v.strip())

            fullmark_m = re.search(r'placeholder=["\']满分([0-9.]+)["\']', html)
            initial_fullmark = fullmark_m.group(1) if fullmark_m else (
                initial_markdic.split(",")[-1] if initial_markdic else "6"
            )

            active_que = next((q for q in questions if q.get("active")), questions[0] if questions else None)
            active_queid = form_fields.get("Que_ID") or (active_que["queid"] if active_que else "")
            active_quename = active_que["name"] if active_que else ""

            initial_task = None
            if form_fields.get("nottask") != "1" and form_fields.get("secid") and form_fields.get("secid") != "0":
                initial_task = {
                    "codeid": "0001",
                    "secid": form_fields.get("secid", ""),
                    "examid": form_fields.get("examid", ""),
                    "queid": active_queid,
                    "quename": active_quename,
                    "flagsend": form_fields.get("Flag_Send", "1"),
                    "Flag_Mode": form_fields.get("Flag_Mode", "1"),
                    "markmodel": form_fields.get("markmodel", "1"),
                    "smallnum": form_fields.get("smallnum", "0"),
                    "subid": self.current_subid_num,
                    "imgwidth": form_fields.get("imgwidth", "900"),
                    "imgpath": initial_img_src,
                    "zimgpath": form_fields.get("zimgpath", ""),
                    "fullmark": initial_fullmark,
                    "markdic": initial_markdic,
                    "teamarkcount": teamarkcount,
                    "taskcount": taskcount,
                    "mode": mode,
                }
                self.last_task_meta = initial_task
            elif len(questions) > 1 and form_fields.get("nottask") == "1":
                # If the default first question has no tasks (nottask == "1"), default active_queid to the 2nd question (e.g. 第9-16题)
                active_queid = questions[1]["queid"]

            return {
                "status": "ok",
                "mode": mode,
                "subid_hex": subid,
                "subid_num": self.current_subid_num,
                "questions": questions,
                "active_queid": active_queid,
                "form_fields": form_fields,
                "teamarkcount": teamarkcount,
                "taskcount": taskcount,
                "initial_task": initial_task,
            }
        except Exception as e:
            logger.error(f"load_subject_paper error ({url}): {e}", exc_info=True)
            return {"status": "error", "message": str(e), "questions": []}

    def get_task_info(self) -> Dict[str, Any]:
        """Backward-compatible wrapper returning subjects and discovered questions."""
        sub_res = self.get_subjects()
        subjects = sub_res.get("subjects", [])
        if subjects and not self.cached_questions:
            first_sub = subjects[0]
            sid = first_sub.get("normal_subid") or first_sub.get("arb_subid") or first_sub.get("subid")
            mode = "normal" if first_sub.get("normal_subid") else "arb"
            if sid:
                self.load_subject_paper(sid, mode=mode)

        return {
            "status": "ok",
            "subjects": subjects,
            "questions": self.cached_questions,
            "found_que_ids": [q["queid"] for q in self.cached_questions],
            "subid_num": self.current_subid_num,
        }

    def _enrich_task_metadata(self, data: Dict[str, Any], queid: str = "", mode: str = "normal") -> Dict[str, Any]:
        """Normalize and enrich task metadata with parsed sub-questions and cached defaults."""
        if not isinstance(data, dict):
            return {"codeid": "-1", "message": "Invalid task data"}

        prev = self.last_task_meta or {}
        same_que = str(data.get("queid") or queid) == str(prev.get("queid") or "")

        if not data.get("subid"):
            data["subid"] = self.current_subid_num or prev.get("subid", "")
        if not data.get("queid") and queid:
            data["queid"] = str(queid)
        if not data.get("quename"):
            q_match = next((q for q in self.cached_questions if str(q["queid"]) == str(data.get("queid"))), None)
            data["quename"] = q_match["name"] if q_match else (prev.get("quename", "") if same_que else f"第{data.get('queid', '')}题")

        if same_que:
            for key in ("fullmark", "markdic", "smallnum", "smallname", "smallmark", "smallmarkdic", "imgwidth", "Flag_Mode"):
                if key not in data or data[key] is None or data[key] == "":
                    if key in prev:
                        data[key] = prev[key]

        data["mode"] = mode or self.current_mode or "normal"

        try:
            smallnum = int(data.get("smallnum") or 0)
        except ValueError:
            smallnum = 0

        sub_questions: List[Dict[str, Any]] = []
        if smallnum > 1:
            s_names = str(data.get("smallname") or "").split(";")
            s_marks = str(data.get("smallmark") or "").split(";")
            s_dics = str(data.get("smallmarkdic") or "").split(";")
            total_full = 0.0
            for i in range(smallnum):
                sname = s_names[i].strip() if i < len(s_names) and s_names[i].strip() else f"小题{i+1}"
                try:
                    smark = float(s_marks[i]) if i < len(s_marks) and s_marks[i] else 0.0
                except ValueError:
                    smark = 0.0
                total_full += smark
                sdic_raw = s_dics[i] if i < len(s_dics) else ""
                sdic_list = [x.strip() for x in sdic_raw.split(",") if x.strip()]
                sub_questions.append({
                    "index": i,
                    "field": f"smallscore{i}",
                    "name": sname,
                    "fullmark": smark,
                    "markdic": sdic_list
                })
            if not data.get("fullmark") and total_full > 0:
                data["fullmark"] = format_score_str(total_full)

        data["sub_questions"] = sub_questions

        markdic_str = str(data.get("markdic") or "")
        if markdic_str:
            data["markdic_list"] = [x.strip() for x in markdic_str.split(",") if x.strip()]
            if not data.get("fullmark") and data["markdic_list"]:
                data["fullmark"] = data["markdic_list"][-1]
        else:
            data["markdic_list"] = []

        if data.get("codeid") == "0001":
            self.last_task_meta = dict(data)

        return data

    def claim_task(self, queid: str, mode: Optional[str] = None) -> Dict[str, Any]:
        """Claim next paper slice via changetaskque (normal) or changearbtaskque (arbitration)."""
        use_mode = mode or self.current_mode or "normal"
        self.current_mode = use_mode

        if not self.current_subid_num and not self.current_subid_hex:
            sub_res = self.get_subjects()
            subs = sub_res.get("subjects", [])
            if subs:
                sid = subs[0].get("arb_subid") if use_mode == "arb" else subs[0].get("normal_subid")
                sid = sid or subs[0].get("subid")
                if sid:
                    self.load_subject_paper(sid, mode=use_mode)

        ep = "mark/task/changearbtaskque" if use_mode == "arb" else "mark/task/changetaskque"
        url = self.get_exam_url(ep)
        payload = {"queid": str(queid)}
        try:
            r = self.session.post(url, data=payload, timeout=15)
            text = self._decode_response(r).strip()
            try:
                data = json.loads(text)
            except Exception:
                data = {"codeid": "-1", "message": text[:300], "raw": text[:500]}

            if data.get("codeid") != "0001" and self.last_task_meta and str(self.last_task_meta.get("queid")) == str(queid):
                if self.last_task_meta.get("imgpath"):
                    return self.last_task_meta

            return self._enrich_task_metadata(data, queid=str(queid), mode=use_mode)
        except Exception as e:
            logger.error(f"Claim task error ({url}): {e}")
            return {"codeid": "-1", "message": str(e)}

    def get_image(self, imgpath: str, splice: int = 0, is_full_paper: bool = False) -> Tuple[Optional[bytes], str]:
        """
        Download answer sheet image and detect its MIME type.
        Supports Yuemanfen encrypted hex tokens via /exam/showimage?path=<hex>&splice=<0|1>
        and full paper images via /exam/showimageyun?path=<hex>.
        """
        if not imgpath or not str(imgpath).strip():
            return None, "image/jpeg"

        raw_path = str(imgpath).strip().replace("&amp;", "&")
        candidate_urls: List[str] = []

        if raw_path.startswith("http://") or raw_path.startswith("https://"):
            candidate_urls.append(raw_path)
        elif is_full_paper:
            candidate_urls.append(self.get_exam_url(f"showimageyun?path={raw_path}"))
            candidate_urls.append(self.get_exam_url(f"showimage?path={raw_path}&splice={splice}"))
        elif "showimage" in raw_path:
            if "splice=" in raw_path:
                raw_path = re.sub(r"splice=\d+", f"splice={splice}", raw_path)
            elif "?" in raw_path and "showimageyun" not in raw_path:
                raw_path = f"{raw_path}&splice={splice}"
            candidate_urls.append(self.get_exam_url(raw_path))
        elif re.match(r"^[0-9A-Fa-f]{16,}$", raw_path) or ("/" not in raw_path and "." not in raw_path):
            candidate_urls.append(self.get_exam_url(f"showimage?path={raw_path}&splice={splice}"))
            candidate_urls.append(self.get_exam_url(f"showimageyun?path={raw_path}"))
        else:
            candidate_urls.append(self.get_exam_url(raw_path))
            candidate_urls.append(self.get_url(raw_path))
            candidate_urls.append(self.get_exam_url(f"showimage?path={raw_path}&splice={splice}"))

        for url in candidate_urls:
            try:
                r = self.session.get(url, timeout=20)
                if r.status_code == 200 and r.content and len(r.content) > 64:
                    head = r.content[:64].lstrip().lower()
                    if head.startswith(b"<!doctype") or head.startswith(b"<html") or head.startswith(b"<script"):
                        continue
                    mime = detect_mime_type(r.content)
                    return r.content, mime
            except Exception as e:
                logger.warning(f"Download image candidate failed ({url}): {e}")

        return None, "image/jpeg"

    def submit_score(self, params: Dict[str, Any], mode: Optional[str] = None) -> Dict[str, Any]:
        """Submit score for current task (#taskmark)."""
        use_mode = mode or params.get("mode") or self.current_mode or "normal"
        ep = "mark/task/submitarbscore" if use_mode == "arb" else "mark/task/submitscore"
        url = self.get_exam_url(ep)

        prev = self.last_task_meta or {}
        queid = str(params.get("Que_ID") or params.get("queid") or prev.get("queid") or "")
        subid = str(params.get("subid") or self.current_subid_num or prev.get("subid") or "")
        smallnum_val = int(params.get("smallnum") or prev.get("smallnum") or 0)

        form_data: Dict[str, str] = {
            "biaozhi": str(params.get("biaozhi") if params.get("biaozhi") is not None else "0"),
            "subid": subid,
            "smallnum": str(smallnum_val),
            "Flag_Mode": str(params.get("Flag_Mode") or prev.get("Flag_Mode") or "1"),
            "secid": str(params.get("secid") or prev.get("secid") or ""),
            "examid": str(params.get("examid") or prev.get("examid") or ""),
            "Que_ID": queid,
            "Flag_Send": str(params.get("Flag_Send") or prev.get("flagsend") or "1"),
            "pizhu": str(params.get("pizhu") or ""),
            "leijiastr": str(params.get("leijiastr") or ""),
            "leijianstr": str(params.get("leijianstr") or ""),
            "markmodel": str(params.get("markmodel") or prev.get("markmodel") or "1"),
            "score": format_score_str(params.get("score", 0)),
        }

        smallscores = params.get("smallscores")
        if isinstance(smallscores, dict) and smallscores:
            form_data["smallnum"] = str(max(smallnum_val, len(smallscores)))
            for idx, k in enumerate(sorted(smallscores.keys())):
                key_name = k if str(k).startswith("smallscore") else f"smallscore{idx}"
                form_data[key_name] = format_score_str(smallscores[k])
        elif isinstance(smallscores, list) and smallscores:
            form_data["smallnum"] = str(max(smallnum_val, len(smallscores)))
            for idx, val in enumerate(smallscores):
                form_data[f"smallscore{idx}"] = format_score_str(val)

        try:
            r = self.session.post(url, data=form_data, timeout=15)
            text = self._decode_response(r).strip()
            try:
                res = json.loads(text)
            except Exception:
                res = {
                    "codeid": "0001" if ("成功" in text or r.status_code == 200) else "0000",
                    "message": text[:300]
                }

            if isinstance(res, dict) and res.get("codeid") in ("0001", "0011"):
                res = self._enrich_task_metadata(res, queid=queid, mode=use_mode)
            return res
        except Exception as e:
            logger.error(f"Submit score error ({url}): {e}")
            return {"codeid": "-1", "message": str(e)}

    def to_arbitrate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Escalate paper to arbitration / abnormal queue (mark/task/Toarbitrate)."""
        url = self.get_exam_url("mark/task/Toarbitrate")
        prev = self.last_task_meta or {}
        queid = str(params.get("Que_ID") or params.get("queid") or prev.get("queid") or "")
        subid = str(params.get("subid") or self.current_subid_num or prev.get("subid") or "")

        form_data: Dict[str, str] = {
            "biaozhi": str(params.get("biaozhi") or "0"),
            "subid": subid,
            "smallnum": str(params.get("smallnum") or prev.get("smallnum") or "0"),
            "Flag_Mode": str(params.get("Flag_Mode") or prev.get("Flag_Mode") or "1"),
            "secid": str(params.get("secid") or prev.get("secid") or ""),
            "examid": str(params.get("examid") or prev.get("examid") or ""),
            "Que_ID": queid,
            "Flag_Send": str(params.get("Flag_Send") or prev.get("flagsend") or "1"),
            "pizhu": str(params.get("pizhu") or ""),
            "leijiastr": "",
            "leijianstr": "",
            "markmodel": str(params.get("markmodel") or prev.get("markmodel") or "1"),
            "score": format_score_str(params.get("score", "")),
        }
        try:
            r = self.session.post(url, data=form_data, timeout=15)
            text = self._decode_response(r).strip()
            try:
                res = json.loads(text)
            except Exception:
                res = {
                    "codeid": "0001" if ("成功" in text or r.status_code == 200) else "0000",
                    "message": text[:300]
                }
            if isinstance(res, dict) and res.get("codeid") == "0001":
                res = self._enrich_task_metadata(res, queid=queid, mode=self.current_mode)
            return res
        except Exception as e:
            logger.error(f"Arbitrate error ({url}): {e}")
            return {"codeid": "-1", "message": str(e)}

    def get_review_list(self, queid: str, nowpage: int = 1, fanwei: str = "", mode: Optional[str] = None) -> Dict[str, Any]:
        """Get graded history / review paper list (gethppaper / gethppapersel)."""
        use_mode = mode or self.current_mode or "normal"
        if nowpage <= 1 and (not fanwei or fanwei == "全部"):
            ep = "mark/task/getarbhppaper" if use_mode == "arb" else "mark/task/gethppaper"
            payload = {"queid": str(queid)}
        else:
            ep = "mark/task/getarbhppapersel" if use_mode == "arb" else "mark/task/gethppapersel"
            payload = {
                "queid": str(queid),
                "nowpage": str(nowpage),
                "fanwei": "全部" if not fanwei else str(fanwei)
            }

        url = self.get_exam_url(ep)
        try:
            r = self.session.post(url, data=payload, timeout=15)
            text = self._decode_response(r).strip()
            data = json.loads(text)
            items: List[Dict[str, str]] = []
            hppaper_str = str(data.get("hppaper") or "")
            if hppaper_str:
                for entry in hppaper_str.split(";"):
                    parts = [p.strip() for p in entry.split(",")]
                    if len(parts) >= 3:
                        items.append({
                            "index": parts[0],
                            "secid": parts[1],
                            "score": parts[2]
                        })
            scores_str = str(data.get("scores") or "")
            score_filters = [s.strip() for s in scores_str.split(";") if s.strip()] if scores_str else []
            return {
                "status": "ok",
                "codeid": data.get("codeid", "0001"),
                "nowpage": int(data.get("nowpage") or nowpage),
                "items": items,
                "score_filters": score_filters,
                "raw": data
            }
        except Exception as e:
            logger.error(f"get_review_list error ({url}): {e}")
            return {"status": "error", "message": str(e), "items": []}

    def get_review_paper_info(self, secid: str, mode: Optional[str] = None) -> Dict[str, Any]:
        """Load a previously graded paper for review / score modification (gethppaperinfo)."""
        use_mode = mode or self.current_mode or "normal"
        ep = "mark/task/getarbhppaperinfo" if use_mode == "arb" else "mark/task/gethppaperinfo"
        url = self.get_exam_url(ep)
        try:
            r = self.session.post(url, data={"secid": str(secid)}, timeout=15)
            text = self._decode_response(r).strip()
            data = json.loads(text)
            if isinstance(data, dict) and data.get("codeid") == "0001":
                data = self._enrich_task_metadata(data, queid=str(data.get("queid") or ""), mode=use_mode)
            return data
        except Exception as e:
            logger.error(f"get_review_paper_info error ({url}): {e}")
            return {"codeid": "-1", "message": str(e)}

    def get_monitor_progress(self, queid: str, subid: Optional[str] = None) -> Dict[str, Any]:
        """Fetch real-time teacher & group grading statistics (mark/monitor/monitorbyteacher)."""
        url = self.get_exam_url("mark/monitor/monitorbyteacher")
        payload = {
            "subid": str(subid or self.current_subid_num or ""),
            "queid": str(queid)
        }
        try:
            r = self.session.post(url, data=payload, timeout=10)
            text = self._decode_response(r).strip()
            return json.loads(text)
        except Exception as e:
            return {"codeid": "-1", "message": str(e)}

