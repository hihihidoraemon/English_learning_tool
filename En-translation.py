import re
import requests
import streamlit as st
import urllib.parse
import json

# 设置页面配置（适配手机）
st.set_page_config(
    page_title="B站英文视频单词提取工具",
    page_icon="📝",
    layout="centered",  # 手机适配：居中布局
    initial_sidebar_state="collapsed"  # 默认收起侧边栏，适配手机
)

# ----------------------
# 配置项
# ----------------------
SIMPLE_WORDS = {"a", "an", "the", "and", "or", "but", "is", "are", "am", "was", "were", 
                "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", 
                "them", "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
                "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their",
                "have", "has", "had", "do", "does", "did", "will", "would", "can", "could",
                "may", "might", "shall", "should", "must", "so", "too", "very", "just", "only"}

# ----------------------
# 核心工具函数（纯云端API）
# ----------------------
def resolve_bilibili_short_url(short_url):
    """解析B站短链接"""
    try:
        if "b23.tv" in short_url:
            response = requests.head(short_url, allow_redirects=True, timeout=10)
            return response.url
        return short_url
    except Exception as e:
        st.warning(f"解析短链接失败：{str(e)}")
        return short_url

def get_bilibili_audio_url(video_url):
    """解析B站视频音频链接（纯API，无需下载）"""
    try:
        # 提取BV号
        bv_match = re.search(r"BV(\w+)", video_url)
        if not bv_match:
            return None, "未找到BV号，请检查链接格式"
        bv_id = bv_match.group(0)
        
        # B站公开API解析音频（无需登录）
        api_url = f"https://api.bilibili.com/x/player/playurl?bvid={bv_id}&cid=0&qn=16&fnval=16&fnver=0"
        headers = {
            "User-Agent": "Mozilla/5.0 (Mobile; Android 13; Pixel 7) AppleWebKit/537.36"
        }
        res = requests.get(api_url, headers=headers, timeout=10)
        data = res.json()
        
        if data.get("code") != 0:
            return None, f"B站API返回错误：{data.get('message', '未知错误')}"
        
        # 提取音频URL
        dash = data.get("data", {}).get("dash", {})
        audio_streams = dash.get("audio", [])
        if not audio_streams:
            return None, "该视频无独立音频流，无法提取"
        
        audio_url = audio_streams[0].get("baseUrl")
        # 补全音频URL的请求头（B站防盗链）
        audio_headers = {
            "User-Agent": headers["User-Agent"],
            "Referer": "https://www.bilibili.com/"
        }
        return (audio_url, audio_headers), None
    except Exception as e:
        return None, f"解析音频链接失败：{str(e)}"

def audio_url_to_text(audio_info):
    """云端语音转文字（使用免费API，替代Whisper+ffmpeg）"""
    audio_url, audio_headers = audio_info
    try:
        # 方案：使用OpenAI Whisper API（需自己申请API Key，免费额度够用）
        # 替换为你自己的OpenAI API Key（https://platform.openai.com/）
        OPENAI_API_KEY = st.secrets.get("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", "")
        if not OPENAI_API_KEY:
            st.warning("请先配置OpenAI API Key！")
            return None, "缺少OpenAI API Key"
        
        # 下载音频数据（临时）
        audio_res = requests.get(audio_url, headers=audio_headers, timeout=30)
        audio_res.raise_for_status()
        
        # 调用Whisper API转文字
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        files = {
            "file": ("audio.mp3", audio_res.content, "audio/mpeg"),
            "model": (None, "whisper-1"),
            "language": (None, "en")
        }
        res = requests.post(url, headers=headers, files=files, timeout=60)
        if res.status_code != 200:
            return None, f"转写失败：{res.text}"
        
        text = res.json().get("text", "")
        return text, None
    except Exception as e:
        return None, f"云端转写失败：{str(e)}"

def translate_text_to_zh(text):
    """云端翻译（纯Web API）"""
    try:
        text_encoded = urllib.parse.quote(text)
        url = f"https://fanyi.youdao.com/translate?doctype=json&type=EN2ZH_CN&i={text_encoded}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            translations = res.json()["translateResult"][0]
            zh_text = "".join([t["tgt"] for t in translations])
            return zh_text, None
        return "", "翻译接口调用失败"
    except Exception as e:
        return "", f"翻译出错：{str(e)}"

def extract_unique_words(text, filter_simple=True):
    """提取去重单词"""
    words = re.findall(r"[a-zA-Z]+", text.lower())
    unique_words = sorted(list(set(words)))
    if filter_simple:
        unique_words = [word for word in unique_words if word not in SIMPLE_WORDS and len(word) > 1]
    return unique_words

