import feedparser
import requests
from datetime import datetime, timedelta
import pytz
import time
import os
from openai import OpenAI

# ================= 配置区 =================
PUSHPLUS_TOKEN = "be1dc2dfd430433b81ecc4893e93eb68"
AI_API_KEY = "sk-355db06057294ffb87021e501621e0a2"
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com") 
MODEL_NAME = "deepseek-chat"

# --- 多镜像备用站 ---
RSSHUB_MIRRORS = [
    "https://rsshub.rssforever.com",
    "https://rss.shab.fun",
    "https://rsshub.app" 
]

# --- 调高了各个权威媒体的抓取配额 ---
RSS_SOURCES = [
    {"name": "机器之心", "url": "/jiqizhixin/dailynews", "is_rsshub": True, "weight": 100, "max_items": 15},
    {"name": "量子位", "url": "/36kr/author/5330644", "is_rsshub": True, "weight": 100, "max_items": 12},
    {"name": "新智元", "url": "/36kr/author/5099383", "is_rsshub": True, "weight": 100, "max_items": 12},
    {"name": "InfoQ AI", "url": "/infoq/topic/33", "is_rsshub": True, "weight": 90, "max_items": 8},
    {"name": "晚点LatePost", "url": "/latepost/index", "is_rsshub": True, "weight": 90, "max_items": 5},
#    {"name": "Google新闻", "url": "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "is_rsshub": False, "weight": 10, "max_items": 5}
]

MAX_LINKS_TO_SHOW = 30   # 底部原始链接展示数量增加到 30 个
TIME_WINDOW_HOURS = 36   # 放宽到抓取过去 36 小时的新闻，避免周末没新闻
# =========================================

def fetch_feed_with_retry(source):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/115.0.0.0 Safari/537.36'
    }
    
    if not source['is_rsshub']:
        try:
            res = requests.get(source['url'], headers=headers, timeout=15)
            res.raise_for_status()
            return feedparser.parse(res.content)
        except Exception as e:
            print(f"[{source['name']}] 直连抓取失败: {e}")
            return None

    for mirror in RSSHUB_MIRRORS:
        full_url = mirror + source['url']
        try:
            res = requests.get(full_url, headers=headers, timeout=12)
            res.raise_for_status() 
            feed = feedparser.parse(res.content)
            if feed.entries:
                print(f"[{source['name']}] 成功通过节点 {mirror} 获取数据")
                return feed
        except Exception:
            continue 
            
    print(f"[{source['name']}] 所有镜像节点均抓取失败！")
    return None

def get_recent_ai_news():
    tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz)
    # 抓取时间放宽到36小时
    time_limit = now - timedelta(hours=TIME_WINDOW_HOURS)
    
    global_news_list = []
    
    for source in RSS_SOURCES:
        feed = fetch_feed_with_retry(source)
        if not feed:
            continue
            
        source_news = []
        for entry in feed.entries:
            if hasattr(entry, 'published_parsed'):
                pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), pytz.utc)
                pub_time = pub_time.astimezone(tz)
                
                if pub_time >= time_limit:
                    source_news.append({
                        'source': source['name'],
                        'weight': source['weight'],
                        'title': entry.title,
                        'link': entry.link,
                        'time': pub_time.strftime("%Y-%m-%d %H:%M"),
                        'timestamp': pub_time.timestamp()
                    })
        
        source_news.sort(key=lambda x: x['timestamp'], reverse=True)
        valid_items = source_news[:source['max_items']]
        global_news_list.extend(valid_items)
            
    global_news_list.sort(key=lambda x: (x['weight'], x['timestamp']), reverse=True)
    return global_news_list

def summarize_news_with_ai(news_list):
    if not AI_API_KEY:
        print("未配置 AI_API_KEY，跳过 AI 总结")
        return None

    news_text = "\n".join([f"- [{news['source']}] {news['title']}" for news in news_list])
    
    # 修改了 AI 的提示词，强制要求写 6-10 条，并且标题必须带来源
    prompt = f"""
    你是一个资深的 AI 科技媒体主编。请根据以下抓取的科技新闻，帮我写一份「每日 AI 晨报」。
    
    要求：
    1. 宁多勿少！必须充分利用素材，挑选出 6 到 10 件最重要的大事进行总结。
    2. 严格按照以下 Markdown 格式输出，资讯标题上【必须注明来源媒体】：
       🌟 **今日行业观察**
       （用一句话总结今天 AI 圈的整体趋势）
       
       🔥 **重要资讯速览**
       1. **[来源媒体] 新闻事件的核心标题**
          （在这里写1-2句简短有力的事件总结或洞察...）
       2. **[来源媒体] 新闻事件的核心标题**
          （在这里写1-2句简短有力的事件总结或洞察...）
       （请继续输出，保证至少有6条以上的内容）
       
       💡 **主编点评**
       （一句话犀利点评）

    以下是今天按优先级排序的新闻素材：
    {news_text}
    """

    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个专业的AI科技编辑，擅长信息提炼，绝不偷懒。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6 
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI 总结失败: {e}")
        return None

def send_wechat_notification(news_list, ai_summary):
    if not PUSHPLUS_TOKEN:
        print("未设置 PUSHPLUS_TOKEN，跳过推送")
        return

    if not news_list:
        content = "今日暂无新的AI资讯。"
    else:
        content = "### 🤖 你的专属 AI 晨报\n\n"
        
        if ai_summary:
            content += f"{ai_summary}\n\n---\n\n"
            content += "<details><summary>👉 点击展开今日精选原始链接</summary>\n\n"
        else:
            content += "*(AI 总结生成失败，以下为今日精选原始新闻)*\n\n"
            
        # 底部展示的链接数量提高到 30 个
        for i, news in enumerate(news_list[:MAX_LINKS_TO_SHOW], 1):
            content += f"{i}. **[{news['source']}]** [{news['title']}]({news['link']})\n"
            
        if len(news_list) > MAX_LINKS_TO_SHOW:
            content += f"\n*(为了阅读体验，已省略其余 {len(news_list) - MAX_LINKS_TO_SHOW} 条新闻)*\n"
        
        if ai_summary:
            content += "</details>\n"
            
    if len(content) > 18000:
        content = content[:18000] + "\n\n...（内容超长，已被系统截断）..."

    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": f"AI每日早报 {datetime.now().strftime('%Y-%m-%d')}",
        "content": content,
        "template": "markdown"
    }
    
    response = requests.post("http://www.pushplus.plus/send", json=payload)
    print("推送结果:", response.text)

if __name__ == "__main__":
    print("1. 开始从头部媒体抓取新闻...")
    recent_news = get_recent_ai_news()
    print(f"成功筛选出 {len(recent_news)} 条优质新闻用于分析。")
    
    source_counts = {}
    for n in recent_news:
        source_counts[n['source']] = source_counts.get(n['source'], 0) + 1
    print("喂给 AI 的新闻来源分布:", source_counts)
    
    ai_summary = None
    if recent_news:
        print("2. 开始调用 AI 进行主编级总结...")
        ai_summary = summarize_news_with_ai(recent_news)
        print("AI 总结完成！" if ai_summary else "AI 总结失败。")
        
    print("3. 开始推送到微信...")
    send_wechat_notification(recent_news, ai_summary)
    print("任务全部完成！")
