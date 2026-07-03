朗读者 · English News Reader
朗读英文新闻，练听写、练跟读。

粘贴一篇英文新闻正文（或贴链接自动抓取），自动用微软神经语音生成高质量朗读音频。播放时逐句高亮，可调速、可选播音员音色。

截图
启动后访问 http://127.0.0.1:5050

功能
粘贴即读 — 把新闻正文贴进去，一键生成音频
链接提取 — 直接贴 URL，自动抓取正文
逐句高亮 — 播放时当前句子高亮并自动滚动，点击句子跳转播放
6 种语音 — 4 种美音 + 2 种英音，接近真人播音员
5 档语速 — 0.8× 到 1.2×，适合慢速听写和常速跟读
播放控制 — 前进/后退 5 秒、重新播放、进度条拖拽
快速开始
依赖
Python 3.10+
网络连接（TTS 需要访问微软服务）
安装
pip install flask trafilatura edge-tts
启动
python server.py
浏览器打开 http://127.0.0.1:5050。

技术栈
层	技术
后端	Python / Flask
文章提取	trafilatura
语音合成	edge-tts（微软神经 TTS，免费）
前端	原生 HTML/CSS/JS，深色主题
项目结构
reader/
  server.py          # Flask 后端
  templates/
    index.html       # 前端界面
License
MIT
