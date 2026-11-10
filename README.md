# 1A2X 每日自动签到

给 [1A2X 社区](https://1a2x.com) 用的 GitHub Actions 每日签到：领「香蕉」。

## 原理

- 只用 Cookie 登录态，**不存账号密码**。1A2X 登录页每次都要过人机验证，
  密码脚本登录走不通；但「记住我」是 180 天长效登录，Cookie 能用很久。
- 脚本每次先打开「社区成长」页 `/growth`，解析当天真实的签到表单
  （action + CSRF 等隐藏字段）再提交，不写死接口，站点小改版不易签废。
- 提交后回查成长页确认已签到状态，并打印香蕉数。

## 配置

仓库 Settings → Secrets and variables → Actions → New repository secret：

- Name：`A2X_COOKIE`
- Secret：在自己已登录 1A2x 的浏览器里导出 Cookie 整串（Header String）后**本人直填**，
  不要发到任何聊天里。

## 运行

- 每天北京时间 00:17 / 01:47 / 03:27 / 04:57 四档兜底（GitHub 定时会迟到，
  脚本幂等，重复运行只提示已签到）。
- 也可在 Actions 页手动 Run workflow 试跑。

Cookie 失效时运行会明确报「Cookie 已失效」，重新导出填一次即可。
