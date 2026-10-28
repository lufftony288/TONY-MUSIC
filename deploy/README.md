# 网页测试部署（尚未上线）

需要：Linux 云服务器、Docker Compose、指向服务器的域名、入站 TCP 80/443。
从仓库根目录执行：

```sh
cp deploy/env.example deploy/.env
# 交互输入访问密码，保存输出的哈希到 deploy/.env 的 APP_PASSWORD_HASH（单引号包围）
docker run --rm -it caddy:2-alpine caddy hash-password
# 编辑 deploy/.env：真实域名、登录用户名、密码哈希、可选 Meshy 密钥
# 请勿在聊天或 Git 中发送/提交 .env
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

访问 https://你的域名，输入用户名和访问密码。Caddy 自动申请 TLS 证书。
应用端口不直接映射到公网；所有页面/API 经统一密码保护。
这是单用户/受信测试小组的共享工作台，共用模型库，不提供用户间数据隔离。
数据保存在 app_data 卷；升级保留该卷。不要执行 down -v，除非确实要删除数据。
Meshy 密钥仅作为服务器环境变量传入，不打入前端或镜像；生成仍使用账户额度。
源环境的模型和历史数据不会自动迁移。当前没有部署目标，因此未验证公网访问、证书签发或镜像运行。
