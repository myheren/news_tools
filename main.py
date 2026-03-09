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

# DeepSeek 的接口地址，如果你用 OpenAI，可以删掉或改为 https://api.openai.com/v1
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com") 
MODEL_NAME = "deepseek-reasoner" # 如果用别的模型，这里对应修改，例如 gpt-3.5-turbo

RSS_URLS = [
    "https://news.google.com/rss/search?q=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://rsshub.app/jiqizhixin/dailynews"
]
# =========================================

def get_recent_ai_news():
    """抓取过去24小时的新闻"""
    tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz)
    one_day_ago = now - timedelta(days=1)
    
    news_list = []
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if hasattr(entry, 'published_parsed'):
                    pub_time = datetime.fromtimestamp(time.mktime(entry.published_parsed), pytz.utc)
                    pub_time = pub_time.astimezone(tz)
                    
                    if pub_time >= one_day_ago:
                        news_list.append({
                            'title': entry.title,
                            'link': entry.link,
                            'time': pub_time.strftime("%Y-%m-%d %H:%M")
                        })
        except Exception as e:
            print(f"抓取 {url} 失败: {e}")
            
    return news_list

def summarize_news_with_ai(news_list):
    """调用大模型进行总结"""
    if not AI_API_KEY:
        print("未配置 AI_API_KEY，跳过 AI 总结")
        return None

    # 将新闻标题提取出来给 AI
    news_titles = "\n".join([f"- {news['title']}" for news in news_list])
    
    prompt = f"""
    你是一个资深的 AI 科技媒体主编。请根据以下过去 24 小时内抓取的 AI 领域新闻标题，帮我写一份「每日 AI 晨报」。
    
    要求：
    1. 剔除重复的、无聊的、价值不大的新闻，只挑选 3-5 件最重要的大事。
    2. 用通俗、凝练的语言总结，最好带有一定的洞察。
    3. 严格按照以下 Markdown 格式输出：
       🌟 **今日行业观察**
       （用一句话总结今天 AI 圈的整体趋势或大新闻）
       
       🔥 **重要资讯速览**
       1. **[关键词]** 新闻事件总结...
       2. **[关键词]** 新闻事件总结...
       3. **[关键词]** 新闻事件总结...
       
       💡 **编辑点评**
       （一句话简短的感受或吐槽）

    以下是今天抓取到的新闻素材：
    {news_titles}
    """

    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个专业的AI科技编辑。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7 # 调整创造力，0.7比较适合兼顾准确与生动
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI 总结失败: {e}")
        return None

def send_wechat_notification(news_list, ai_summary):
    """推送微信消息"""
    if not PUSHPLUS_TOKEN:
        print("未设置 PUSHPLUS_TOKEN，跳过推送")
        return

    if not news_list:
        content = "今日暂无新的AI资讯。"
    else:
        content = "### 🤖 你的每日 AI 晨报\n\n"
        
        # 如果 AI 总结成功，放在最前面
        if ai_summary:
            content += f"{ai_summary}\n\n---\n\n"
            content += "<details><summary>👉 点击查看今日原始新闻链接</summary>\n\n"
        else:
            content += "*(AI 总结生成失败，以下为今日原始新闻)*\n\n"
            
        # 附上所有的原始新闻链接
        for i, news in enumerate(news_list, 1):
            content += f"{i}. [{news['title']}]({news['link']})\n"
        
        if ai_summary:
            content += "</details>\n"
            
    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": f"AI每日早报 {datetime.now().strftime('%Y-%m-%d')}",
        "content": content,
        "template": "markdown"
    }
    
    response = requests.post("http://www.pushplus.plus/send", json=payload)
    print("推送结果:", response.text)

if __name__ == "__main__":
    print("1. 开始抓取AI新闻...")
    recent_news = get_recent_ai_news()
    print(f"共抓取到 {len(recent_news)} 条新闻。")
    
    ai_summary = None
    if recent_news:
        print("2. 开始调用 AI 进行总结...")
        ai_summary = summarize_news_with_ai(recent_news)
        print("AI 总结完成！" if ai_summary else "AI 总结失败。")
        
    print("3. 开始推送到微信...")
    send_wechat_notification(recent_news, ai_summary)
    print("任务全部完成！")
