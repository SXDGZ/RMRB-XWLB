#!/usr/bin/env python3
"""
每日新闻自动采集 + AI总结 + QQ推送
支持：新闻联播 + 人民日报
运行方式：直接执行 python news_summary.py

数据来源：
- 新闻联播：央视网栏目页 (https://tv.cctv.com/lm/xwlb/)
- 人民日报：中新经纬快报 (https://www.jwview.com) + 人民网首页
"""

# 解决Windows控制台GBK编码问题
import sys
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
import json
import re
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from typing import Optional

# ============================================================
# 配置区（所有敏感信息从环境变量读取）
# ============================================================
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/anthropic")
LLM_MODEL = os.environ.get("LLM_MODEL", "DeepSeek-V4-Flash")
QMSG_KEY = os.environ.get("QMSG_KEY", "")          # Qmsg酱的KEY
QQ_RECEIVER = os.environ.get("QQ_RECEIVER", "")     # 接收消息的QQ号

# 邮箱推送配置（推荐，无关键词限制）
SMTP_USER = os.environ.get("SMTP_USER", "")          # QQ邮箱地址，如 2802492961@qq.com
SMTP_PASS = os.environ.get("SMTP_PASS", "")          # QQ邮箱SMTP授权码（不是QQ密码！）
SMTP_TO = os.environ.get("SMTP_TO", "")              # 接收邮件的邮箱（默认同发件人）

# 目标日期（默认昨天，可被覆盖用于测试）
TARGET_DATE = os.environ.get("TARGET_DATE", None)  # 格式: YYYY-MM-DD

def get_target_date():
    if TARGET_DATE:
        return datetime.strptime(TARGET_DATE, "%Y-%m-%d")
    return datetime.now() - timedelta(days=1)


