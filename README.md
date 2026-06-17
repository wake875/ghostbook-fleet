# 👻 Ghostbook Fleet

对 xnmoe.com 留言板进行**20节点分布式压力测试**，基于 GitHub Actions runner 多IP特性。

## 架构

```
                    ┌─────────────────────────────┐
                    │   GitHub Actions Workflow   │
                    │   workflow_dispatch trigger │
                    └─────────────┬───────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
     ┌────▼────┐            ┌────▼────┐            ┌────▼────┐
     │ Node #1 │            │ Node #2 │    ...     │Node #20 │
     │ 3 threads│           │ 3 threads│           │ 3 threads│
     │ 120s     │           │ 120s     │           │ 120s     │
     │ IP: x.x  │           │ IP: y.y  │           │ IP: z.z  │
     └────┬─────┘           └────┬─────┘           └────┬─────┘
          │                       │                       │
          └───────────────────────┼───────────────────────┘
                                  │
                         ┌────────▼────────┐
                         │  xnmoe.com      │
                         │  Cloudflare CDN │
                         │  FastAPI Origin │
                         └─────────────────┘
```

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `duration` | 120s | 每节点运行时长 |
| `threads` | 3 | 每节点并发线程（历史最优） |

## 关键优化

- **3线程/节点**：历史验证 8线程→服务崩溃，3线程→稳定持续写入
- **X-Forwarded-For 轮换**：每次请求伪造不同全球IP，绕过速率限制
- **4KB 载荷**：每条留言最大填充，加速数据库磁盘消耗
- **浏览器级Headers**：Origin + Referer 绕过 Cloudflare WAF
- **混合内容**：XSS + SSTI + SQLi payload混入，触发多层面处理开销

## 预估火力

| 指标 | 单节点 | 20节点总计 |
|------|--------|-----------|
| 线程数 | 3 | **60** |
| 请求速率 | ~50-200 RPS | **~1000-4000 RPS** |
| 数据写入 | ~20-50 MB | **~400MB-1GB (2min)** |

## 部署

1. Fork 到 wake875
2. Actions → Ghostbook Fleet → Run workflow
3. 填写 duration（秒）和 threads → 触发
