**PaperCloud-ClassSchedule**

# 🤖新加入QQ机器人🤖 Via NapCat
Ver1.1
似乎NapCat活不长了
*腾讯律师函.pdf*

还是Python哥哥 

| 路径 | 说明 |
|---|---|
| **app/qq.py** | 接口（发消息的） |
| **app/qqsched.py** | 定时任务（课表提醒，值日） |
| **auto-sync/auto-sync.js** |  外部同步服务（NapCat 协议，本地端口能监听哦） |

## 依赖

- NapCat HTTPS作为消息通道
- 群号、访问口令config/secrets.json
- 机器人与站点不互相干扰
