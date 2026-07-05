# 📰 每日新闻联播 + 人民日报 AI总结 & QQ推送

自动采集央视《新闻联播》和《人民日报》每日新闻，调用AI进行深度解读总结，并推送到QQ。

## 运行原理

```
每天08:30 (北京时间)
    ↓
GitHub Actions 自动触发
    ↓
采集新闻联播 "本期节目主要内容"
    +
采集人民日报 头版及重要新闻
    ↓
调用 DeepSeek/Claude API 生成结构化解读
    ↓
通过 Qmsg酱 推送到你的QQ
    ↓
摘要文件自动保存到仓库
```

## 前置准备

### 1. Qmsg酱（QQ推送通道）
1. 打开 [Qmsg酱官网](https://qmsg.zendee.cn/)
2. 用你的QQ号登录
3. 在管理台添加接收QQ（你自己的QQ号）
4. 把机器人添加为QQ好友
5. 获取你的 **KEY**（在管理台可以看到）

### 2. LLM API密钥
使用你现有的 DeepSeek API（通过 Anthropic 兼容接口）：
- API地址：`https://api.deepseek.com/anthropic`
- API Key：你的 sk-... 密钥
- 模型：`DeepSeek-V4-Flash`

## 部署步骤

### 方式一：GitHub Actions（推荐，电脑无需开机）

1. **Fork/创建仓库**
   - 在 GitHub 上创建一个新仓库
   - 将本目录所有文件 push 到该仓库

2. **配置 GitHub Secrets**
   在仓库 Settings → Secrets and variables → Actions 中添加：

   | Secret名称 | 说明 | 示例值 |
   |-----------|------|--------|
   | `LLM_API_KEY` | DeepSeek API Key | `sk-xxxxxxxx` |
   | `LLM_BASE_URL` | API地址 | `https://api.deepseek.com/anthropic` |
   | `LLM_MODEL` | 模型名 | `DeepSeek-V4-Flash` |
   | `QMSG_KEY` | Qmsg酱 KEY | 在Qmsg酱管理台获取 |
   | `QQ_RECEIVER` | 你的QQ号 | `123456789` |

3. **启用 Actions**
   - 进入 Actions 标签页
   - 确认 workflow 已启用
   - 可以点 "Run workflow" 手动测试一次

4. **完成！**
   - 每天 08:30 自动运行
   - 新闻解读会自动推送到你的QQ
   - 摘要文件也会自动提交到仓库

### 方式二：本地运行

```bash
# 设置环境变量
set LLM_API_KEY=sk-xxxx
set QMSG_KEY=your_qmsg_key
set QQ_RECEIVER=your_qq_number

# 运行
python news_summary.py
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `news_summary.py` | 主程序：采集+总结+推送 |
| `.github/workflows/daily_news.yml` | GitHub Actions 定时任务配置 |
| `requirements.txt` | Python依赖 |
| `news_YYYYMMDD.md` | 每日生成的新闻摘要（自动保存） |

## 自定义

- **修改推送时间**：编辑 `.github/workflows/daily_news.yml` 中的 `cron` 表达式
- **修改AI提示词**：编辑 `news_summary.py` 中的 `build_prompt()` 函数
- **增加其他信源**：在 `fetch_xinwen_lianbo()` 同级添加新的采集函数