# ============================================================
# 第一部分：新闻采集 - 通用工具
# ============================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def fetch_url(url: str, timeout: int = 20, encoding: str = "utf-8") -> Optional[str]:
    """安全地获取URL内容"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None
        resp.encoding = encoding
        return resp.text
    except Exception as e:
        print(f"  [WARN] 请求失败: {url} - {e}")
        return None


def extract_text_between(html: str, prefix: str, suffix: str) -> Optional[str]:
    """提取两个标记之间的文本"""
    idx = html.find(prefix)
    if idx == -1:
        return None
    start = idx + len(prefix)
    end = html.find(suffix, start)
    if end == -1:
        return None
    return html[start:end].strip()


# ============================================================
# 新闻联播采集（来源：央视网栏目页）
# ============================================================

def fetch_xinwen_lianbo_from_cctv() -> Optional[list]:
    """
    从央视网栏目页获取新闻联播条目
    页面结构：<li>完整版[视频]新闻标题</li>
    """
    print("[新闻联播] 从央视网栏目页获取...")
    html = fetch_url("https://tv.cctv.com/lm/xwlb/")
    if not html:
        return None

    items = []
    # 提取所有 <li> 内容
    for match in re.finditer(r'<li[^>]*>(.*?)</li>', html, re.DOTALL):
        text = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        # 只取包含 "完整版" 的条目（新闻标题）
        if '完整版' in text:
            # 去掉前缀 "完整版[视频]" 或 "完整版《新闻联播》日期"
            clean = re.sub(
                r'^完整版(\[视频\]|《[^》]*》\s*\d+\s*)?',
                '', text
            ).strip()
            if clean and len(clean) > 5:
                items.append(clean)

    # 过滤掉导航文字
    skip_words = ['微信', '扫码', '小程序', '首页', '栏目', '播出信息', '热门', '朝闻天下', '今日说法']
    valid = [i for i in items if not any(kw in i for kw in skip_words)]

    # 去重
    seen = set()
    unique = []
    for item in valid:
        if item not in seen:
            seen.add(item)
            unique.append(item)

    if len(unique) >= 3:
        print(f"  ✓ 获取到 {len(unique)} 条")
        return unique
    return None


# ============================================================
# 人民日报采集（来源：中新经纬 + 人民网）
# ============================================================

def fetch_people_daily_from_jwview(date_obj: datetime) -> Optional[list]:
    """
    从中新经纬 (jwview.com) 获取"人民日报头版主要内容"
    通过尝试多个可能的文章ID来定位目标文章
    """
    month_day = date_obj.strftime("%m-%d")
    print(f"[人民日报] 从中新经纬获取 ({month_day})...")

    # 已知的文章ID映射（用于定位和推算）
    # 2026-07-03 -> 234884
    # 2026-07-04 -> 234942
    base_date = datetime(2026, 7, 3)
    base_id = 234884
    known_date = datetime(2026, 7, 4)
    known_id = 234942

    # 推算目标日期的近似ID
    if base_date <= date_obj <= known_date:
        # 在已知范围内线性推算
        days_diff = (date_obj - base_date).days
        approx_id = base_id + days_diff * 58
    elif date_obj > known_date:
        days_from_known = (date_obj - known_date).days
        approx_id = known_id + days_from_known * 55
    else:
        approx_id = base_id

    # 在近似ID附近尝试（前后各20个）
    search_range = list(range(approx_id - 20, approx_id + 21))
    found = None
    found_text = None

    for try_id in search_range:
        url = f"https://www.jwview.com/jingwei/kb/pc/{month_day}/{try_id}.shtml"
        html = fetch_url(url, timeout=10, encoding="gb2312")
        if html and '人民日报头版主要内容' in html:
            # 提取正文内容
            body = extract_text_between(html, '人民日报头版主要内容', '中新经纬版权所有')
            if body:
                found_text = f"【人民日报头版主要内容】\n{body.strip()}"
                found = try_id
                print(f"  ✓ 找到文章: ID={try_id}")
                break

    if found_text:
        # 解析成条目列表
        items = []
        for line in found_text.split('；'):
            line = re.sub(r'^\d+[、.．]', '', line).strip()
            if line and len(line) > 5:
                items.append(line)
        # 也尝试按换行和序号拆分
        if len(items) <= 2:
            items = re.findall(r'\d+[、.．]([^；;]+)', found_text)
            items = [i.strip() for i in items if len(i.strip()) > 5]
        return items if items else None

    return None


def fetch_people_daily_from_peoplecom() -> Optional[list]:
    """
    从人民网 (www.people.com.cn) 首页提取当日重要新闻
    """
    print("[人民日报] 从人民网首页获取...")
    html = fetch_url("http://www.people.com.cn/")
    if not html:
        return None

    items = []
    seen_texts = set()
    for match in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>([^<]{12,})</a>', html):
        text = re.sub(r'\s+', '', match.group(2)).strip()
        if text in seen_texts or len(text) < 10:
            continue
        seen_texts.add(text)

        # 要闻关键词（匹配到任一即保留）
        keep_keywords = [
            '习近平', '总理', '国务院', '全国人大', '全国政协', '中纪委',
            '重要讲话', '召开', '举行', '发布', '印发', '部署',
            '人民日报', '头版', '评论员', '人民论坛',
            '外交', '会谈', '访华', '会见',
            '经济', '发展', '改革', '建设', '高质量',
            '科技', '创新', '航天', '高铁',
            '防汛', '救灾', '应急', '台风',
            '国际', '联合国', '一带一路',
            '七一', '建党', '党员',
        ]
        skip_keywords = [
            '广告', 'cookie', '登录', '注册', '协议', '隐私',
            '免责', '招聘', '举报', '视频', '直播', '专题',
            '问卷', '调查', '意见', '征集', '网友',
            '人民网', '网站', 'English', '日本語',
            '健康', '娱乐', '体育', '时尚', '游戏',
        ]

        if any(kw in text for kw in keep_keywords) \
           and not any(kw in text for kw in skip_keywords):
            items.append(text)

    # 去重（基于前30字符去重）
    unique = []
    seen_prefix = set()
    for item in items:
        prefix = item[:30]
        if prefix not in seen_prefix:
            seen_prefix.add(prefix)
            unique.append(item)

    if len(unique) >= 3:
        print(f"  ✓ 从人民网获取到 {len(unique)} 条")
        return unique[:25]
    return None


def fetch_people_daily() -> Optional[list]:
    """采集人民日报（多源fallback）"""
    date_obj = get_target_date()
    # 先尝试 jwview（内容最完整）
    result = fetch_people_daily_from_jwview(date_obj)
    if result:
        return result
    # 降级到人民网首页
    result = fetch_people_daily_from_peoplecom()
    if result:
        return result
    return None


# ============================================================
# 新闻联播入口（多源fallback）
# ============================================================

def fetch_xinwen_lianbo() -> Optional[list]:
    """采集新闻联播"""
    result = fetch_xinwen_lianbo_from_cctv()
    if result:
        return result
    return None


# ============================================================
# 第二部分：AI总结
# ============================================================

def build_prompt(xwlb_items: list, rmrb_items: list, date_str: str) -> str:
    """构造AI总结的提示词"""

    xwlb_text = "\n".join(f"{i+1}. {item}" for i, item in enumerate(xwlb_items))
    rmrb_text = "\n".join(f"{i+1}. {item}" for i, item in enumerate(rmrb_items[:20]))

    return f"""你是一位资深的时政新闻分析师。请根据以下素材，生成一份结构化、有深度的新闻解读。