def get_word_definition(word):
    """词典API（纯Web）"""
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()[0]
            # 提取音标
            phonetics = data.get("phonetics", [])
            phonetic = ""
            for p in phonetics:
                if p.get("text") and "uk" in p.get("audio", "").lower():
                    phonetic = p["text"]
                    break
                elif p.get("text"):
                    phonetic = p["text"]
            # 提取释义
            meanings = data.get("meanings", [])
            if meanings:
                pos = meanings[0]["partOfSpeech"]
                definition = meanings[0]["definitions"][0]["definition"]
                example = meanings[0]["definitions"][0].get("example", "")
                return {
                    "phonetic": phonetic,
                    "definition": f"【{pos}】{definition}",
                    "example": f"例句：{example}" if example else ""
                }
            else:
                return {"phonetic": "", "definition": "无可用释义", "example": ""}
        else:
            return {"phonetic": "", "definition": "查询失败", "example": ""}
    except Exception as e:
        return {"phonetic": "", "definition": f"查询出错：{str(e)}", "example": ""}

def play_pronunciation_js(word):
    """播放读音（浏览器原生API，手机兼容）"""
    return f"""
    <script>
    const synth = window.speechSynthesis;
    const utterance = new SpeechSynthesisUtterance("{word}");
    utterance.lang = 'en-GB';
    // 手机兼容：延迟播放
    setTimeout(() => synth.speak(utterance), 100);
    </script>
    """

# ----------------------
# 页面UI（适配手机）
# ----------------------
st.title("📝 B站英文单词提取")
st.caption("手机端适配版 | 无需安装任何软件")

# 输入区（手机友好）
video_url = st.text_input(
    "B站视频链接",
    placeholder="粘贴b23.tv或BV开头链接",
    label_visibility="collapsed"
)
col1, col2 = st.columns(2)
with col1:
    filter_simple = st.checkbox("过滤简单词", value=True)
with col2:
    translate_switch = st.checkbox("翻译为中文", value=True)

submit_btn = st.button("开始提取", type="primary", use_container_width=True)

# 核心逻辑
if submit_btn and video_url:
    with st.spinner("解析视频链接..."):
        # 1. 解析短链接
        full_url = resolve_bilibili_short_url(video_url)
        # 2. 解析音频链接
        audio_info, error = get_bilibili_audio_url(full_url)
        if error:
            st.error(error)
            st.stop()
    
    with st.spinner("语音转文字中..."):
        # 3. 云端转写
        text, error = audio_url_to_text(audio_info)
        if error:
            st.error(error)
            st.stop()
        if not text:
            st.warning("未识别到任何文本")
            st.stop()
    
    # 4. 翻译（可选）
    zh_text = ""
    if translate_switch:
        with st.spinner("翻译中..."):
            zh_text, error = translate_text_to_zh(text)
            if error:
                st.warning(f"翻译提示：{error}")
    
    # 5. 提取单词
    with st.spinner("提取单词..."):
        unique_words = extract_unique_words(text, filter_simple)
        words_dict = {word: get_word_definition(word) for word in unique_words}
    
    # 显示结果（手机适配）
    st.divider()
    # 文本区（折叠面板，节省空间）
    with st.expander("📄 视频文本", expanded=True):
        tab1, tab2 = st.tabs(["🇬🇧 英文", "🇨🇳 中文"])
        with tab1:
            st.text_area("", text, height=150)  # 缩短高度，适配手机
        with tab2:
            st.text_area("", zh_text if zh_text else "无翻译结果", height=150)
    
    # 单词区（滚动显示）
    st.subheader(f"📚 单词列表（{len(unique_words)}个）")
    for word, desc in words_dict.items():
        # 手机适配：一行显示
        col_word, col_btn = st.columns([3, 1])
        with col_word:
            st.markdown(f"**{word}** {f'/ {desc["phonetic"]} /' if desc['phonetic'] else ''}")
        with col_btn:
            if st.button("🔊", key=word, use_container_width=True):
                st.components.v1.html(play_pronunciation_js(word), height=0)
        st.write(desc["definition"])
        if desc["example"]:
            st.caption(desc["example"])
        st.divider()
    
    # 导出功能（手机可下载）
    def export_words():
        content = ""
        for word, desc in words_dict.items():
            content += f"{word} {desc['phonetic']}\n{desc['definition']}\n{desc['example']}\n---\n"
        return content
    st.download_button(
        "📥 导出单词表",
        data=export_words(),
        file_name="bilibili_words.txt",
        mime="text/plain",
        use_container_width=True
    )

elif submit_btn and not video_url:
    st.warning("请输入B站视频链接！")

# 底部说明（手机适配）
st.divider()
st.caption("💡 说明：1. 仅支持公开英文视频；2. 转写依赖OpenAI API；3. 手机端建议横屏使用")
