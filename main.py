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

# --- 新增：带权重的新闻源配置 ---
# weight 越高，优先级越高。这样可以确保截断时保留的都是优质媒体的新闻
RSS_SOURCES = [
    {"name": "机器之心", "url": "https://rsshub.app/jiqizhixin/dailynews", "weight": 100},
    {"name": "量子位", "url": "https://rsshub.app/36kr/author/5330644", "weight": 100},
    {"name": "新智元", "url": "https://rsshub.app/36kr/author/5099383", "weight": 100},
    {"name": "InfoQ", "url": "https://rsshub.app/infoq/topic/33", "weight": 100}, # InfoQ AI前线
    {"name": "晚点LatePost", "url": "https://rsshub.app/latepost/index", "weight": 100},
    # 泛新闻作为补充，权重调低
    {"name": "Google新闻", "url": "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", "weight": 50}
]

MAX_NEWS_FOR_AI = 40     # 最多喂给大模型多少条新闻
MAX_LINKS_TO_SHOW = 15   # 微信底部最多附带多少个原始链接
# =========================================

def get_recent_ai_news():
    tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz)
    one_day_ago = now - timedelta(days=1)
    
    news_list = []
    
    # 模拟浏览器请求头，防止被反爬虫拦截
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    for source in RSS_SOURCES:
        try:
            # 先用 requests 获取内容（带超时），避免 feedparser 直接请求卡死
            response = requests.get(source['url'], headers=headers, timeout=12)
            feed = feedparser.parse(response.content)
            
            valid_count = 0
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), pytz.utc)
                    pub_time = pub_time.astimezone(tz)
                    
                    if pub_time >= one_day_ago:
                        news_list.append({
                            'source': source['name'],
                            'weight': source['weight'],
                            'title': entry.title,
                            'link': entry.link,
                            'time': pub_time.strftime("%Y-%m-%d %H:%M"),
                            'timestamp': pub_time.timestamp() # 用于精确排序
                        })
                        valid_count += 1
            print(f"[{source['name']}] 成功抓取 {valid_count} 条24h内新闻")
            
        except requests.exceptions.Timeout:
            print(f"抓取超时跳过: {source['name']}")
        except Exception as e:
            print(f"抓取失败: {source['name']} - {e}")
            
    # 【核心排序逻辑】：第一优先级是媒体权重(从大到小)，第二优先级是发布时间(从新到旧)
    news_list.sort(key=lambda x: (x['weight'], x['timestamp']), reverse=True)
    
    return news_list[:MAX_NEWS_FOR_AI]

def summarize_news_with_ai(news_list):
    if not AI_API_KEY:
        print("未配置 AI_API_KEY，跳过 AI 总结")
        return None

    # 将新闻标题和来源一起喂给大模型，让大模型知道这是权威媒体发出的
    news_text = "\n".join([f"- [{news['source']}] {news['title']}" for news in news_list])
    
    prompt = f"""
    你是一个资深的 AI 科技媒体主编。请根据以下过去 24 小时内抓取的科技新闻，帮我写一份「每日 AI 晨报」。
    
    要求：
    1. 重点关注 AI 大模型、科技巨头动态、前沿技术。如果遇到《晚点LatePost》等泛商业媒体的内容，请只提取与“科技/AI”相关的部分，忽略纯电商或娱乐八卦。
    2. 剔除重复的、无聊的新闻，从这些顶尖媒体的报道中，只挑选 3-5 件最重要的大事。
    3. 严格按照以下 Markdown 格式输出：
       🌟 **今日行业观察**
       （用一句话总结今天 AI 圈的整体趋势）
       
       🔥 **重要资讯速览**
       1. **[关键词]** 新闻事件总结...（可标明消息来源，如：据机器之心报道...）
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
            temperature=0.6 # 调低了一点温度，让新闻总结更严谨客观
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
            
        # 底部链接展示也会带上媒体来源的标签
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
    
    ai_summary = None
    if recent_news:
        print("2. 开始调用 AI 进行主编级总结...")
        ai_summary = summarize_news_with_ai(recent_news)
        print("AI 总结完成！" if ai_summary else "AI 总结失败。")
        
    print("3. 开始推送到微信...")
    send_wechat_notification(recent_news, ai_summary)
    print("任务全部完成！")
