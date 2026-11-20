# 本次新增：QQ 群机器人

在阶段 1 的基础上，补入群机器人相关代码。

## 新增文件

```
app/qq.py             机器人接口层
app/qqsched.py        定时任务（早报、课表提醒、值班通知）
auto-sync/auto-sync.js 外部同步服务（NapCat + OneBot 协议）
```

## 依赖与配置

- 需要 NapCat 或其他 OneBot 实现作为消息通道
- 群号、访问口令写在 `config/secrets.json`（不入库，见根目录 `.gitignore`）
- 未配置时机器人功能不生效，不影响站点其他部分

## 说明

本阶段只新增机器人代码，不改动阶段 1 已有文件。
