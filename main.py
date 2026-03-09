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

# --- 核心升级 1：RSSHub 多镜像备用站（防官方节点限流报错） ---
RSSHUB_MIRRORS = [
    "https://rsshub.rssforever.com",
    "https://rss.shab.fun",
    "https://rsshub.app" # 官方放最后作为兜底
]

# --- 核心升级 2：强制配额与极度倾斜的权重 ---
# max_items: 强行限制该媒体最多入选几篇新闻（防止某一家霸榜）
RSS_SOURCES = [
    {"name": "机器之心", "url": "/jiqizhixin/dailynews", "is_rsshub": True, "weight": 100, "max_items": 10},
    {"name": "量子位", "url": "/36kr/author/5330644", "is_rsshub": True, "weight": 100, "max_items": 8},
    {"name": "新智元", "url": "/36kr/author/5099383", "is_rsshub": True, "weight": 100, "max_items": 8},
    {"name": "InfoQ AI", "url": "/infoq/topic/33", "is_rsshub": True, "weight": 90, "max_items": 5},
    {"name": "晚点LatePost", "url": "/latepost/index", "is_rsshub": True, "weight": 90, "max_items": 3},
    # 彻底打入冷宫的 Google 新闻，只允许它提供最多 3 条作为补充，权重最低
    {"name": "Google新闻", "url": "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "is_rsshub": False, "weight": 10, "max_items": 3}
]

MAX_LINKS_TO_SHOW = 15   # 微信底部最多附带多少个原始链接
# =========================================

def fetch_feed_with_retry(source):
    """带重试机制的抓取逻辑"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    # 如果是 Google 新闻这类直连网址
    if not source['is_rsshub']:
        try:
            res = requests.get(source['url'], headers=headers, timeout=15)
            res.raise_for_status()
            return feedparser.parse(res.content)
        except Exception as e:
            print(f"[{source['name']}] 直连抓取失败: {e}")
            return None

    # 如果是 RSSHub，循环尝试多个镜像站
    for mirror in RSSHUB_MIRRORS:
        full_url = mirror + source['url']
        try:
            res = requests.get(full_url, headers=headers, timeout=12)
            res.raise_for_status() # 检查 403 / 500 报错
            feed = feedparser.parse(res.content)
            # 如果成功解析且有数据，立即返回
            if feed.entries:
                print(f"[{source['name']}] 成功通过节点 {mirror} 获取数据")
                return feed
        except Exception:
            continue # 当前节点失败，静默尝试下一个节点
            
    print(f"[{source['name']}] 所有镜像节点均抓取失败！")
    return None

def get_recent_ai_news():
    tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz)
    one_day_ago = now - timedelta(days=1)
    
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
                
                if pub_time >= one_day_ago:
                    source_news.append({
                        'source': source['name'],
                        'weight': source['weight'],
                        'title': entry.title,
                        'link': entry.link,
                        'time': pub_time.strftime("%Y-%m-%d %H:%M"),
                        'timestamp': pub_time.timestamp()
                    })
        
        # 针对单一媒体的新闻按时间排序，并截取最大配额
        source_news.sort(key=lambda x: x['timestamp'], reverse=True)
        valid_items = source_news[:source['max_items']]
        global_news_list.extend(valid_items)
        print(f"[{source['name']}] 最终采纳 {len(valid_items)} 条最新资讯。")
            
    # 【全局终极排序】：按照 权重第一，时间第二 的逻辑排序
    global_news_list.sort(key=lambda x: (x['weight'], x['timestamp']), reverse=True)
    return global_news_list

def summarize_news_with_ai(news_list):
    if not AI_API_KEY:
        print("未配置 AI_API_KEY，跳过 AI 总结")
        return None

    news_text = "\n".join([f"- [{news['source']}] {news['title']}" for news in news_list])
    
    prompt = f"""
    你是一个资深的 AI 科技媒体主编。请根据以下过去 24 小时内抓取的科技新闻，帮我写一份「每日 AI 晨报」。
    
    注意：我为你提供的素材已经经过了优先级排序，排在前面的【机器之心】、【量子位】、【新智元】等是最高优先级的权威报道。
    
    要求：
    1. 必须优先从【机器之心】、【量子位】、【新智元】等权威来源中挑选 3-5 件最重要的大事进行详细总结。
    2. 【Google新闻】和【晚点】的内容仅作边缘补充，如果前面权威源的新闻已经足够好，可以直接忽略 Google 新闻。
    3. 严格按照以下 Markdown 格式输出：
       🌟 **今日行业观察**
       （用一句话总结今天 AI 圈的整体趋势）
       
       🔥 **重要资讯速览**
       1. **[关键词]** 新闻事件总结...（必须标明消息来源，如：据机器之心报道...）
       2. **[关键词]** 新闻事件总结...
       3. **[关键词]** 新闻事件总结...
       
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
                {"role": "system", "content": "你是一个专业的AI科技编辑，具备敏锐的商业与技术洞察力。"},
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
    
    # 调试日志：打印入选的各大媒体新闻数量，让你在 GitHub 清楚看到分配情况
    source_counts = {}
    for n in recent_news:
        source_counts[n['source']] = source_counts.get(n['source'], 0) + 1
    print("最终喂给 AI 的新闻来源分布:", source_counts)
    
    ai_summary = None
    if recent_news:
        print("2. 开始调用 AI 进行主编级总结...")
        ai_summary = summarize_news_with_ai(recent_news)
        print("AI 总结完成！" if ai_summary else "AI 总结失败。")
        
    print("3. 开始推送到微信...")
    send_wechat_notification(recent_news, ai_summary)
    print("任务全部完成！")
