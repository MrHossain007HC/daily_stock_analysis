# Collector1

隔离的 Apify Python Actor，包名 Collector1，目录 `actors/collector1/`。它只处理公开的 DSE（达卡证券交易所）历史行情与财务文档，不接入 StockNow 私有登录、会话或内部接口，也不改动现有策略、持仓、历史库或其他 Actor。

## 行为

- 公开 URL 必须落在允许的主机上，默认是 `dsebd.org` 与 `sec.gov.bd`。主机名包含 `stocknow` 时一律拒绝。
- 下载前解析 DNS，拒绝私网、回环、链路本地和原始 IP。重定向逐跳复查。不使用代理，不携带认证头。
- ZIP 拒绝路径穿越、加密包、过大展开体积和过高压缩比。
- 原始回执、接受行、隔离行和失败行分开存放。失败记录的 `promoted` 恒为 false。
- 相同 SHA-256 只保留一条规范行情，后到的冲突收盘价进入隔离，不覆盖已接受值。
- 只根据元数据建立的索引，`documentClaim` 为 `metadata_only`，`verifiedAnnualReport` 为 false。
- 请求的交易日没有行情时，覆盖状态是 `unknown` 或来源明确写出的 `non_trading`。`provenMissing` 恒为 false。
- NAV 允许为负数。只有 NAV 为负不会单独导致整行被拒绝。其它字段仍逐项校验。
- 文件名或正文里的公司代码与声明代码冲突时隔离，不把代码改写成另一个代码。
- 检查点版本为 1。已完成的工作项不会在恢复时重跑，也不会把隔离结果提升为接受。

## 本地测试

```bash
python3 -m pytest actors/collector1/tests -q
```

仓库根目录的 `setup.cfg` 把默认测试路径限制在 `tests/`。本包测试是隔离的，不进入现有生产测试套件。

## 部署

部署步骤写在包内 `actors/collector1/README.md` 的 “How to deploy Collector1 later”。需要已有 Apify 账号，由后续流程执行 `apify push`。本包不包含 token，也不发布到 Apify Store。

英文操作说明以包内 README 为准。这里不另写一份英文专题文档。
