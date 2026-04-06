# ProfitAgent

智能盈利管理系统

## 本地启动

`--port` 可换成**任意未被占用的端口**（与浏览器地址里的端口保持一致即可）。下面以 `8080` 为例：

```bash
cd backend
source .venv/bin/activate   # 可选
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

浏览器访问：`http://127.0.0.1:8080/ui/`（若改用其他端口，把 `8080` 一并改掉；根路径 `/` 会重定向到报价台）