# Potala-Ticket
布达拉宫小程序余票监控
## 1. 抓包
抓包请自行使用工具去抓包小程序发送的信息，我在这里只提供一点参考，请不要做非法用途

参考工具：Charles

[Mac 教程链接](https://juejin.cn/post/7044427519243583495)

Windows 系统请自行搜索教程
## 2. 获取 URL 及 Token
从你抓包的请求中，你需要获取
* URL
* Token
* Host
* site-id
* version
* Referer

前两个请将其填到.env文件中，后四个填到`get_headers()`函数中
## 3.微信推送
使用的是 Server 酱的微信推送服务，使用教程请看[官网](https://sct.ftqq.com/)

**注册后有七天免费会员功能**，七天后每天推送只能发五天，所以建议开始抢票后再使用能够省钱

注册他的会员一个月需要 8 元，与本人无关，自愿付费
## 4.运行
先按照依赖库

pip install -r requirements.txt

在运行程序即可

python ticket.py
