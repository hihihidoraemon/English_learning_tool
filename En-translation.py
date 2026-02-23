import re
import requests
import json
import os
import whisper
import streamlit as st
from pathlib import Path
import shutil
import subprocess
import urllib.parse

# 设置页面配置
st.set_page_config(
    page_title="B站英文视频单词提取工具",
    page_icon="📝",
    layout="wide"
)

# ----------------------
# 配置项
# ----------------------
# 简单词列表（可自行修改）
SIMPLE_WORDS = {"a", "an", "the", "and", "or", "but", "is", "are", "am", "was", "were", 
                "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", 
                "them", "in", "on", "at", "to", "for", "of", "with", "by", "from", "as",
                "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their",
                "have", "has", "had", "do", "does", "did", "will", "would", "can", "could",
                "may", "might", "shall", "should", "must", "so", "too", "very", "just", "only"}

# ----------------------
# 工具函数
# ----------------------
def clean_audio_dir():
    """清理音频目录"""
    if os.path.exists("audio"):
        shutil.rmtree("audio")
    os.makedirs("audio", exist_ok=True)

def resolve_bilibili_short_url(short_url):
    """解析B站短链接（b23.tv）为完整链接"""
    try:
        # 处理b23.tv短链接
        if "b23.tv" in short_url:
            # 禁止重定向，获取真实链接
            response = requests.head(short_url, allow_redirects=True, timeout=10)
            return response.url
        return short_url
    except Exception as e:
        st.warning(f"解析短链接失败，将尝试直接使用原链接：{str(e)}")
        return short_url

