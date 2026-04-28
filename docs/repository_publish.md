# 仓库发布说明 / Repository Publishing Notes

## 中文

### 目标仓库

当前项目发布目标为：

- GitHub: `https://github.com/edmund-xl/MyTxAnalyzer`
- 本地项目目录：`/Users/lei/Documents/New project/onchain-rca-workbench`

### 目录边界

必须只发布 `onchain-rca-workbench` 目录内的工程文件。

不要从 `/Users/lei/Documents/New project` 父目录执行提交或 push，因为父目录下还有其他项目，例如 MegaETH Pentest Workbench 和其他实验目录。误从父目录发布会把不相关项目带入目标仓库。

### 需要排除的本地文件

以下文件或目录不得上传：

- `.env`
- `.local_rca.db`
- `backend/test_rca_workbench.db`
- `.run-*.log`
- `.run-*.pid`
- `.artifacts/`
- `.test_artifacts/`
- `backend/.venv/`
- `frontend/node_modules/`
- `frontend/.next/`
- `frontend/tsconfig.tsbuildinfo`
- `tmp/`
- `vendor/txanalyzer/`

`vendor/txanalyzer/` 不入库。需要 TxAnalyzer 时运行 `scripts/setup_txanalyzer.sh`，该脚本会从官方仓库 clone 到本地。

### 发布前检查

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench
git status --short
git check-ignore .env .local_rca.db backend/test_rca_workbench.db frontend/node_modules frontend/tsconfig.tsbuildinfo vendor/txanalyzer tmp
```

### 发布原则

- 不上传真实 RPC key、Explorer key、LLM key、数据库密码或对象存储密钥。
- `.env.example` 只能保留示例值、公共 RPC 或空 key。
- `.env.example` 中的敏感配置必须使用 `REPLACE_ME_*` 占位符。
- 每次发布前确认 remote 指向 `edmund-xl/MyTxAnalyzer`。
- RCA Workbench 继续使用 `3100/8100`，不得影响 MegaETH Pentest Workbench 的 `3000/4000`。

## English

### Target Repository

The current publishing target is:

- GitHub: `https://github.com/edmund-xl/MyTxAnalyzer`
- Local project directory: `/Users/lei/Documents/New project/onchain-rca-workbench`

### Directory Boundary

Only engineering files inside `onchain-rca-workbench` should be published.

Do not commit or push from the parent directory `/Users/lei/Documents/New project`, because it contains other projects such as MegaETH Pentest Workbench and other experimental folders. Publishing from the parent directory would accidentally include unrelated projects.

### Local Files To Exclude

The following files or directories must not be uploaded:

- `.env`
- `.local_rca.db`
- `backend/test_rca_workbench.db`
- `.run-*.log`
- `.run-*.pid`
- `.artifacts/`
- `.test_artifacts/`
- `backend/.venv/`
- `frontend/node_modules/`
- `frontend/.next/`
- `frontend/tsconfig.tsbuildinfo`
- `tmp/`
- `vendor/txanalyzer/`

`vendor/txanalyzer/` is intentionally not committed. Run `scripts/setup_txanalyzer.sh` when TxAnalyzer is needed; the script clones the official repository locally.

### Pre-publish Check

```bash
cd /Users/lei/Documents/New\ project/onchain-rca-workbench
git status --short
git check-ignore .env .local_rca.db backend/test_rca_workbench.db frontend/node_modules frontend/tsconfig.tsbuildinfo vendor/txanalyzer tmp
```

### Publishing Rules

- Do not upload real RPC keys, explorer keys, LLM keys, database passwords, or object-store secrets.
- `.env.example` may only contain example values, public RPCs, or empty keys.
- Sensitive settings in `.env.example` must use `REPLACE_ME_*` placeholders.
- Confirm that the remote points to `edmund-xl/MyTxAnalyzer` before every push.
- RCA Workbench should continue using `3100/8100` and must not affect the MegaETH Pentest Workbench ports `3000/4000`.