素材来源：
1. 央视《新闻联播》{date_str} 内容提要
2. 《人民日报》{date_str} 头版及重要新闻

--- 新闻联播内容 ---
{xwlb_text}

--- 人民日报内容 ---
{rmrb_text}

请按以下格式生成解读报告：

【今日头条】
- 指出今天最重要的1-2条新闻，点明意义

【要闻速览】
- 用表格或分点列出所有重要新闻（按政治、经济、外交、社会科技分类）

【深度解读】
- 选取2-3个最值得关注的话题，提供背景分析和趋势判断
- 指出新闻联播和人民日报的重合点

【国际视野】
- 重要国际新闻及评论

【一句话总结】
- 用一句话概括今天新闻的核心主线

要求：专业但不晦涩，有观点有依据，每条分析后标注来源（新闻联播/人民日报）"""


def call_llm(prompt: str) -> Optional[str]:
    """调用兼容Anthropic格式的LLM API"""
    if not LLM_API_KEY:
        print("[LLM] 未配置API KEY，跳过AI总结")
        return None

    url = f"{LLM_BASE_URL.rstrip('/')}/v1/messages"
    payload = {
        "model": LLM_MODEL,
        "max_tokens": 4000,
        "temperature": 0.3,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    print(f"[LLM] 正在调用 {LLM_MODEL} 生成总结...")
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120
        )
        resp.raise_for_status()
        data = resp.json()
        for block in data.get("content", []):
            if block.get("type") == "text":
                return block["text"]
        return data.get("content", [{}])[0].get("text", "")
    except Exception as e:
        print(f"  [ERROR] LLM调用失败: {e}")
        if hasattr(e, 'response') and e.response:
            print(f"  RESPONSE: {e.response.text[:500]}")
        return None


# ============================================================
# 第三部分：推送（邮箱优先 + Qmsg酱备用）
# ============================================================

def send_email(message: str, title: str = "每日新闻解读") -> bool:
    """通过QQ邮箱SMTP发送（无关键词限制，推荐）"""
    sender = SMTP_USER or f"{QQ_RECEIVER}@qq.com"
    to_addr = SMTP_TO or sender
    password = SMTP_PASS

    if not password:
        print("[邮箱] 未配置SMTP_PASS，跳过邮箱推送")
        return False

    print(f"[邮箱] 正在发送至 {to_addr}...")
    try:
        # 构建邮件（HTML格式，更美观）
        body_html = message.replace("\n", "<br>")
        body_html = re.sub(r'【([^】]+)】', r'<h3>\1</h3>', body_html)
        body_html = f"""
        <html>
        <head><meta charset="utf-8"><style>
            body {{ font-family: "Microsoft YaHei", sans-serif; padding: 20px; }}
            h3 {{ color: #c0392b; border-bottom: 2px solid #eee; padding-bottom: 5px; }}
            h2 {{ color: #c0392b; }}
            hr {{ border: none; border-top: 1px solid #eee; }}
        </style></head>
        <body>{body_html}</body></html>
        """

        msg = MIMEText(body_html, "html", "utf-8")
        msg["Subject"] = title
        msg["From"] = sender
        msg["To"] = to_addr

        # QQ邮箱SMTP: smtp.qq.com 端口465(SSL)
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30) as server:
            server.login(sender, password)
            server.sendmail(sender, [to_addr], msg.as_string())

        print(f"  ✓ 邮件推送成功！请检查 {to_addr}")
        return True
    except smtplib.SMTPAuthenticationError:
        print(f"  [ERROR] SMTP登录失败：请检查授权码是否正确")
        print(f"  [提示] QQ邮箱 → 设置 → 账户 → 开启SMTP服务 → 生成授权码")
        return False
    except smtplib.SMTPException as e:
        print(f"  [ERROR] SMTP发送失败: {e}")
        return False
    except Exception as e:
        print(f"  [ERROR] 邮件发送异常: {e}")
        return False


def send_to_qq(message: str, title: str = "每日新闻解读") -> bool:
    """通过Qmsg酱发送消息到QQ"""
    if not QMSG_KEY:
        print("[QQ] 未配置QMSG_KEY，跳过推送")
        return False

    url = f"https://qmsg.zendee.cn/send/{QMSG_KEY}"
    full_msg = f"📰 {title}\n{'='*25}\n\n{message}"

    # Qmsg酱单条限制约4000字符，超长则分段
    max_len = 3500
    if len(full_msg) > max_len:
        parts = []
        current = ""
        for line in full_msg.split("\n"):
            if len(current) + len(line) + 1 > max_len:
                parts.append(current)
                current = line
            else:
                current += "\n" + line if current else line
        if current:
            parts.append(current)

        success = True
        for i, part in enumerate(parts):
            part_title = f"{title} ({i+1}/{len(parts)})"
            try:
                resp = requests.post(url, data={"msg": f"📰 {part_title}\n{'='*25}\n\n{part}"}, timeout=15)
                result = resp.json()
                if result.get("code") != 0:
                    print(f"  [WARN] 第{i+1}段推送失败: {result}")
                    success = False
                else:
                    print(f"  ✓ 第{i+1}/{len(parts)}段已发送")
            except Exception as e:
                print(f"  [ERROR] 第{i+1}段推送异常: {e}")
                success = False
        return success
    else:
        try:
            resp = requests.post(url, data={"msg": full_msg}, timeout=15)
            result = resp.json()
            if result.get("code") == 0:
                print("  ✓ QQ消息推送成功")
                return True
            else:
                print(f"  [WARN] QQ推送返回异常: {result}")
                return False
        except Exception as e:
            print(f"  [ERROR] QQ推送失败: {e}")
            return False


# ============================================================
# 第四部分：主流程
# ============================================================

def main():
    date_obj = get_target_date()
    date_str = date_obj.strftime("%Y年%m月%d日")
    date_ymd = date_obj.strftime("%Y%m%d")

    print(f"\n{'='*50}")
    print(f"  每日新闻采集 + AI总结 + QQ推送")
    print(f"  日期：{date_str}")
    print(f"{'='*50}\n")

    # ---- 步骤1：采集新闻联播 ----
    print("【1/4】采集新闻联播...")
    xwlb = fetch_xinwen_lianbo()
    if not xwlb:
        print("  ⚠ 未获取到新闻联播内容，使用占位信息")
        xwlb = ["（当日新闻联播内容获取失败）"]
    else:
        for i, item in enumerate(xwlb, 1):
            print(f"  {i}. {item[:60]}{'...' if len(item) > 60 else ''}")
    print(f"  → 共 {len(xwlb)} 条\n")

    # ---- 步骤2：采集人民日报 ----
    print("【2/4】采集人民日报...")
    rmrb = fetch_people_daily()
    if not rmrb:
        print("  ⚠ 未获取到人民日报内容，使用占位信息")
        rmrb = ["（当日人民日报内容获取失败）"]
    else:
        for i, item in enumerate(rmrb[:10], 1):
            print(f"  {i}. {item[:60]}{'...' if len(item) > 60 else ''}")
        if len(rmrb) > 10:
            print(f"  ... 共 {len(rmrb)} 条")
    print(f"  → 共 {len(rmrb)} 条\n")

    # ---- 步骤3：AI总结 ----
    print("【3/4】AI深度总结...")
    prompt = build_prompt(xwlb, rmrb, date_str)
    summary = call_llm(prompt)
    if not summary:
        print("  ⚠ AI总结失败，使用原始素材")
        summary = "【新闻联播 " + date_str + "】\n" + "\n".join(f"- {i}" for i in xwlb)
        summary += "\n\n【人民日报 " + date_str + "】\n" + "\n".join(f"- {i}" for i in rmrb[:10])
    print(f"  → 总结完成（{len(summary)}字符）\n")

    # 保存到本地文件
    output_file = f"news_{date_ymd}.md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"  → 已保存至 {output_file}")

    # ---- 步骤4：推送（邮箱优先，Qmsg酱备用） ----
    print("【4/4】推送消息...")
    title = f"新闻解读 {date_obj.strftime('%Y.%m.%d')}"

    # 方式A：邮箱推送（推荐，无关键词限制）
    email_ok = send_email(summary, title)

    # 方式B：Qmsg酱辅助推送（如果能用的话）
    qq_ok = send_to_qq(summary, title)

    if email_ok or qq_ok:
        print(f"\n{'='*50}")
        print(f"  ✅ 全部完成！新闻解读已推送（邮箱={'✓' if email_ok else '✗'} QQ={'✓' if qq_ok else '✗'}）")
        print(f"{'='*50}\n")
    else:
        print(f"\n{'='*50}")
        print(f"  ⚠ 所有推送方式均失败，请检查配置")
        print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
