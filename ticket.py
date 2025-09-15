#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Potala Palace WeChat Mini-Program Ticket Monitor (stateless, change-push & open-window watch)
- 仅 Server酱推送（有变化才推）
- 不做任何本地文件读写（无状态；仅进程内存缓存上次已推送状态）
- 控制台打印：每个监测日期下所有“有票”时间段及余票
- 若返回 {"code":0,"msg":"暂无数据","data":null} => 未到预约时间；根据“提前15天”规则计算开放日并等待开放，一旦开放立刻推送一次“已开放”，随后按变化才推
请求体: {"commodity_id": 1, "date": "YYYY-MM-DD"}
"""

import os
import time
import random
import datetime as dt
from typing import Any, Dict, List, Tuple, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
import logging 

# 如需用 .env 管理密钥，保留此行；若完全不读文件，可注释掉并用环境变量注入
load_dotenv(override=True)

# ====== 基本配置 ======
BASE_URL = "请你自己去抓包他的 URL "
HTTP_TIMEOUT = 10
MAX_RETRIES = 3

# 监控商品与日期
COMMODITY_IDS = [1]                      # 1：布达拉宫门票(示例)
TARGET_DATES = ["2025-10-01"]            # 可改为动态生成未来 N 天，例如：[(今天+1) ~ (今天+20)]

# 轮询周期（秒）与抖动（秒）
CHECK_INTERVAL_SEC = 60
JITTER_SEC = 10

# （可选）开放日前的“低频探测”周期（比如还没到 date-15 天时）
EARLY_CHECK_INTERVAL_SEC = 43200  # 12 小时；你也可以设成跟 CHECK_INTERVAL_SEC 一样

# Server酱（Turbo）密钥（必填，可用环境变量 SERVERCHAN_SENDKEY）
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "").strip()  # e.g. SCTxxxxxxxxxxxx

# 小程序 token（必填，可用环境变量 POTALA_TOKEN）
POTALA_TOKEN = os.getenv("POTALA_TOKEN", "").strip()

# ====== 日志配置 (新增) ======
LOG_FILE = "potala_monitor.log" # nohup 输出的日志文件名

def setup_logging():
    """配置日志记录器，同时输出到文件和控制台"""
    # 获取根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO) # 设置最低日志级别

    # 创建一个格式化器
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # 创建文件处理器，用于写入日志文件
    # 使用 utf-8 编码以支持中文字符
    file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
    file_handler.setFormatter(formatter)

    # 创建流处理器，用于在控制台输出
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    # 将处理器添加到根日志记录器
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def make_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=MAX_RETRIES,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    return s

def get_headers() -> Dict[str, str]:
    """每轮从环境变量读取 token，方便外部更新后无需重启（可配合 load_dotenv override）。"""
    token_env = os.getenv("POTALA_TOKEN", POTALA_TOKEN)
    return {
        "Host": "把你抓包的 host 填到这",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "xweb_xhr": "1",
        "platform": "wxMiniProgram",
        "site-id": "把你抓包的 site-id 填到这",
        "token": token_env or "",
        "version": "把你抓包的 version 填到这",
        "Accept": "*/*",
        "Referer": "把你抓包的 Referer 填到这",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

def notify_serverchan(title: str, content: str):
    if not SERVERCHAN_SENDKEY:
        return
    try:
        url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
        # Server酱支持 Markdown；这里用简单文本
        response = requests.post(url, data={"title": title, "desp": content}, timeout=HTTP_TIMEOUT)
        response.raise_for_status() # 如果请求失败则抛出异常
    except Exception as e:
        # 改为 logging.warning，这样不会中断程序，但会在日志中留下记录
        logging.warning(f"Server酱推送失败: {e}")


class FetchStatus:
    OK = "OK"              # 正常返回，可解析到 data(list)
    NOT_OPEN = "NOT_OPEN"  # 暂无数据 => 未到预约时间
    ERROR = "ERROR"        # 其他错误（含 Token 失效等）

def fetch_slots(sess: requests.Session, commodity_id: int, date_str: str) -> Tuple[str, Optional[List[Dict[str, Any]]], str]:
    """
    返回: (status, slots, msg)
      - status: OK / NOT_OPEN / ERROR
      - slots: 当 OK 时为列表，否则 None
      - msg: 接口返回的 msg 或异常信息
    """
    payload = {"commodity_id": commodity_id, "date": date_str}
    try:
        r = sess.post(BASE_URL, headers=get_headers(), json=payload, timeout=HTTP_TIMEOUT)
    except Exception as e:
        return FetchStatus.ERROR, None, f"网络异常: {e}"

    # 优先解析 JSON 看 msg，便于识别“暂无数据/请先登录”
    try:
        data = r.json()
    except Exception as e:
        try:
            r.raise_for_status()
        except Exception as e2:
            return FetchStatus.ERROR, None, f"HTTP异常: {e2}"
        return FetchStatus.ERROR, None, f"JSON解析异常: {e} | 响应内容: {r.text[:200]}"

    code = data.get("code")
    msg = str(data.get("msg", ""))
    if code == 1 and "data" in data and isinstance(data["data"], list):
        return FetchStatus.OK, data["data"], msg
    if code == 0 and "暂无数据" in msg:
        return FetchStatus.NOT_OPEN, None, msg

    # 可能是 token 失效或未登录提示
    if "登录" in msg or "请先登录" in msg or code == 0:
        return FetchStatus.ERROR, None, f"接口异常或token无效: {msg}"

    return FetchStatus.ERROR, None, f"未知返回: code={code}, msg={msg}"

def format_available_lines(slots: List[Dict[str, Any]]) -> List[str]:
    """只保留有票(time_interval_str + nums)。"""
    lines = []
    for s in slots:
        try:
            nums = int(str(s.get("nums", "0")).strip() or 0)
        except Exception:
            nums = 0
        if nums > 0:
            ti = s.get("time_interval_str") or s.get("time_interval")
            lines.append(f"{ti}：{nums} 张")
    return lines

def join_lines(lines: List[str]) -> str:
    """用于“变化检测”的可比对字符串（顺序保持）。"""
    return " | ".join(lines) if lines else ""

def compute_open_date(date_str: str) -> dt.date:
    """根据‘提前 15 天’规则计算开放日：open_date = target_date - 15 天（按日期，不含具体时刻）。"""
    target = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    return target - dt.timedelta(days=15)

def main():
    # 在 main 函数开始时配置日志
    setup_logging()
    
    sess = make_session()

    boot_msg = f"监控启动：路线{COMMODITY_IDS}, 日期={', '.join(TARGET_DATES)}, 监控周期={CHECK_INTERVAL_SEC}s±{JITTER_SEC}s"
    # 将 print 改为 logging.info
    logging.info(boot_msg)
    # notify_serverchan("布达拉宫余票监控启动", boot_msg)

    # 进程内存缓存：仅用于“已推送的上一次状态”
    # key: (cid, date) -> dict(status=..., payload=...)，
    #   其中 status ∈ {"NOT_OPEN","NO_STOCK","HAS_STOCK"}
    #   payload 对于 HAS_STOCK 存放已推送的字符串（有票时段串）
    last_pushed: Dict[Tuple[int, str], Dict[str, str]] = {}

    while True:
        now = dt.datetime.now()
        for cid in COMMODITY_IDS:
            for date_str in TARGET_DATES:
                key = (cid, date_str)
                open_date = compute_open_date(date_str)
                today = now.date()

                # 还没到开放日：低频探测（避免打扰），仅在日志中提示一次
                if today < open_date:
                    left_days = (open_date - today).days
                    # 将 print 改为 logging.info
                    logging.info(f"{date_str} (路线{cid}) 未到预约开放日({open_date})，剩余 {left_days} 天。进入低频探测。")
                    
                    st = last_pushed.get(key, {})
                    if st.get("status") != "NOT_OPEN":
                        last_pushed[key] = {"status": "NOT_OPEN", "payload": ""}
                    continue

                # 到了开放日及之后，开始正常调用接口
                status, slots, msg = fetch_slots(sess, cid, date_str)

                if status == FetchStatus.NOT_OPEN:
                    # 将 print 改为 logging.info
                    logging.info(f"{date_str} (路线{cid}) 仍显示未开放({msg})，继续高频检测直至开放。")
                    st = last_pushed.get(key, {})
                    if st.get("status") != "NOT_OPEN":
                        # notify_serverchan(f"布达拉宫 {date_str}（路线{cid}）",
                        #                   f"已到预约日（{open_date}）但仍显示未开放，系统将持续高频检测直至开放。")
                        last_pushed[key] = {"status": "NOT_OPEN", "payload": ""}
                    continue

                if status == FetchStatus.ERROR:
                    # 将 print 改为 logging.error
                    logging.error(f"获取失败: cid={cid} date={date_str} err={msg}")
                    # Token 无效时提醒一次
                    # if "token" in msg or "登录" in msg:
                        # notify_serverchan("布达拉宫监控：Token 可能失效", f"{date_str} 拉取失败：{msg}\n请更新 POTALA_TOKEN")
                    continue

                # 正常返回
                assert status == FetchStatus.OK and slots is not None
                lines = format_available_lines(slots)
                merged = join_lines(lines)
                st = last_pushed.get(key, {})

                if st.get("status") == "NOT_OPEN":
                    # notify_serverchan(f"布达拉宫 {date_str}（路线{cid}）预约已开放",
                    #                   "系统检测到接口已开放，后续仅在余票变化时推送。")
                    logging.info(f"{date_str} (路线{cid}) 预约已开放，开始监控余票变化。")

                if merged:
                    new_status = "HAS_STOCK"
                    printable = " | ".join(lines)
                    # 将 print 改为 logging.info
                    logging.info(f"{date_str} (路线{cid}) 有票时段: {printable}")
                else:
                    new_status = "NO_STOCK"
                    # 将 print 改为 logging.info
                    logging.info(f"{date_str} (路线{cid}) 暂无可售时段")

                prev_status = st.get("status")
                prev_payload = st.get("payload", "")
                changed = (new_status != prev_status) or (new_status == "HAS_STOCK" and merged != prev_payload)

                if changed:
                    if new_status == "HAS_STOCK":
                        notify_serverchan(
                            f"布达拉宫 {date_str} 有票更新（路线{cid}）",
                            "\n".join([f"- {ln}" for ln in lines])
                        )
                        last_pushed[key] = {"status": "HAS_STOCK", "payload": merged}
                    else:
                        # notify_serverchan(
                        #     f"布达拉宫 {date_str} 暂无可售（路线{cid}）",
                        #     "当前无可售时段；后续仅在余票变化时再推送。"
                        # )
                        last_pushed[key] = {"status": "NO_STOCK", "payload": ""}
                
                time.sleep(1 + random.random())

        # 周期休眠
        now = dt.datetime.now()
        any_in_open_window = any(now.date() >= compute_open_date(date_str) for date_str in TARGET_DATES)
        base_sleep = CHECK_INTERVAL_SEC if any_in_open_window else EARLY_CHECK_INTERVAL_SEC
        sleep_duration = base_sleep + random.randint(0, JITTER_SEC)
        logging.info(f"本轮监控结束，休眠 {sleep_duration} 秒...")
        time.sleep(sleep_duration)

if __name__ == "__main__":
    main()