def download_bilibili_audio(url):
    """下载B站视频音频（修复版：强制下载最低清流，绕过登录限制）"""
    clean_audio_dir()
    try:
        # 第一步：解析短链接为完整B站链接
        full_url = resolve_bilibili_short_url(url)
        st.info(f"解析后的完整链接：{full_url}")
        
        # 第二步：用you-get下载，强制选择最低清的流（通常无需登录）
        # 使用 --json 选项获取所有可用流，然后选择第一个（最低清）
        list_command = f"you-get --json {full_url}"
        list_result = subprocess.run(
            list_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if list_result.returncode != 0:
            return None, f"获取视频信息失败：{list_result.stderr}"
        
        # 解析JSON，找到最低清的流ID
        import json
        video_info = json.loads(list_result.stdout)
        streams = video_info.get('streams', {})
        # 按质量从低到高排序，选择第一个
        sorted_streams = sorted(streams.items(), key=lambda x: x[1].get('quality', 9999))
        if not sorted_streams:
            return None, "未找到任何可用的视频流"
        lowest_quality_stream_id = sorted_streams[0][0]
        st.info(f"自动选择最低清流：{lowest_quality_stream_id}")

        # 第三步：下载这个最低清流
        download_command = f"you-get -o audio --format={lowest_quality_stream_id} {full_url}"
        download_result = subprocess.run(
            download_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        # 打印日志（方便排查）
        st.text("下载日志：")
        st.text(download_result.stdout)
        if download_result.stderr:
            st.text("下载错误日志：")
            st.text(download_result.stderr)
        
        # 第四步：查找所有音频/视频文件
        media_extensions = ('.mp4', '.flv', '.mkv', '.webm', '.mp3', '.m4a', '.wav', '.flac', '.ogg', '.aac')
        media_files = []
        for root, dirs, files in os.walk("audio"):
            for file in files:
                if file.lower().endswith(media_extensions):
                    media_files.append(os.path.join(root, file))
        
        if media_files:
            media_path = media_files[-1]
            st.success(f"成功找到媒体文件：{media_path}")
            return media_path, None
        else:
            return None, "未找到媒体文件！可能原因：1.视频无音频 2.you-get未正确下载 3.链接权限问题"
    except subprocess.TimeoutExpired:
        return None, "操作超时，请检查网络或视频链接"
    except Exception as e:
        return None, f"下载失败：{str(e)}"

def audio_to_text(audio_path, model_name="base"):
    """音频转文字"""
    try:
        model = whisper.load_model(model_name)
        result = model.transcribe(audio_path, language="en")
        return result["text"], None
    except Exception as e:
        return None, f"转写失败：{str(e)}"

def translate_text_to_zh(text):
    """调用免费翻译API将英文翻译成中文"""
    try:
        # 备用免费翻译接口（无需API Key）
        url = f"https://fanyi.youdao.com/translate?&doctype=json&type=EN2ZH_CN&i={urllib.parse.quote(text)}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            translations = res.json()["translateResult"][0]
            zh_text = "".join([t["tgt"] for t in translations])
            return zh_text, None
        
        return "", "翻译接口调用失败"
    except Exception as e:
        return "", f"翻译出错：{str(e)}"

def extract_unique_words(text, filter_simple=True):
    """提取去重单词，可选过滤简单词"""
    # 提取英文单词并转小写
    words = re.findall(r"[a-zA-Z]+", text.lower())
    unique_words = sorted(list(set(words)))
    
    # 过滤简单词
    if filter_simple:
        unique_words = [word for word in unique_words if word not in SIMPLE_WORDS and len(word) > 1]
    
    return unique_words

def get_word_definition(word):
    """调用词典API获取释义（包含音标）"""
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()[0]
            # 提取音标（优先英式，没有则取美式）
            phonetics = data.get("phonetics", [])
            phonetic = ""
            for p in phonetics:
                if p.get("text") and "uk" in p.get("audio", "").lower():
                    phonetic = p["text"]
                    break
                elif p.get("text"):
                    phonetic = p["text"]
            
            # 提取核心释义
            meanings = data.get("meanings", [])
            if meanings:
                # 取第一个词性的第一个释义
                pos = meanings[0]["partOfSpeech"]
                definition = meanings[0]["definitions"][0]["definition"]
                # 提取例句（如果有）
                example = meanings[0]["definitions"][0].get("example", "")
                if example:
                    return {
                        "phonetic": phonetic,
                        "definition": f"【{pos}】{definition}",
                        "example": f"例句：{example}"
                    }
                else:
                    return {
                        "phonetic": phonetic,
                        "definition": f"【{pos}】{definition}",
                        "example": ""
                    }
            else:
                return {"phonetic": "", "definition": "无可用释义", "example": ""}
        else:
            return {"phonetic": "", "definition": "查询失败（API返回错误）", "example": ""}
    except Exception as e:
        return {"phonetic": "", "definition": f"查询出错：{str(e)}", "example": ""}

def export_words_to_txt(words_with_def):
    """导出单词和释义到TXT"""
    content = ""
    for word, desc in words_with_def.items():
        content += f"{word} {desc['phonetic']}\n{desc['definition']}\n{desc['example']}\n{'-'*50}\n"
    return content

# ----------------------
# 播放读音的JS函数
# ----------------------
def play_pronunciation_js(word):
    """生成播放单词读音的JavaScript代码"""
    return f"""
    <script>
    // 创建语音合成对象
    const synth = window.speechSynthesis;
    // 创建语音内容
    const utterance = new SpeechSynthesisUtterance("{word}");
    // 设置为英式英语（也可改为'en-US'美式）
    utterance.lang = 'en-GB';
    // 播放语音
    synth.speak(utterance);
    </script>
    """

# ----------------------
# 页面UI
# ----------------------
st.title("📝 B站英文视频单词提取工具")
st.divider()

# 左侧输入区
with st.sidebar:
    st.header("输入设置")
    video_url = st.text_input("B站视频链接", placeholder="例如：https://www.bilibili.com/video/BV1xx411c7mG/ 或 b23.tv/TyCfrFJ")
    filter_simple = st.checkbox("过滤简单基础词（a/the/and等）", value=True)
    model_option = st.selectbox("语音识别模型（越大越准）", ["base", "small", "medium"], index=0)
    translate_switch = st.checkbox("翻译视频文本为中文", value=True)  # 翻译开关
    submit_btn = st.button("开始提取", type="primary", use_container_width=True)

# 右侧结果区
# 调整列布局：原文+翻译 占2/3，单词区占1/3
col_text, col_words = st.columns([2, 1])

if submit_btn and video_url:
    with st.spinner("正在下载音频..."):
        audio_path, error = download_bilibili_audio(video_url)
        if error:
            st.error(error)
            st.stop()
    
    with st.spinner("正在转换语音为文字..."):
        text, error = audio_to_text(audio_path, model_option)
        if error:
            st.error(error)
            st.stop()
    
    # 翻译文本（如果开启开关）
    zh_text = ""
    if translate_switch:
        with st.spinner("正在翻译文本为中文..."):
            zh_text, error = translate_text_to_zh(text)
            if error:
                st.warning(f"翻译提示：{error}")
    
    with st.spinner("正在提取单词并查询释义..."):
        unique_words = extract_unique_words(text, filter_simple)
        # 构建单词-释义字典
        words_dict = {}
        for word in unique_words:
            words_dict[word] = get_word_definition(word)
    
    # 显示结果：原文+翻译
    with col_text:
        st.subheader("📄 视频语音文本")
        # 切换标签：英文原文 / 中文翻译
        tab1, tab2 = st.tabs(["🇬🇧 英文原文", "🇨🇳 中文翻译"])
        with tab1:
            st.text_area("", text, height=400)
        with tab2:
            if zh_text:
                st.text_area("", zh_text, height=400)
            else:
                st.info("暂无翻译结果，请检查网络或翻译接口")
    
    # 显示单词区
    with col_words:
        st.subheader(f"📚 提取的单词（共{len(unique_words)}个）")
        # 显示单词+读音按钮+音标+释义
        for word, desc in words_dict.items():
            # 一行显示：单词 + 读音按钮 + 音标
            col_word, col_btn, col_phonetic = st.columns([2, 1, 3])
            with col_word:
                st.markdown(f"**{word}**")
            with col_btn:
                # 点击按钮播放读音（调用JS）
                if st.button("🔊 听读音", key=word):
                    st.components.v1.html(play_pronunciation_js(word), height=0)
            with col_phonetic:
                if desc["phonetic"]:
                    st.markdown(f"/{desc['phonetic']}/")
                else:
                    st.markdown("-")
            
            # 显示释义和例句
            st.write(desc["definition"])
            if desc["example"]:
                st.caption(desc["example"])
            st.divider()
        
        # 导出功能
        st.download_button(
            label="📥 导出单词表到TXT",
            data=export_words_to_txt(words_dict),
            file_name="bilibili_video_words.txt",
            mime="text/plain",
            use_container_width=True
        )

elif submit_btn and not video_url:
    st.warning("请输入B站视频链接！")

# 底部说明
st.divider()
st.caption("💡 说明：1. 支持B站完整链接和短链接（b23.tv）；2. 首次运行会下载Whisper模型（约1GB）；3. 音频下载和转写可能需要几分钟，请耐心等待；4. 读音功能依赖浏览器语音合成，建议使用Chrome/Edge；5. 翻译功能使用有道免费接口，无需API Key。")
